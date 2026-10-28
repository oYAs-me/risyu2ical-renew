from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class Meeting:
    term: int
    weekday: int
    period: int


@dataclass
class Course:
    code: str
    name: str = ""
    teacher: str = ""
    classroom: str = ""
    meetings: list[Meeting] = field(default_factory=list)


@dataclass
class Registration:
    name: str
    year: int
    semester: int
    courses: list[Course]


def merge_registrations(registrations: list[Registration]) -> Registration:
    if not registrations:
        raise ValueError("RSReferCsvが指定されていません")
    years = {item.year for item in registrations}
    if len(years) != 1:
        raise ValueError("異なる年度のCSVは同時に指定できません")
    merged: dict[str, Course] = {}
    for registration in registrations:
        for course in registration.courses:
            target = merged.setdefault(course.code, Course(code=course.code))
            target.meetings = sorted(
                set(target.meetings) | set(course.meetings),
                key=lambda item: (item.term, item.weekday, item.period),
            )
            for field in ("name", "teacher", "classroom"):
                if not getattr(target, field) and getattr(course, field):
                    setattr(target, field, getattr(course, field))
    return Registration(
        name=next((item.name for item in registrations if item.name), ""),
        year=registrations[0].year,
        semester=registrations[0].semester,
        courses=sorted(merged.values(), key=lambda item: item.code),
    )


@dataclass(frozen=True)
class TermSchedule:
    number: int
    starts: dict[int, date]
    exdates: dict[int, tuple[date, ...]]
    class_count: int = 8


@dataclass(frozen=True)
class CalendarYear:
    year: int
    timezone: str
    timetable: dict[int, time]
    period_minutes: int
    terms: tuple[TermSchedule, ...]
