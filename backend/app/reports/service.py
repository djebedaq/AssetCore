"""One calculation layer for API, drill-down and both export formats.

Column projections deliberately avoid ORM document relationships and binary evidence.
Bounded column reads keep memory predictable; pagination itself happens in SQL.
"""

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import (
    AssetCategory,
    GeneratedDocument,
    Location,
    Machine,
    OfficialDocument,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    Repair,
    RepairPart,
    RequestApprovalSnapshot,
    RequestDeliveryEvent,
    TransferBatch,
    TransferProtocol,
    User,
)
from ..part_requests.official import quantity, received
from ..part_requests.request_schemas import decimal_text
from ..permissions import Permission, ensure_permission, has_permission
from .filters import (
    ATTENTION_GROWTH_FACTOR,
    ATTENTION_GROWTH_MIN,
    ATTENTION_OPEN_DAYS,
    ATTENTION_REPAIRS,
    ATTENTION_WINDOW_DAYS,
    DELAYED_ORDER_DAYS,
    MAX_SOURCE_ROWS,
    SOFIA,
    ReportFilters,
    naive,
)

MODULES = {
    "usage": Permission.TRANSFERS_VIEW,
    "repairs": Permission.REPAIRS_VIEW,
    "requests": Permission.REQUESTS_VIEW,
}
TERMINAL_REQUESTS = {"DELIVERED", "REJECTED", "CANCELLED"}


def bounded(db, statement, maximum=MAX_SOURCE_ROWS):
    rows = db.execute(statement.limit(maximum + 1)).mappings().all()
    if len(rows) > maximum:
        raise HTTPException(422, detail={"code": "reports_scope_too_large", "limit": maximum})
    return [dict(row) for row in rows]


def text_match(q, *columns):
    term = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(*(column.ilike(f"%{term}%", escape="\\") for column in columns))


def machine_scope(f):
    conditions = []
    if f.category_id:
        conditions.append(Machine.category_id == f.category_id)
    if f.uncategorized:
        conditions.append(Machine.category_id.is_(None))
    if f.machine_ids:
        conditions.append(Machine.id.in_(f.machine_ids))
    return select(Machine.id).where(*conditions)


def machine_search(q):
    return select(Machine.id).where(
        text_match(
            q,
            Machine.inventory_number,
            Machine.serial_number,
            Machine.name,
            Machine.model,
            Machine.brand,
        )
    )


def scope(statement, model, machine_column, f, *reference_columns, general=False, documents=False):
    if f.category_id or f.uncategorized or f.machine_ids or not general:
        statement = statement.where(machine_column.in_(machine_scope(f)))
    if f.q:
        matches = [machine_column.in_(machine_search(f.q)), text_match(f.q, *reference_columns)]
        if documents:
            if model is TransferProtocol:
                matches.append(
                    model.id.in_(
                        select(OfficialDocument.transfer_id).where(
                            text_match(f.q, OfficialDocument.document_number)
                        )
                    )
                )
                matches.append(
                    model.batch_id.in_(
                        select(OfficialDocument.batch_id).where(
                            text_match(f.q, OfficialDocument.document_number)
                        )
                    )
                )
            else:
                linked = (
                    GeneratedDocument.repair_id
                    if model is Repair
                    else GeneratedDocument.part_request_id
                )
                matches.append(
                    model.id.in_(
                        select(linked).where(text_match(f.q, GeneratedDocument.document_number))
                    )
                )
        statement = statement.where(or_(*matches))
    return statement


def statements(f, documents=False):
    # A request linked through a repair has the same machine as in the canonical workspace.
    request_machine = func.coalesce(
        PartRequest.machine_id,
        select(Repair.machine_id).where(Repair.id == PartRequest.repair_id).scalar_subquery(),
    )
    transfers = (
        select(*TransferProtocol.__table__.c)
        .outerjoin(TransferBatch, TransferBatch.id == TransferProtocol.batch_id)
        .where(
            TransferProtocol.issue_status == "COMPLETED",
            TransferProtocol.issued_at.is_not(None),
            or_(TransferBatch.id.is_(None), TransferBatch.status != "CANCELLED"),
        )
    )
    transfers = scope(
        transfers,
        TransferProtocol,
        TransferProtocol.machine_id,
        f,
        TransferProtocol.protocol_number,
        TransferBatch.batch_reference,
        documents=documents,
    )
    repairs = scope(
        select(*Repair.__table__.c),
        Repair,
        Repair.machine_id,
        f,
        Repair.repair_reference,
        Repair.reported_problem,
        Repair.diagnosis,
        documents=documents,
    )
    requests = scope(
        select(
            *PartRequest.__table__.c,
            request_machine.label("effective_machine_id"),
            RequestApprovalSnapshot.official_number,
        ).outerjoin(RequestApprovalSnapshot, RequestApprovalSnapshot.request_id == PartRequest.id),
        PartRequest,
        request_machine,
        f,
        PartRequest.request_reference,
        RequestApprovalSnapshot.official_number,
        PartRequest.part_name,
        PartRequest.part_number,
        general=True,
        documents=documents,
    )
    return {"usage": transfers, "repairs": repairs, "requests": requests}


def hours(start, end):
    if not start or not end or naive(end) < naive(start):
        return None
    return (naive(end) - naive(start)).total_seconds() / 3600


def average(values):
    usable = [value for value in values if value is not None]
    return (round(sum(usable) / len(usable), 4) if usable else None), len(usable)


def is_returned(row):
    return row["return_status"] == "COMPLETED" and row["returned_at"] is not None


def ongoing(row):
    # Active relationship is authoritative, including an awaiting return signature.
    return bool(row["is_active"]) and not is_returned(row)


def receipts(row):
    reversed_ids = {e.correction_of_id for e in row["events"] if e.correction_of_id is not None}
    return [e for e in row["events"] if e.kind == "RECEIPT" and e.id not in reversed_ids]


def overlap(row, f, now):
    end = naive(row["returned_at"]) if is_returned(row) else now if ongoing(row) else None
    if end is None:
        return None
    start = max(naive(row["issued_at"]), f.start)
    return max(0, (min(end, f.end, now) - start).total_seconds() / 3600)


def metric(key, value, *, previous=None, unit="count", sample=None, drill=None, current=False):
    return {
        "key": key,
        "value": round(value, 4) if isinstance(value, float) else value,
        "previous": previous,
        "change": value - previous if value is not None and previous is not None else None,
        "percent": round((value - previous) / previous * 100, 2)
        if value is not None and previous is not None and previous != 0
        else None,
        "unit": unit,
        "sample": sample,
        "drill": drill,
        "current": current,
    }


def period_metrics(kind, rows, f, now):
    p = f.previous()
    result = []

    def count(key, predicate, timestamp, drill=None):
        result.append(
            metric(
                key,
                sum(bool(predicate(r) and f.includes(r[timestamp])) for r in rows),
                previous=sum(bool(predicate(r) and p.includes(r[timestamp])) for r in rows),
                drill=drill or key,
            )
        )

    def avg(key, values, unit="hours", drill=None):
        value, sample = average(values)
        result.append(metric(key, value, unit=unit, sample=sample, drill=drill))

    if kind == "usage":
        count("issues", lambda r: True, "issued_at")
        result.append(
            metric(
                "unique_issued",
                len({r["machine_id"] for r in rows if f.includes(r["issued_at"])}),
                previous=len({r["machine_id"] for r in rows if p.includes(r["issued_at"])}),
                drill="issues",
            )
        )
        count("completed_cycles", is_returned, "returned_at")
        result.append(
            metric(
                "still_issued",
                sum(ongoing(r) and f.includes(r["issued_at"]) for r in rows),
                drill="still_issued",
            )
        )
        result.append(
            metric(
                "active_issues", sum(ongoing(r) for r in rows), drill="active_issues", current=True
            )
        )
        avg(
            "avg_cycle_hours",
            [
                hours(r["issued_at"], r["returned_at"])
                for r in rows
                if is_returned(r) and f.includes(r["returned_at"])
            ],
            drill="completed_cycles",
        )
        result.append(
            metric(
                "issue_hours",
                sum(overlap(r, f, now) or 0 for r in rows),
                unit="hours",
                drill="issue_hours",
            )
        )
        count(
            "returned_ready",
            lambda r: is_returned(r) and r["return_next_status"] == "READY",
            "returned_at",
        )
        count(
            "returned_repair",
            lambda r: is_returned(r) and r["return_next_status"] == "REPAIR",
            "returned_at",
        )
        denominator = next(m["value"] for m in result if m["key"] == "completed_cycles")
        numerator = next(m["value"] for m in result if m["key"] == "returned_repair")
        result.append(
            metric(
                "return_repair_percent",
                numerator / denominator * 100 if denominator else None,
                unit="percent",
                sample=denominator,
                drill="returned_repair",
            )
        )
        count(
            "returned_damage", lambda r: is_returned(r) and bool(r["return_damage"]), "returned_at"
        )
        count(
            "returned_missing",
            lambda r: is_returned(r) and bool(r["return_missing_equipment"]),
            "returned_at",
        )
    elif kind == "repairs":
        count("opened", lambda r: True, "opened_at")
        count("closed", lambda r: r["status"] == "COMPLETED", "closed_at")
        result.append(
            metric(
                "current_repairs",
                sum(r["status"] != "COMPLETED" for r in rows),
                current=True,
                drill="current_repairs",
            )
        )
        closed = [r for r in rows if r["status"] == "COMPLETED" and f.includes(r["closed_at"])]
        avg(
            "calendar_hours",
            [hours(r["opened_at"], r["closed_at"]) for r in closed],
            drill="closed",
        )
        avg(
            "started_hours",
            [hours(r["started_at"], r["closed_at"]) for r in closed],
            drill="closed",
        )
        opened = [r for r in rows if f.includes(r["opened_at"])]
        for field in ("diagnosis_minutes", "repair_minutes", "testing_minutes"):
            values = [r[field] for r in opened if r[field] is not None]
            result.append(
                metric(
                    field,
                    sum(values) if values else None,
                    unit="minutes",
                    sample=len(values),
                    drill="opened",
                )
            )
            avg("avg_" + field, values, unit="minutes", drill="opened")
        labor = [
            sum(r[k] for k in ("diagnosis_minutes", "repair_minutes", "testing_minutes"))
            for r in opened
            if all(
                r[k] is not None for k in ("diagnosis_minutes", "repair_minutes", "testing_minutes")
            )
        ]
        result.append(
            metric(
                "labor_minutes",
                sum(labor) if labor else None,
                unit="minutes",
                sample=len(labor),
                drill="opened",
            )
        )
    else:
        result.append(
            metric(
                "receipts",
                sum(f.includes(e.occurred_at) for r in rows for e in receipts(r)),
                previous=sum(p.includes(e.occurred_at) for r in rows for e in receipts(r)),
                drill="receipts",
            )
        )
        for key, field in (
            ("created", "created_at"),
            ("submitted", "submitted_at"),
            ("ordered", "ordered_at"),
        ):
            count(key, lambda r: True, field)
        for key, decision in (("approved", "APPROVED"), ("rejected", "REJECTED")):
            result.append(
                metric(
                    key,
                    sum(
                        any(d == decision and f.includes(at) for d, at in r["decisions"])
                        for r in rows
                    ),
                    previous=sum(
                        any(d == decision and p.includes(at) for d, at in r["decisions"])
                        for r in rows
                    ),
                    drill=key,
                )
            )
        count("cancelled", lambda r: r["status"] == "CANCELLED", "cancelled_at")
        count(
            "delivered",
            lambda r: r["status"] == "DELIVERED" and r["remaining_lines"] == 0 and bool(r["lines"]),
            "delivered_at",
        )
        cohort = [r for r in rows if f.includes(r["created_at"])]
        result.append(
            metric(
                "partial",
                sum(r["status"] == "PARTIALLY_DELIVERED" for r in cohort),
                drill="partial",
            )
        )
        for key, predicate in (
            ("pending_requests", lambda r: r["status"] not in TERMINAL_REQUESTS),
            (
                "outstanding",
                lambda r: r["status"] not in TERMINAL_REQUESTS and r["remaining_lines"] > 0,
            ),
            ("waiting_order", lambda r: r["status"] == "APPROVED" and not r["ordered_at"]),
            ("delayed", lambda r: r["delayed"]),
        ):
            result.append(metric(key, sum(predicate(r) for r in rows), current=True, drill=key))
        avg(
            "delivery_hours",
            [
                hours(r["ordered_at"], r["delivered_at"])
                for r in rows
                if r["status"] == "DELIVERED"
                and r["remaining_lines"] == 0
                and r["lines"]
                and f.includes(r["delivered_at"])
            ],
            drill="delivered",
        )
    return result


class Reports:
    def __init__(self, db: Session, user: User, f: ReportFilters, now=None):
        ensure_permission(user, Permission.REPORTS_VIEW)
        ensure_permission(user, Permission.ASSETS_VIEW)
        self.db, self.user, self.f = db, user, f
        self.now = naive(now or datetime.now(UTC))
        f = self.f = replace(f, cutoff=self.now)
        self.allowed = {
            kind: has_permission(user, permission) for kind, permission in MODULES.items()
        }
        self.queries = statements(f, has_permission(user, Permission.DOCUMENTS_VIEW))
        self.sources = {}
        self._attention = None
        active = exists(
            select(TransferProtocol.id).where(
                TransferProtocol.machine_id == Machine.id,
                TransferProtocol.is_active.is_(True),
                TransferProtocol.issue_status == "COMPLETED",
            )
        )
        statement = select(
            Machine.id,
            Machine.inventory_number,
            Machine.name,
            Machine.brand,
            Machine.model,
            Machine.category_id,
            Machine.category,
            Location.name.label("location"),
            case((active, "ISSUED"), else_=Machine.status).label("status"),
            AssetCategory.name_bg,
            AssetCategory.name_en,
            AssetCategory.name_ru,
        )
        statement = (
            statement.outerjoin(Location, Location.id == Machine.location_id)
            .outerjoin(AssetCategory, AssetCategory.id == Machine.category_id)
            .where(Machine.id.in_(machine_scope(f)))
        )
        if f.q:
            matches = [Machine.id.in_(machine_search(f.q))]
            for kind, permitted in self.allowed.items():
                if permitted:
                    q = self.queries[kind].subquery()
                    matches.append(
                        Machine.id.in_(
                            select(
                                q.c.effective_machine_id if kind == "requests" else q.c.machine_id
                            )
                        )
                    )
            if has_permission(user, Permission.DOCUMENTS_VIEW):
                matches.append(
                    Machine.id.in_(
                        select(OfficialDocument.machine_id).where(
                            text_match(f.q, OfficialDocument.document_number)
                        )
                    )
                )
            statement = statement.where(or_(*matches))
        self.machines = bounded(
            db, statement.order_by(Machine.inventory_number, Machine.id), 10_000
        )
        self.machine_map = {m["id"]: m for m in self.machines}

    def load(self, kind):
        ensure_permission(self.user, MODULES[kind])
        if kind in self.sources:
            return self.sources[kind]
        f, now = self.f, self.now
        earliest = min(f.previous().start, now - timedelta(days=ATTENTION_WINDOW_DAYS * 2))
        query = self.queries[kind]
        if kind == "usage":
            query = query.where(
                TransferProtocol.issued_at <= now,
                or_(
                    TransferProtocol.issued_at >= earliest,
                    TransferProtocol.returned_at >= earliest,
                    TransferProtocol.is_active.is_(True),
                ),
            )
        elif kind == "repairs":
            query = query.where(
                Repair.opened_at <= now,
                or_(
                    Repair.opened_at >= earliest,
                    Repair.closed_at >= earliest,
                    Repair.status != "COMPLETED",
                ),
            )
        # Requests include old open orders and timestamped decisions. No retrospective status reconstruction.
        if kind == "requests":
            query = query.where(PartRequest.created_at <= now)
        self.queries[kind] = query
        rows = bounded(self.db, query)
        for row in rows:
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = naive(value)
        if kind == "requests":
            ids = self.queries[kind].with_only_columns(PartRequest.id).order_by(None)
            lines = bounded(
                self.db,
                select(*PartRequestLine.__table__.c).where(PartRequestLine.request_id.in_(ids)),
            )
            events = bounded(
                self.db,
                select(
                    RequestDeliveryEvent.id,
                    RequestDeliveryEvent.request_id,
                    RequestDeliveryEvent.kind,
                    RequestDeliveryEvent.quantities,
                    RequestDeliveryEvent.occurred_at,
                    RequestDeliveryEvent.correction_of_id,
                ).where(RequestDeliveryEvent.request_id.in_(ids)),
            )
            decisions = bounded(
                self.db,
                select(
                    PartRequestApproval.request_id,
                    PartRequestApproval.decision,
                    PartRequestApproval.decided_at,
                ).where(PartRequestApproval.request_id.in_(ids)),
            )
            by_line, by_event, by_decision = defaultdict(list), defaultdict(list), defaultdict(list)
            for line in lines:
                by_line[line["request_id"]].append(SimpleNamespace(**line))
            for event in events:
                by_event[event["request_id"]].append(SimpleNamespace(**event))
            for d in decisions:
                by_decision[d["request_id"]].append((d["decision"], d["decided_at"]))
            for r in rows:
                r["machine_id"] = r["effective_machine_id"]
                r["lines"], r["events"], r["decisions"] = (
                    by_line[r["id"]],
                    by_event[r["id"]],
                    by_decision[r["id"]],
                )
                totals = received(SimpleNamespace(lines=r["lines"], delivery_events=r["events"]))
                r["remaining"] = [
                    {
                        "id": line.id,
                        "part_number": line.part_number,
                        "description": line.description,
                        "unit": line.unit,
                        "quantity": decimal_text(max(Decimal(0), quantity(line) - totals[line.id])),
                    }
                    for line in r["lines"]
                    if quantity(line) > totals[line.id]
                ]
                r["remaining_lines"] = len(r["remaining"])
                # A missing line history is unknown, never fabricated from the legacy header quantity.
                r["elapsed_days"] = (
                    (
                        now.replace(tzinfo=UTC).astimezone(SOFIA).date()
                        - r["ordered_at"].replace(tzinfo=UTC).astimezone(SOFIA).date()
                    ).days
                    if r["ordered_at"]
                    else None
                )
                r["delayed"] = bool(
                    r["status"] in {"ORDERED", "PARTIALLY_DELIVERED"}
                    and r["ordered_at"]
                    and r["remaining_lines"] > 0
                    and r["elapsed_days"] > DELAYED_ORDER_DAYS
                )
        self.sources[kind] = rows
        return rows

    def trends(self, kinds):
        f = self.f
        monthly = (f.date_to - f.date_from).days > 120
        buckets = {}
        day = f.date_from
        while day <= f.date_to:
            label = (
                day.strftime("%Y-%m")
                if monthly
                else (day - timedelta(days=day.weekday())).isoformat()
            )
            buckets.setdefault(label, {"period": label})
            day += timedelta(days=1)
        for kind in kinds:
            rows = self.load(kind)
            events = (
                [("issues", r["issued_at"]) for r in rows]
                + [("completed_cycles", r["returned_at"]) for r in rows if is_returned(r)]
                if kind == "usage"
                else (
                    [("opened", r["opened_at"]) for r in rows]
                    + [("closed", r["closed_at"]) for r in rows if r["status"] == "COMPLETED"]
                    if kind == "repairs"
                    else [("created", r["created_at"]) for r in rows]
                    + [("receipts", e.occurred_at) for r in rows for e in receipts(r)]
                )
            )
            for key, at in events:
                if f.includes(at):
                    d = naive(at).replace(tzinfo=UTC).astimezone(SOFIA).date()
                    label = (
                        d.strftime("%Y-%m")
                        if monthly
                        else (d - timedelta(days=d.weekday())).isoformat()
                    )
                    buckets[label][key] = buckets[label].get(key, 0) + 1
        for bucket in buckets.values():
            for kind in kinds:
                for key in {
                    "usage": ("issues", "completed_cycles"),
                    "repairs": ("opened", "closed"),
                    "requests": ("created", "receipts"),
                }[kind]:
                    bucket.setdefault(key, 0)
        return list(buckets.values())

    def attention(self):
        if self._attention is not None:
            return self._attention
        if not self.allowed["repairs"]:
            return []
        repairs = self.load("repairs")
        transfers = self.load("usage") if self.allowed["usage"] else []
        recent_start = self.now - timedelta(days=ATTENTION_WINDOW_DAYS)
        previous_start = recent_start - timedelta(days=ATTENTION_WINDOW_DAYS)
        if self.f.q:
            # Search selects machines; objective attention criteria use their complete
            # relevant history, not only problem descriptions matching the search.
            queries = statements(replace(self.f, q=""))
            repairs = bounded(
                self.db,
                queries["repairs"].where(
                    Repair.machine_id.in_(self.machine_map),
                    Repair.opened_at <= self.now,
                    or_(Repair.opened_at >= previous_start, Repair.status != "COMPLETED"),
                ),
            )
            if self.allowed["usage"]:
                transfers = bounded(
                    self.db,
                    queries["usage"].where(
                        TransferProtocol.machine_id.in_(self.machine_map),
                        TransferProtocol.issued_at <= self.now,
                        TransferProtocol.returned_at >= recent_start,
                        TransferProtocol.returned_at <= self.now,
                    ),
                )
        grouped, returned = defaultdict(list), defaultdict(list)
        for r in repairs:
            grouped[r["machine_id"]].append(r)
        for r in transfers:
            if (
                is_returned(r)
                and r["return_next_status"] == "REPAIR"
                and naive(r["returned_at"]) >= recent_start
            ):
                returned[r["machine_id"]].append(r)
        result = []
        for mid, machine in self.machine_map.items():
            records = grouped[mid]
            recent = [r for r in records if r["opened_at"] >= recent_start]
            previous = [r for r in records if previous_start <= r["opened_at"] < recent_start]
            long = [
                r
                for r in records
                if r["status"] != "COMPLETED"
                and r["opened_at"] < self.now - timedelta(days=ATTENTION_OPEN_DAYS)
            ]
            reasons = []
            if len(recent) >= ATTENTION_REPAIRS:
                reasons.append(
                    {"code": "frequent", "count": len(recent), "days": ATTENTION_WINDOW_DAYS}
                )
            if long:
                reasons.append({"code": "long", "count": len(long), "days": ATTENTION_OPEN_DAYS})
            if (
                len(recent) >= ATTENTION_GROWTH_MIN
                and previous
                and len(recent) >= len(previous) * ATTENTION_GROWTH_FACTOR
            ):
                reasons.append(
                    {
                        "code": "growth",
                        "count": len(recent),
                        "previous": len(previous),
                        "days": ATTENTION_WINDOW_DAYS,
                    }
                )
            if returned[mid]:
                reasons.append(
                    {"code": "return", "count": len(returned[mid]), "days": ATTENTION_WINDOW_DAYS}
                )
            if reasons:
                result.append(
                    {
                        "machine": machine,
                        "reasons": reasons,
                        "open_count": sum(r["status"] != "COMPLETED" for r in records),
                    }
                )
        self._attention = sorted(
            result,
            key=lambda r: (
                -len(r["reasons"]),
                r["machine"]["inventory_number"],
                r["machine"]["id"],
            ),
        )
        return self._attention

    def matches(self, kind, name):
        """SQL predicates shared by paginated and exported detail rows."""
        f, now = self.f, self.now

        def within(column):
            return and_(column >= f.start, column < f.end, column <= now)

        if kind == "machines":
            ids = [
                m["id"] for m in self.machines if name == "total_machines" or m["status"] == name
            ]
            return Machine.id.in_(ids)
        if kind == "usage":
            final = and_(
                TransferProtocol.return_status == "COMPLETED",
                TransferProtocol.returned_at.is_not(None),
            )
            active = and_(TransferProtocol.is_active.is_(True), ~final)
            mapping = {
                "issues": within(TransferProtocol.issued_at),
                "unique_issued": within(TransferProtocol.issued_at),
                "completed_cycles": and_(final, within(TransferProtocol.returned_at)),
                "still_issued": and_(active, within(TransferProtocol.issued_at)),
                "active_issues": active,
                "issue_hours": and_(
                    TransferProtocol.issued_at < min(f.end, now),
                    or_(and_(final, TransferProtocol.returned_at > f.start), active),
                ),
            }
            for key, column, value in (
                ("returned_ready", TransferProtocol.return_next_status, "READY"),
                ("returned_repair", TransferProtocol.return_next_status, "REPAIR"),
            ):
                mapping[key] = and_(final, within(TransferProtocol.returned_at), column == value)
            for key, column in (
                ("returned_damage", TransferProtocol.return_damage),
                ("returned_missing", TransferProtocol.return_missing_equipment),
            ):
                mapping[key] = and_(
                    final, within(TransferProtocol.returned_at), column.is_not(None), column != ""
                )
            if name == "attention_returns":
                return and_(
                    final,
                    TransferProtocol.return_next_status == "REPAIR",
                    TransferProtocol.returned_at >= now - timedelta(days=ATTENTION_WINDOW_DAYS),
                )
            return mapping.get(name, mapping["issues"])
        if kind == "repairs":
            mapping = {
                "opened": within(Repair.opened_at),
                "closed": and_(Repair.status == "COMPLETED", within(Repair.closed_at)),
                "current_repairs": Repair.status != "COMPLETED",
                "attention": or_(
                    Repair.opened_at >= now - timedelta(days=ATTENTION_WINDOW_DAYS),
                    and_(
                        Repair.status != "COMPLETED",
                        Repair.opened_at < now - timedelta(days=ATTENTION_OPEN_DAYS),
                    ),
                ),
            }
            return mapping.get(name, mapping["opened"])
        rows = self.load("requests")

        def selected(r):
            if name in {"approved", "rejected"}:
                return any(d == name.upper() and f.includes(at) for d, at in r["decisions"])
            if name == "partial":
                return r["status"] == "PARTIALLY_DELIVERED" and f.includes(r["created_at"])
            if name == "pending_requests":
                return r["status"] not in TERMINAL_REQUESTS
            if name == "outstanding":
                return r["status"] not in TERMINAL_REQUESTS and r["remaining_lines"] > 0
            if name == "waiting_order":
                return r["status"] == "APPROVED" and not r["ordered_at"]
            if name == "delayed":
                return r["delayed"]
            if name == "delivered":
                return (
                    r["status"] == "DELIVERED"
                    and r["remaining_lines"] == 0
                    and bool(r["lines"])
                    and f.includes(r["delivered_at"])
                )
            field = {
                "created": "created_at",
                "submitted": "submitted_at",
                "ordered": "ordered_at",
                "cancelled": "cancelled_at",
            }.get(name, "created_at")
            return f.includes(r[field]) and (name != "cancelled" or r["status"] == "CANCELLED")

        return PartRequest.id.in_([r["id"] for r in rows if selected(r)])

    def details(self, kind, name, page=1, page_size=20, sort="newest"):
        if kind == "machines":
            # Machines are a bounded projection already loaded for current status and category counts.
            rows = [m for m in self.machines if name == "total_machines" or m["status"] == name]
            return self.page(
                rows[(page - 1) * page_size : page * page_size], len(rows), page, page_size
            )
        self.load(kind)
        if (kind, name) in {("repairs", "attention"), ("usage", "attention_returns")}:
            model = Repair if kind == "repairs" else TransferProtocol
            timestamp = model.opened_at if kind == "repairs" else model.returned_at
            query = statements(replace(self.f, q=""))[kind].where(
                model.machine_id.in_(self.machine_map),
                self.matches(kind, name),
                timestamp <= self.now,
            )
            total = self.db.scalar(select(func.count()).select_from(query.subquery()))
            order = (
                (timestamp.asc(), model.id.asc())
                if sort == "oldest"
                else (timestamp.desc(), model.id.desc())
            )
            records = (
                self.db.execute(
                    query.order_by(*order).offset((page - 1) * page_size).limit(page_size)
                )
                .mappings()
                .all()
            )
            return self.page(
                [self.record(kind, dict(row)) for row in records], total, page, page_size
            )
        if kind == "requests" and name == "receipts":
            corrected = aliased(RequestDeliveryEvent)
            query = select(RequestDeliveryEvent.id, RequestDeliveryEvent.request_id).where(
                RequestDeliveryEvent.request_id.in_(
                    self.queries[kind].with_only_columns(PartRequest.id)
                ),
                RequestDeliveryEvent.kind == "RECEIPT",
                RequestDeliveryEvent.occurred_at <= self.now,
                RequestDeliveryEvent.occurred_at >= self.f.start,
                RequestDeliveryEvent.occurred_at < self.f.end,
                ~exists(
                    select(corrected.id).where(
                        corrected.correction_of_id == RequestDeliveryEvent.id
                    )
                ),
            )
            total = self.db.scalar(select(func.count()).select_from(query.subquery()))
            order = (
                (RequestDeliveryEvent.occurred_at.asc(), RequestDeliveryEvent.id.asc())
                if sort == "oldest"
                else (RequestDeliveryEvent.occurred_at.desc(), RequestDeliveryEvent.id.desc())
            )
            events = self.db.execute(
                query.order_by(*order).offset((page - 1) * page_size).limit(page_size)
            ).all()
            by_id = {r["id"]: r for r in self.load(kind)}
            items = []
            for event_id, request_id in events:
                record = self.record(kind, by_id[request_id])
                event = next(e for e in by_id[request_id]["events"] if e.id == event_id)
                record.update(id=event_id, original_id=request_id, created_at=event.occurred_at)
                items.append(record)
            return self.page(items, total, page, page_size)
        model, timestamp = {
            "usage": (TransferProtocol, TransferProtocol.issued_at),
            "repairs": (Repair, Repair.opened_at),
            "requests": (PartRequest, PartRequest.created_at),
        }[kind]
        query = self.queries[kind].where(self.matches(kind, name))
        total = self.db.scalar(select(func.count()).select_from(query.subquery()))
        order = (
            (timestamp.asc(), model.id.asc())
            if sort == "oldest"
            else (timestamp.desc(), model.id.desc())
        )
        ids = (
            self.db.execute(
                query.with_only_columns(model.id)
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        by_id = {r["id"]: r for r in self.load(kind)}
        items = [self.record(kind, by_id[identifier]) for identifier in ids if identifier in by_id]
        return self.page(items, total, page, page_size)

    @staticmethod
    def page(items, total, page, page_size):
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "has_previous": page > 1,
            "has_next": page * page_size < total,
        }

    def record(self, kind, row):
        machine = self.machine_map.get(row["machine_id"])
        # General requests and q matching a reference can be outside machine-search matches.
        result = {
            "id": row["id"],
            "machine_id": row["machine_id"],
            "machine": machine,
            "module": {"usage": "transfers", "repairs": "repairs", "requests": "parts"}[kind],
        }
        fields = {
            "usage": (
                "protocol_number",
                "issued_at",
                "returned_at",
                "issue_status",
                "return_status",
                "return_next_status",
                "return_damage",
                "return_missing_equipment",
                "batch_id",
                "is_active",
            ),
            "repairs": (
                "repair_reference",
                "reported_problem",
                "diagnosis",
                "status",
                "opened_at",
                "started_at",
                "closed_at",
                "diagnosis_minutes",
                "repair_minutes",
                "testing_minutes",
                "source_return_transfer_id",
            ),
            "requests": (
                "request_reference",
                "official_number",
                "part_name",
                "status",
                "created_at",
                "ordered_at",
                "delivered_at",
                "elapsed_days",
                "remaining_lines",
                "remaining",
                "request_kind",
            ),
        }[kind]
        result.update({k: row[k] for k in fields})
        if kind == "usage":
            result.update(
                cycle_hours=hours(row["issued_at"], row["returned_at"])
                if is_returned(row)
                else None,
                issue_hours=overlap(row, self.f, self.now),
            )
        return result

    def build(self, section, *, exporting=False):
        if section == "machine" and len(self.f.machine_ids) != 1:
            raise HTTPException(422, detail={"code": "reports_machine_required"})
        if section == "compare" and len(self.machines) != len(self.f.machine_ids):
            raise HTTPException(422, detail={"code": "reports_machine_scope_mismatch"})
        if section in MODULES:
            ensure_permission(self.user, MODULES[section])
        kinds = (
            [section]
            if section in MODULES
            else [k for k, permitted in self.allowed.items() if permitted]
        )
        all_metrics = {
            kind: period_metrics(kind, self.load(kind), self.f, self.now) for kind in kinds
        }
        metrics = all_metrics.get(section, [])
        current = [
            metric("total_machines", len(self.machines), current=True, drill="total_machines")
        ]
        current.extend(
            metric(
                status,
                sum(m["status"] == status for m in self.machines),
                current=True,
                drill=status,
            )
            for status in ("READY", "ISSUED", "REPAIR")
        )
        if self.allowed["repairs"]:
            current.append(
                next(
                    m
                    for m in period_metrics("repairs", self.load("repairs"), self.f, self.now)
                    if m["key"] == "current_repairs"
                )
            )
        if self.allowed["requests"]:
            current.append(
                next(
                    m
                    for m in period_metrics("requests", self.load("requests"), self.f, self.now)
                    if m["key"] == "pending_requests"
                )
            )
        categories = {}
        for machine in self.machines:
            key = machine["category_id"]
            item = categories.setdefault(
                key,
                {
                    "id": key,
                    "name_bg": machine["name_bg"],
                    "name_en": machine["name_en"],
                    "name_ru": machine["name_ru"],
                    "total": 0,
                    "statuses": Counter(),
                },
            )
            item["total"] += 1
            item["statuses"][machine["status"]] += 1
        machine_stats = []
        grouped = {kind: defaultdict(list) for kind in kinds}
        for kind in kinds:
            for row in self.load(kind):
                grouped[kind][row["machine_id"]].append(row)
        for machine in self.machines:
            machine_stats.append(
                {
                    "machine": machine,
                    "metrics": {
                        kind: period_metrics(kind, grouped[kind][machine["id"]], self.f, self.now)
                        for kind in kinds
                    },
                }
            )
        for item in machine_stats:
            category = categories[item["machine"]["category_id"]]
            totals = category.setdefault("metrics", Counter())
            for category_metrics in item["metrics"].values():
                for m in category_metrics:
                    if m["key"] in {"issues", "completed_cycles", "opened", "closed", "created"}:
                        totals[m["key"]] += m["value"] or 0
        ranking_kind = (
            "repairs"
            if section in {"overview", "repairs"}
            else "usage"
            if section == "usage"
            else "requests"
        )
        ranking_key = {"repairs": "opened", "usage": "issues", "requests": "created"}[ranking_kind]

        def rank_value(item):
            return next(
                (
                    m["value"] or 0
                    for m in item["metrics"].get(ranking_kind, [])
                    if m["key"] == ranking_key
                ),
                0,
            )

        rankings = sorted(
            machine_stats, key=lambda item: (-rank_value(item), item["machine"]["id"])
        )[:10]
        parts, articles = [], []
        if section in {"machine", "repairs"} and self.allowed["repairs"]:
            part_rows = bounded(
                self.db,
                select(
                    RepairPart.id,
                    RepairPart.repair_id,
                    RepairPart.part_number,
                    RepairPart.description,
                    RepairPart.quantity,
                    RepairPart.unit,
                    RepairPart.created_at,
                )
                .join(Repair, Repair.id == RepairPart.repair_id)
                .where(
                    Repair.id.in_(self.queries["repairs"].with_only_columns(Repair.id)),
                    RepairPart.created_at >= self.f.start,
                    RepairPart.created_at < self.f.end,
                    RepairPart.created_at <= self.now,
                )
                .order_by(RepairPart.created_at.desc(), RepairPart.id.desc()),
                1000,
            )
            parts = part_rows if exporting else part_rows[:100]
        if section == "requests":
            counts = {}
            for r in self.load("requests"):
                if not self.f.includes(r["created_at"]) or r["status"] == "CANCELLED":
                    continue
                for line in r["lines"]:
                    identifier = line.catalog_part_id or line.linked_catalog_part_id
                    # Unbound free text is never merged with another article by guessing its identity.
                    key = (
                        ("catalog", identifier, line.unit)
                        if identifier
                        else ("line", line.id, line.unit)
                    )
                    item = counts.setdefault(
                        key,
                        {
                            "catalog_part_id": identifier,
                            "line_id": line.id,
                            "description": line.description,
                            "part_number": line.part_number,
                            "unit": line.unit,
                            "requests": set(),
                            "quantity": Decimal(0),
                            "request_id": r["id"],
                        },
                    )
                    item["requests"].add(r["id"])
                    item["quantity"] += quantity(line)
            articles = [
                {**v, "requests": len(v["requests"]), "quantity": str(v["quantity"])}
                for v in counts.values()
            ]
            articles.sort(key=lambda a: (-a["requests"], a["line_id"]))
        if section == "overview":
            metrics = [
                m
                for kind in kinds
                for m in all_metrics[kind]
                if m["key"]
                in {
                    "issues",
                    "completed_cycles",
                    "opened",
                    "closed",
                    "created",
                    "submitted",
                    "delivered",
                }
            ]
        kind = section if section in MODULES else next(iter(kinds), "machines")
        name = {
            "usage": "issues",
            "repairs": "opened",
            "requests": "created",
            "machines": "total_machines",
        }[kind]
        return {
            "section": section,
            "filter_machines": [
                {"id": m["id"], "inventory_number": m["inventory_number"], "name": m["name"]}
                for m in self.machines
                if m["id"] in self.f.machine_ids
            ],
            "filters": self.f.public(),
            "previous_filters": self.f.previous().public(),
            "generated_at": self.now.isoformat() + "Z",
            "capabilities": self.allowed,
            "current": current,
            "metrics": metrics,
            "categories": list(categories.values()),
            "trends": self.trends(kinds),
            "rankings": rankings,
            "ranking_kind": ranking_kind,
            "ranking_key": ranking_key,
            "attention": self.attention() if exporting else self.attention()[:50],
            "attention_total": len(self.attention()),
            "machines": machine_stats if section in {"compare", "machine"} else [],
            "parts": parts,
            "parts_total": len(part_rows)
            if section in {"machine", "repairs"} and self.allowed["repairs"]
            else 0,
            "articles": articles if exporting else articles[:20],
            "articles_total": len(articles),
            "records": self.details(kind, name),
            "delayed": self.details("requests", "delayed") if section == "requests" else None,
            "thresholds": {
                "window_days": ATTENTION_WINDOW_DAYS,
                "repair_count": ATTENTION_REPAIRS,
                "open_days": ATTENTION_OPEN_DAYS,
                "delivery_days": DELAYED_ORDER_DAYS,
            },
        }
