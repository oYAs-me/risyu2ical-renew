from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .calendar_data import DEFAULT_CALENDAR
from .grouping import group_consecutive_periods
from .models import CalendarYear, Course


_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _uid(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:24]
    return f"{digest}@risyu2ical"


def build_icalendar(
    name: str,
    courses: list[Course],
    *,
    calendar: CalendarYear = DEFAULT_CALENDAR,
) -> bytes:
    tz = ZoneInfo(calendar.timezone)
    cal = Calendar()
    cal.add("PRODID", "-//risyu2ical-renew//Saitama University//JA")
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add("METHOD", "PUBLISH")
    cal.add("X-WR-CALNAME", name)
    cal.add("X-WR-TIMEZONE", calendar.timezone)

    schedules = {schedule.number: schedule for schedule in calendar.terms}
    for course in courses:
        by_term_day: dict[tuple[int, int], list[int]] = {}
        for meeting in course.meetings:
            by_term_day.setdefault((meeting.term, meeting.weekday), []).append(meeting.period)
        for (term, weekday), periods in sorted(by_term_day.items()):
            schedule = schedules.get(term)
            if schedule is None or weekday not in schedule.starts:
                continue
            for first_period, last_period in group_consecutive_periods(periods):
                start_date = schedule.starts[weekday]
                start_time = calendar.timetable.get(first_period)
                end_time = calendar.timetable.get(last_period)
                if start_time is None or end_time is None:
                    continue
                start = datetime.combine(start_date, start_time, tzinfo=tz)
                end = datetime.combine(
                    start_date,
                    end_time,
                    tzinfo=tz,
                ) + timedelta(minutes=calendar.period_minutes)
                event = Event()
                event.add("UID", _uid(calendar.year, course.code, term, weekday, first_period, last_period))
                event.add("DTSTAMP", datetime.now(tz))
                event.add("DTSTART", start)
                event.add("DTEND", end)
                event.add("SUMMARY", course.name or course.code)
                description = " / ".join(
                    value for value in (course.code, f"担当教員: {course.teacher}" if course.teacher else "") if value
                )
                if description:
                    event.add("DESCRIPTION", description)
                if course.classroom:
                    event.add("LOCATION", course.classroom)
                event.add(
                    "RRULE",
                    {"FREQ": "WEEKLY", "BYDAY": _BYDAY[weekday], "COUNT": 8},
                )
                exdates = [
                    datetime.combine(day, start_time, tzinfo=tz)
                    for day in schedule.exdates.get(weekday, ())
                ]
                if exdates:
                    event.add("EXDATE", exdates)
                cal.add_component(event)
    return cal.to_ical()
