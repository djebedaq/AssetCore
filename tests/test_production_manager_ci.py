from __future__ import annotations

import copy
import io
import json
import ssl
from email.message import Message
from http.client import HTTPException
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from scripts import production_manager_ci as ci

SHA = "a" * 40
UNTRUSTED = "untrusted-response-must-never-be-reported"


@pytest.fixture(autouse=True)
def no_live_github(monkeypatch):
    monkeypatch.setattr(ci, "build_opener", lambda *_: pytest.fail("Live network is forbidden"))


def workflow():
    return {"id": 123, "name": "Build check", "path": ".github/workflows/check.yml",
            "state": "active", "url": f"{ci.API_ROOT}/workflows/123"}


def run(**changes):
    result = {
        "id": 321, "run_number": 10, "run_attempt": 1,
        "workflow_id": 123, "name": "Build check", "path": ".github/workflows/check.yml",
        "event": "push", "head_sha": SHA, "head_branch": "main",
        "status": "completed", "conclusion": "success",
        "repository": {"full_name": "djebedaq/AssetCore", "private": False},
        "head_repository": {"full_name": "djebedaq/AssetCore", "private": False},
        "logs_url": UNTRUSTED, "display_title": UNTRUSTED,
    }
    result.update(changes)
    return result


def jobs(**changes):
    return [{"id": index + 1, "name": name, "run_id": 321, "run_attempt": 1,
             "head_sha": SHA, "status": "completed", "conclusion": "success",
             "runner_name": UNTRUSTED, **changes}
            for index, name in enumerate(sorted(ci.REQUIRED_JOBS))]


def metadata(monkeypatch, *, listed=None, job_rows=None, workflow_data=None,
             list_reads=None, run_reads=None):
    selected_runs = [run()] if listed is None else listed
    workflow_data = workflow() if workflow_data is None else workflow_data
    job_rows = jobs() if job_rows is None else job_rows
    list_reads = [selected_runs] if list_reads is None else list_reads
    run_reads = [max(selected_runs, key=lambda row: row["run_number"])] if (
        run_reads is None and selected_runs) else (run_reads or [])
    requests = []
    counts = {"list": 0, "run": 0}

    def read(path, query=None):
        requests.append((path, query))
        if path == "/workflows/check.yml":
            return copy.deepcopy(workflow_data)
        if path == "/workflows/123/runs":
            assert query["head_sha"] == SHA and query["event"] == "push"
            assert query["branch"] == "main"
            assert "status" not in query and "conclusion" not in query
            data = list_reads[min(counts["list"], len(list_reads) - 1)]
            start = (query["page"] - 1) * query["per_page"]
            rows = data[start:start + query["per_page"]]
            if start + len(rows) == len(data):
                counts["list"] += 1
            return {"total_count": len(data), "workflow_runs": copy.deepcopy(rows)}
        if "/attempts/" in path:
            start = (query["page"] - 1) * query["per_page"]
            rows = job_rows[start:start + query["per_page"]]
            return {"total_count": len(job_rows), "jobs": copy.deepcopy(rows)}
        if path.startswith("/runs/"):
            data = run_reads[min(counts["run"], len(run_reads) - 1)]
            assert path == f"/runs/{data['id']}"
            counts["run"] += 1
            return copy.deepcopy(data)
        pytest.fail("Unexpected fixed GitHub route")

    monkeypatch.setattr(ci, "_api_json", read)
    return requests


def refused(code):
    return pytest.raises(ci.CIError, match=f"^{code}$")


def test_exact_push_success_returns_only_allowlisted_identity(monkeypatch, capsys):
    requests = metadata(monkeypatch)
    assert ci.qualify_ci(SHA) == {"run_id": 321, "run_attempt": 1, "qualified": True}
    assert [path for path, _ in requests] == [
        "/workflows/check.yml", "/workflows/123/runs", "/runs/321",
        "/runs/321/attempts/1/jobs", "/workflows/123/runs", "/runs/321",
    ]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("sha", [None, 1, "", "a" * 39, "a" * 41, "A" * 40,
                                     "main", "latest", "a" * 39 + ";", "a" * 40 + "\n"])
def test_malformed_or_implicit_target_is_refused_before_network(sha):
    with refused("CI_TARGET_INVALID"):
        ci.qualify_ci(sha)


@pytest.mark.parametrize("field,value", [
    ("name", "Another workflow"), ("path", ".github/workflows/other.yml"),
    ("state", "disabled_manually"), ("url", "https://elsewhere.invalid/"),
])
def test_workflow_identity_must_match_fixed_repository(monkeypatch, field, value):
    data = workflow()
    data[field] = value
    metadata(monkeypatch, workflow_data=data)
    with refused("CI_WORKFLOW_MISMATCH"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("field,value", [
    ("event", "pull_request"), ("head_sha", "b" * 40), ("head_branch", "other"),
    ("name", "Other CI"), ("path", ".github/workflows/other.yml"),
    ("workflow_id", 124), ("workflow_id", True),
    ("repository", {"full_name": "another/AssetCore", "private": False}),
    ("head_repository", {"full_name": "another/AssetCore", "private": False}),
    ("repository", {"full_name": "djebedaq/AssetCore", "private": True}),
    ("head_repository", None),
])
def test_wrong_sha_event_branch_repository_or_workflow_refused(monkeypatch, field, value):
    metadata(monkeypatch, listed=[run(**{field: value})])
    with refused("CI_RUN_IDENTITY_MISMATCH"):
        ci.qualify_ci(SHA)


def test_missing_ci_refused(monkeypatch):
    metadata(monkeypatch, listed=[])
    with refused("CI_RUN_MISSING"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("status", [None, "queued", "waiting", "in_progress", "pending"])
def test_pending_ci_refused(monkeypatch, status):
    metadata(monkeypatch, listed=[run(status=status)])
    with refused("CI_RUN_PENDING"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("conclusion", [None, "failure", "cancelled", "skipped", "neutral"])
def test_unsuccessful_ci_refused(monkeypatch, conclusion):
    metadata(monkeypatch, listed=[run(conclusion=conclusion)])
    with refused("CI_RUN_FAILED"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("name", sorted(ci.REQUIRED_JOBS))
def test_each_required_production_job_must_be_present(monkeypatch, name):
    metadata(monkeypatch, job_rows=[row for row in jobs() if row["name"] != name])
    with refused("CI_JOBS_MISSING"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("name", sorted(ci.REQUIRED_JOBS))
@pytest.mark.parametrize("status,conclusion", [
    ("in_progress", None), ("completed", "failure"), ("completed", "skipped"),
])
def test_each_required_job_must_complete_successfully(monkeypatch, name, status, conclusion):
    rows = jobs()
    next(row for row in rows if row["name"] == name).update(
        status=status, conclusion=conclusion)
    metadata(monkeypatch, job_rows=rows)
    with refused("CI_JOB_FAILED"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("change", [
    {"head_sha": "b" * 40}, {"run_id": 999}, {"run_attempt": 2}, {"run_attempt": True},
])
def test_jobs_cannot_belong_to_another_sha_run_or_attempt(monkeypatch, change):
    metadata(monkeypatch, job_rows=jobs(**change))
    with refused("CI_RUN_IDENTITY_MISMATCH"):
        ci.qualify_ci(SHA)


def test_successful_rerun_uses_attempt_specific_endpoint(monkeypatch):
    requests = metadata(monkeypatch, listed=[run(run_attempt=3)], job_rows=jobs(run_attempt=3))
    assert ci.qualify_ci(SHA)["run_attempt"] == 3
    assert "/runs/321/attempts/3/jobs" in [path for path, _ in requests]


def test_attempt_endpoint_is_authoritative_when_job_attempt_field_is_absent(monkeypatch):
    rows = jobs()
    for row in rows:
        del row["run_attempt"]
    metadata(monkeypatch, listed=[run(run_attempt=3)], job_rows=rows)
    assert ci.qualify_ci(SHA)["run_attempt"] == 3


def test_partial_rerun_does_not_borrow_older_successful_jobs(monkeypatch):
    metadata(monkeypatch, listed=[run(run_attempt=2)],
             job_rows=[row for row in jobs(run_attempt=2) if row["name"] == "docker"])
    with refused("CI_JOBS_MISSING"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("pending", [True, False])
def test_older_success_does_not_hide_latest_failed_or_pending_run(monkeypatch, pending):
    newer = run(id=322, run_number=11, status="queued" if pending else "completed",
                conclusion=None if pending else "failure")
    metadata(monkeypatch, listed=[run(), newer])
    with refused("CI_RUN_PENDING" if pending else "CI_RUN_FAILED"):
        ci.qualify_ci(SHA)


def test_latest_run_is_checked_beyond_first_page(monkeypatch):
    rows = [run(id=index + 1, run_number=index + 1) for index in range(101)]
    rows[-1]["conclusion"] = "failure"
    requests = metadata(monkeypatch, listed=rows)
    with refused("CI_RUN_FAILED"):
        ci.qualify_ci(SHA)
    assert [query["page"] for path, query in requests if path.endswith("/runs")] == [1, 2]


def test_job_pagination_does_not_hide_a_required_job(monkeypatch):
    rows = [{**jobs()[0], "id": index + 100, "name": f"additional-{index}"}
            for index in range(100)] + jobs()
    requests = metadata(monkeypatch, job_rows=rows)
    assert ci.qualify_ci(SHA)["qualified"] is True
    assert [query["page"] for path, query in requests if path.endswith("/jobs")] == [1, 2]


@pytest.mark.parametrize("during_jobs", [True, False])
def test_rerun_during_qualification_refused(monkeypatch, during_jobs):
    reads = [run(), run(run_attempt=2)] if during_jobs else [run(run_attempt=2)]
    metadata(monkeypatch, run_reads=reads)
    with refused("CI_METADATA_CHANGED"):
        ci.qualify_ci(SHA)


def test_replacement_run_during_job_check_refused(monkeypatch):
    metadata(monkeypatch, list_reads=[[run()], [run(), run(id=322, run_number=11)]])
    with refused("CI_METADATA_CHANGED"):
        ci.qualify_ci(SHA)


def test_run_must_still_be_successful_after_jobs(monkeypatch):
    metadata(monkeypatch, run_reads=[run(), run(status="queued", conclusion=None)])
    with refused("CI_RUN_PENDING"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("field,value", [
    ("id", 0), ("id", True), ("id", "321"), ("run_attempt", None),
    ("run_attempt", -1), ("run_number", 2**63),
])
def test_ci_identifiers_are_bounded_positive_integers(monkeypatch, field, value):
    metadata(monkeypatch, listed=[run(**{field: value})])
    with refused("CI_METADATA_INVALID"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("kind", ["run_id", "run_number", "job_id", "job_name"])
def test_duplicate_identities_are_ambiguous_and_refused(monkeypatch, kind):
    if kind == "run_id":
        metadata(monkeypatch, listed=[run(), run(run_number=11)])
    elif kind == "run_number":
        metadata(monkeypatch, listed=[run(), run(id=322)])
    elif kind == "job_id":
        rows = jobs()
        rows[-1]["id"] = rows[0]["id"]
        metadata(monkeypatch, job_rows=rows)
    else:
        metadata(monkeypatch, job_rows=jobs() + [{**jobs()[0], "id": 999}])
    with refused("CI_METADATA_INVALID"):
        ci.qualify_ci(SHA)


@pytest.mark.parametrize("body,code", [
    ({"total_count": 501, "workflow_runs": []}, "CI_METADATA_LIMIT"),
    ({"total_count": -1, "workflow_runs": []}, "CI_METADATA_INVALID"),
    ({"total_count": True, "workflow_runs": []}, "CI_METADATA_INVALID"),
    ({"total_count": 1, "workflow_runs": []}, "CI_METADATA_INVALID"),
    ({"total_count": 0, "workflow_runs": [run()]}, "CI_METADATA_INVALID"),
    ({"total_count": 1, "workflow_runs": [None]}, "CI_METADATA_INVALID"),
    ({"total_count": 1, "workflow_runs": {}}, "CI_METADATA_INVALID"),
])
def test_incomplete_malformed_or_excessive_metadata_refused(monkeypatch, body, code):
    monkeypatch.setattr(ci, "_api_json", lambda *_: body)
    with refused(code):
        ci._items("/workflows/123/runs", "workflow_runs")


def test_count_change_during_pagination_refused(monkeypatch):
    pages = iter([{"total_count": 101, "jobs": [{}] * 100},
                  {"total_count": 102, "jobs": [{}] * 2}])
    monkeypatch.setattr(ci, "_api_json", lambda *_: next(pages))
    with refused("CI_METADATA_CHANGED"):
        ci._items("/runs/321/attempts/1/jobs", "jobs")


def transport(monkeypatch, *, body=b"{}", status=200, content_type="application/json",
              response_url=None, error=None):
    calls = []
    stream = io.BytesIO(body)
    headers = Message()
    headers["Content-Type"] = content_type
    headers["Link"] = '<https://untrusted.invalid/private>; rel="next"'

    class Response:
        def __init__(self, url):
            self.status = status
            self.headers = headers
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *_):
            stream.close()

        def geturl(self):
            return self.url if response_url is None else response_url

        def read(self, count):
            assert count == ci.MAX_RESPONSE_BYTES + 1
            return stream.read(count)

    def open_request(request, *, timeout):
        calls.append(request)
        assert timeout == ci.REQUEST_TIMEOUT
        if error is not None:
            raise error
        return Response(request.full_url)

    def build(*handlers):
        assert any(isinstance(handler, ci._NoRedirect) for handler in handlers)
        proxy = next(handler for handler in handlers if isinstance(handler, ci.ProxyHandler))
        assert proxy.proxies == {}
        https = next(handler for handler in handlers if isinstance(handler, ci.HTTPSHandler))
        assert https._context.check_hostname
        assert https._context.verify_mode == ssl.CERT_REQUIRED
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(ci, "build_opener", build)
    return calls


def test_transport_is_token_free_https_bounded_and_does_not_use_link(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", UNTRUSTED)
    monkeypatch.setenv("GH_TOKEN", UNTRUSTED)
    monkeypatch.setenv("HTTPS_PROXY", f"https://{UNTRUSTED}@untrusted.invalid")
    calls = transport(monkeypatch, body=json.dumps({"id": 123}).encode())
    assert ci._api_json("/workflows/check.yml") == {"id": 123}
    assert len(calls) == 1
    assert calls[0].full_url == f"{ci.API_ROOT}/workflows/check.yml"
    assert "Authorization" not in calls[0].headers
    assert UNTRUSTED not in str(calls[0].headers)


@pytest.mark.parametrize("error", [
    URLError(UNTRUSTED), TimeoutError(UNTRUSTED), ssl.SSLError(UNTRUSTED),
    HTTPException(UNTRUSTED),
    HTTPError("https://api.github.com/", 403, UNTRUSTED, {}, io.BytesIO(UNTRUSTED.encode())),
    HTTPError("https://api.github.com/", 404, UNTRUSTED, {}, io.BytesIO(UNTRUSTED.encode())),
])
def test_network_tls_rate_limit_and_http_errors_are_sanitized(monkeypatch, capsys, error):
    transport(monkeypatch, error=error)
    with refused("CI_UNAVAILABLE") as caught:
        ci._api_json("/workflows/check.yml")
    assert caught.value.code == "CI_UNAVAILABLE"
    assert UNTRUSTED not in str(caught.value)
    assert caught.value.__suppress_context__
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("body", [UNTRUSTED.encode(), b"[]", b"null", b"\xff",
                                    b"[" * 2000 + b"]" * 2000])
def test_invalid_json_never_becomes_operator_output(monkeypatch, body):
    transport(monkeypatch, body=body)
    with refused("CI_RESPONSE_INVALID"):
        ci._api_json("/workflows/check.yml")


def test_response_size_limit(monkeypatch):
    transport(monkeypatch, body=b"x" * (ci.MAX_RESPONSE_BYTES + 1))
    with refused("CI_RESPONSE_TOO_LARGE"):
        ci._api_json("/workflows/check.yml")


def test_non_json_content_type_refused(monkeypatch):
    transport(monkeypatch, content_type="text/html")
    with refused("CI_RESPONSE_INVALID"):
        ci._api_json("/workflows/check.yml")


@pytest.mark.parametrize("url", ["http://api.github.com/", "https://untrusted.invalid/",
                                    f"{ci.API_ROOT}/workflows/other.yml"])
def test_every_redirect_refused_including_same_origin(monkeypatch, url):
    transport(monkeypatch, response_url=url)
    with refused("CI_REDIRECT_REFUSED"):
        ci._api_json("/workflows/check.yml")
    with refused("CI_REDIRECT_REFUSED"):
        ci._NoRedirect().redirect_request(None, None, 302, UNTRUSTED, {}, url)


@pytest.mark.parametrize("path", ["https://untrusted.invalid/", "//untrusted.invalid/",
                                     "/workflows/../../anything", "/runs/321?token=value"])
def test_transport_cannot_fetch_arbitrary_urls(path):
    with refused("CI_METADATA_INVALID"):
        ci._api_json(path)
