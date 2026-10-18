from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query

SOFIA = ZoneInfo("Europe/Sofia")
Section = Literal["overview", "usage", "repairs", "requests", "compare", "machine"]
MAX_SOURCE_ROWS = 100_000
MAX_EXPORT_ROWS = 5_000
ATTENTION_WINDOW_DAYS = 90
ATTENTION_REPAIRS = 3
ATTENTION_OPEN_DAYS = 7
ATTENTION_GROWTH_MIN = 3
ATTENTION_GROWTH_FACTOR = 2
DELAYED_ORDER_DAYS = 14


@dataclass(frozen=True)
class ReportFilters:
    date_from: date
    date_to: date
    category_id: int | None = None
    uncategorized: bool = False
    machine_ids: tuple[int, ...] = ()
    q: str = ""

    @property
    def start(self):
        return (
            datetime.combine(self.date_from, time.min, SOFIA).astimezone(UTC).replace(tzinfo=None)
        )

    @property
    def end(self):
        return (
            datetime.combine(self.date_to + timedelta(days=1), time.min, SOFIA)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def previous(self):
        days = (self.date_to - self.date_from).days + 1
        return replace(
            self,
            date_from=self.date_from - timedelta(days=days),
            date_to=self.date_from - timedelta(days=1),
        )

    def includes(self, value):
        return value is not None and self.start <= naive(value) < self.end

    def public(self):
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "category_id": self.category_id,
            "uncategorized": self.uncategorized,
            "machine_ids": list(self.machine_ids),
            "q": self.q,
            "timezone": "Europe/Sofia",
            "start_utc": self.start.isoformat() + "Z",
            "end_utc_exclusive": self.end.isoformat() + "Z",
        }


def naive(value):
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def report_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = Query(None, ge=1),
    uncategorized: bool = False,
    machine_id: int | None = Query(None, ge=1),
    machine_ids: str = Query("", max_length=60),
    q: str = Query("", max_length=160),
):
    today = datetime.now(SOFIA).date()
    last = date_to or today
    first = date_from or last - timedelta(days=29)
    if first > last or (last - first).days > 1095 or first.year < 1970 or last.year > 2100:
        raise HTTPException(422, detail={"code": "reports_invalid_period"})
    try:
        ids = tuple(dict.fromkeys(int(value) for value in machine_ids.split(",") if value))
    except ValueError:
        raise HTTPException(422, detail={"code": "reports_invalid_machines"}) from None
    if machine_id:
        ids = (machine_id,)
    if len(ids) > 4 or any(value < 1 for value in ids) or (category_id and uncategorized):
        raise HTTPException(422, detail={"code": "reports_invalid_machines"})
    return ReportFilters(first, last, category_id, uncategorized, ids, q.strip())
