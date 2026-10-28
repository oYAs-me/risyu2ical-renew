from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

from .models import CalendarYear, TermSchedule


def load_calendar(path: str | Path) -> CalendarYear:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    timetable = {
        int(period): time.fromisoformat(value)
        for period, value in payload["timetable"].items()
    }
    terms = tuple(
        TermSchedule(
            number=int(item["number"]),
            starts={int(day): date.fromisoformat(data["start"]) for day, data in item["weekdays"].items()},
            exdates={
                int(day): tuple(date.fromisoformat(value) for value in data.get("exdates", []))
                for day, data in item["weekdays"].items()
            },
            class_count=int(item.get("class_count")),
        )
        for item in payload["terms"]
    )
    return CalendarYear(
        year=int(payload["year"]),
        timezone=payload.get("timezone", "Asia/Tokyo"),
        timetable=timetable,
        period_minutes=int(payload.get("period_minutes", 90)),
        terms=terms,
    )


DEFAULT_CALENDAR = load_calendar(Path(__file__).parent / "data" / "calendar_2026.json")
