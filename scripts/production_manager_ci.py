"""Bounded, anonymous GitHub qualification for an explicitly approved release.

Only the public AssetCore Build check push workflow is trusted. No response URL,
pagination link, credential, job output or arbitrary server message is returned
to the operator. A rerun must qualify its current attempt with all required jobs.
"""

from __future__ import annotations

import json
import re
import ssl
from http.client import HTTPException
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

REPOSITORY = "djebedaq/AssetCore"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/actions"
WORKFLOW_PATH = ".github/workflows/check.yml"
WORKFLOW_NAME = "Build check"
REQUIRED_JOBS = frozenset({"backend", "frontend", "postgres", "docker"})
PAGE_SIZE = 100
MAX_ITEMS = 500
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = 15


class CIError(RuntimeError):
    """A stable result code, with no untrusted HTTP or metadata content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CIError("CI_REDIRECT_REFUSED")


def _api_json(path: str, query: dict[str, str | int] | None = None) -> dict[str, Any]:
    # Callers construct paths only from fixed routes and validated integer IDs.
    if not re.fullmatch(r"/(?:workflows/check\.yml|workflows/[0-9]+/runs|"
                        r"runs/[0-9]+(?:/attempts/[0-9]+/jobs)?)", path):
        raise CIError("CI_METADATA_INVALID")
    url = API_ROOT + path
    if query:
        url += "?" + urlencode(query)
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AssetCore-production-manager",
        "Cache-Control": "no-cache",
    })
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect(),
                              HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            if response.geturl() != url or response.status in {301, 302, 303, 307, 308}:
                raise CIError("CI_REDIRECT_REFUSED")
            if response.status != 200:
                raise CIError("CI_UNAVAILABLE")
            if response.headers.get_content_type() not in {
                "application/json", "application/vnd.github+json",
            }:
                raise CIError("CI_RESPONSE_INVALID")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise CIError("CI_RESPONSE_TOO_LARGE")
        result = json.loads(body.decode("utf-8"))
        if not isinstance(result, dict):
            raise CIError("CI_RESPONSE_INVALID")
        return result
    except CIError:
        raise
    except (URLError, OSError, HTTPException):
        raise CIError("CI_UNAVAILABLE") from None
    except (ValueError, UnicodeError, RecursionError):
        raise CIError("CI_RESPONSE_INVALID") from None


def _positive_integer(value: Any) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise CIError("CI_METADATA_INVALID")
    return value


def _items(path: str, key: str, query: dict[str, str | int] | None = None) -> list[dict]:
    """Paginate using constructed URLs; never fetch a server-supplied Link."""
    items: list[dict] = []
    total: int | None = None
    for page in range(1, MAX_ITEMS // PAGE_SIZE + 1):
        result = _api_json(path, {**(query or {}), "per_page": PAGE_SIZE, "page": page})
        count = result.get("total_count")
        rows = result.get(key)
        if type(count) is not int or count < 0 or not isinstance(rows, list):
            raise CIError("CI_METADATA_INVALID")
        if count > MAX_ITEMS:
            raise CIError("CI_METADATA_LIMIT")
        if total is not None and count != total:
            raise CIError("CI_METADATA_CHANGED")
        total = count
        if len(rows) != min(PAGE_SIZE, total - len(items)):
            raise CIError("CI_METADATA_INVALID")
        if any(not isinstance(row, dict) for row in rows):
            raise CIError("CI_METADATA_INVALID")
        items.extend(rows)
        if len(items) == total:
            return items
    raise CIError("CI_METADATA_LIMIT")


def _run_identity(run: dict, sha: str, workflow_id: int) -> tuple[int, int, int]:
    if not isinstance(run, dict):
        raise CIError("CI_METADATA_INVALID")
    # GitHub can include the workflow ref as a path suffix in run metadata.
    if (run.get("event") != "push" or run.get("head_sha") != sha
            or run.get("head_branch") != "main"
            or run.get("name") != WORKFLOW_NAME
            or run.get("path") not in {WORKFLOW_PATH, WORKFLOW_PATH + "@main",
                                        WORKFLOW_PATH + "@refs/heads/main"}
            or type(run.get("workflow_id")) is not int
            or run["workflow_id"] != workflow_id):
        raise CIError("CI_RUN_IDENTITY_MISMATCH")
    for field in ("repository", "head_repository"):
        repository = run.get(field)
        if (not isinstance(repository, dict)
                or repository.get("full_name") != REPOSITORY
                or repository.get("private") is not False):
            raise CIError("CI_RUN_IDENTITY_MISMATCH")
    return (_positive_integer(run.get("id")), _positive_integer(run.get("run_attempt")),
            _positive_integer(run.get("run_number")))


def _require_success(run: dict) -> None:
    if run.get("status") != "completed":
        raise CIError("CI_RUN_PENDING")
    if run.get("conclusion") != "success":
        raise CIError("CI_RUN_FAILED")


def _latest_run(sha: str, workflow_id: int) -> dict:
    # Never filter on success: that could hide a newer failed or pending run.
    runs = _items(f"/workflows/{workflow_id}/runs", "workflow_runs", {
        "head_sha": sha, "event": "push", "branch": "main",
    })
    if not runs:
        raise CIError("CI_RUN_MISSING")
    identities = [_run_identity(run, sha, workflow_id) for run in runs]
    if (len({identity[0] for identity in identities}) != len(runs)
            or len({identity[2] for identity in identities}) != len(runs)):
        raise CIError("CI_METADATA_INVALID")
    return max(runs, key=lambda run: run["run_number"])


def _qualify_jobs(run_id: int, attempt: int, sha: str) -> None:
    jobs = _items(f"/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    seen_ids: set[int] = set()
    seen_required: set[str] = set()
    for job in jobs:
        job_id = _positive_integer(job.get("id"))
        if job_id in seen_ids:
            raise CIError("CI_METADATA_INVALID")
        seen_ids.add(job_id)
        # The endpoint pins the attempt. Validate it too if the API includes it.
        if (type(job.get("run_id")) is not int or job["run_id"] != run_id
                or job.get("head_sha") != sha
                or ("run_attempt" in job and (
                    type(job["run_attempt"]) is not int or job["run_attempt"] != attempt))):
            raise CIError("CI_RUN_IDENTITY_MISMATCH")
        name = job.get("name")
        if not isinstance(name, str):
            raise CIError("CI_METADATA_INVALID")
        if name in REQUIRED_JOBS:
            if name in seen_required:
                raise CIError("CI_METADATA_INVALID")
            seen_required.add(name)
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                raise CIError("CI_JOB_FAILED")
    if seen_required != REQUIRED_JOBS:
        raise CIError("CI_JOBS_MISSING")


def qualify_ci(sha: str) -> dict[str, int | bool]:
    """Return safe run identity only after exact-SHA push CI is established.

    Qualification is a point-in-time observation, not a lock on GitHub. Reread
    run selection and current attempt after the jobs to reject observed reruns,
    replacements and state changes. Any ambiguity fails before deployment.
    """
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise CIError("CI_TARGET_INVALID")
    workflow = _api_json("/workflows/check.yml")
    workflow_id = _positive_integer(workflow.get("id"))
    if (workflow.get("name") != WORKFLOW_NAME or workflow.get("path") != WORKFLOW_PATH
            or workflow.get("state") != "active"
            or workflow.get("url") != f"{API_ROOT}/workflows/{workflow_id}"):
        raise CIError("CI_WORKFLOW_MISMATCH")
    listed = _latest_run(sha, workflow_id)
    identity = _run_identity(listed, sha, workflow_id)
    _require_success(listed)
    run_id, attempt, _ = identity
    current = _api_json(f"/runs/{run_id}")
    if _run_identity(current, sha, workflow_id) != identity:
        raise CIError("CI_METADATA_CHANGED")
    _require_success(current)
    _qualify_jobs(run_id, attempt, sha)
    final_listed = _latest_run(sha, workflow_id)
    if _run_identity(final_listed, sha, workflow_id) != identity:
        raise CIError("CI_METADATA_CHANGED")
    _require_success(final_listed)
    final_current = _api_json(f"/runs/{run_id}")
    if _run_identity(final_current, sha, workflow_id) != identity:
        raise CIError("CI_METADATA_CHANGED")
    _require_success(final_current)
    return {"run_id": run_id, "run_attempt": attempt, "qualified": True}
