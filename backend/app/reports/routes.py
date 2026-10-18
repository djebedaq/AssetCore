from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..permissions import Permission, require_permission
from .filters import MAX_EXPORT_ROWS, ReportFilters, Section, naive, report_filters
from .service import Reports

router = APIRouter(prefix="/api/reports", tags=["reports"])
reader = require_permission(Permission.REPORTS_VIEW)


def service(
    f: ReportFilters = Depends(report_filters),
    user: User = Depends(reader),
    db: Session = Depends(get_db),
    as_of: datetime | None = None,
):
    current = datetime.now(UTC).replace(tzinfo=None)
    if as_of and not current - timedelta(hours=24) <= naive(as_of) <= current + timedelta(
        seconds=5
    ):
        raise HTTPException(422, detail={"code": "reports_refresh_required"})
    clock = min(naive(as_of), current) if as_of else current
    if db.get_bind().dialect.name == "postgresql":
        # Authentication has already used its own transaction. A separate read-only
        # repeatable snapshot keeps every chart/table/export query mutually consistent.
        engine = db.get_bind().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        )
        with Session(engine, autoflush=False) as snapshot:
            yield Reports(snapshot, user, f, clock)
    else:
        if db.get_bind().dialect.name == "sqlite":
            connection = db.connection()
            # sqlite3 legacy mode does not begin physical transactions for SELECT.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN")
        yield Reports(db, user, f, clock)


@router.get("/records")
def report_records(
    kind: Literal["machines", "usage", "repairs", "requests"],
    metric: str = Query("", max_length=60),
    page: int = Query(1, ge=1, le=5000),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["newest", "oldest"] = "newest",
    reports: Reports = Depends(service),
):
    return reports.details(kind, metric, page, page_size, sort)


@router.get("/export/{format}")
def export_report(
    format: Literal["pdf", "xlsx"],
    section: Section = "overview",
    language: Literal["bg", "en", "ru"] = "bg",
    reports: Reports = Depends(service),
    expected_digest: str | None = Query(
        None, min_length=64, max_length=64, pattern="^[a-f0-9]{64}$"
    ),
):
    from .exports import export_pdf, export_xlsx

    data = reports.build(section, exporting=True)
    if expected_digest is not None and data["digests"].get(section) != expected_digest:
        raise HTTPException(409, detail={"code": "reports_changed_refresh"})
    if max(data["attention_total"], data["parts_total"], data["articles_total"]) > MAX_EXPORT_ROWS:
        raise HTTPException(
            422, detail={"code": "reports_export_too_large", "limit": MAX_EXPORT_ROWS}
        )
    if section == "compare" and not 2 <= len(reports.f.machine_ids) <= 4:
        raise HTTPException(422, detail={"code": "reports_compare_requires_machines"})
    kinds = (
        [section]
        if section in reports.allowed
        else [k for k, allowed in reports.allowed.items() if allowed]
    )
    details = {}
    for kind in kinds:
        # Include completed repairs opened before the period and old delayed orders too.
        names = {
            "usage": ["issues", "completed_cycles", "issue_hours", "active_issues"],
            "repairs": ["opened", "closed", "current_repairs"],
            "requests": [
                "created",
                "submitted",
                "approved",
                "rejected",
                "cancelled",
                "ordered",
                "delivered",
                "outstanding",
                "delayed",
            ],
        }[kind]
        records = {}
        for name in names:
            page = reports.details(kind, name, 1, MAX_EXPORT_ROWS + 1)
            if page["total"] > MAX_EXPORT_ROWS:
                raise HTTPException(
                    422, detail={"code": "reports_export_too_large", "limit": MAX_EXPORT_ROWS}
                )
            for row in page["items"]:
                records[row["id"]] = row
        details[kind] = list(records.values())
        if kind == "requests":
            events = reports.details("requests", "receipts", 1, MAX_EXPORT_ROWS + 1)
            if events["total"] > MAX_EXPORT_ROWS:
                raise HTTPException(
                    422, detail={"code": "reports_export_too_large", "limit": MAX_EXPORT_ROWS}
                )
            details["receipts"] = events["items"]
    if sum(len(rows) for rows in details.values()) > MAX_EXPORT_ROWS:
        raise HTTPException(
            422, detail={"code": "reports_export_too_large", "limit": MAX_EXPORT_ROWS}
        )
    content = (
        export_pdf(data, details, language)
        if format == "pdf"
        else export_xlsx(data, details, language)
    )
    media = (
        "application/pdf"
        if format == "pdf"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="assetcore-{section}.{format}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/machines/{asset_id}")
def report_machine(asset_id: int, reports: Reports = Depends(service)):
    from dataclasses import replace

    f = replace(reports.f, machine_ids=(asset_id,))
    selected = Reports(reports.db, reports.user, f, reports.now)
    if not selected.machines:
        raise HTTPException(404, detail={"code": "machine_not_found"})
    return selected.build("machine")


@router.get("/{section}")
def report_section(section: Section, reports: Reports = Depends(service)):
    if section == "compare" and not 2 <= len(reports.f.machine_ids) <= 4:
        raise HTTPException(422, detail={"code": "reports_compare_requires_machines"})
    return reports.build(section)
