from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import BinaryIO, Iterable, TextIO

from .models import Course, Meeting, Registration

_YEAR_TERM = re.compile(r"(?P<year>\d{4})年度\s*[・･]\s*第(?P<term>\d+)")
_PERIOD = re.compile(r"^\s*(\d+)\s*限")
_WEEKDAYS = ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日")
_EMPTY = {"", "未登録", "-", "－", "—"}


def _reader(source: str | Path | bytes | BinaryIO | TextIO) -> Iterable[list[str]]:
    if isinstance(source, (str, Path)):
        stream = open(source, "r", encoding="cp932", newline="")
        close = True
    elif isinstance(source, bytes):
        stream = io.TextIOWrapper(io.BytesIO(source), encoding="cp932", newline="")
        close = True
    elif isinstance(source, io.TextIOBase):
        stream = source
        close = False
    else:
        stream = io.TextIOWrapper(source, encoding="cp932", newline="")
        close = True
    try:
        yield from csv.reader(stream)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"RSReferCsvを読み込めません: {exc}") from exc
    finally:
        if close:
            stream.close()


def _clean(value: str) -> str:
    return value.replace("\ufeff", "").replace("\u3000", " ").strip()


def _course_code(value: str) -> str:
    value = _clean(value)
    return "" if value in _EMPTY else value


def parse_rsrefer_csv(source: str | Path | bytes | BinaryIO | TextIO) -> Registration:
    """Parse a CampusSquare RSReferCsv export without using unsafe evaluation.

    The export contains five rows per period.  The first row has course codes;
    subsequent rows contain display details.  The parser deliberately locates
    the weekday header instead of relying on fixed file offsets.
    """
    rows = list(_reader(source))
    if not rows:
        raise ValueError("RSReferCsvが空です")

    name = ""
    year = term = None
    for row in rows[:12]:
        for index, value in enumerate(row[:-1]):
            label = _clean(value).strip("[]")
            candidate = _clean(row[index + 1])
            if label == "氏名" and not name:
                name = candidate
            if label in {"年度・学期", "年度･学期"}:
                match = _YEAR_TERM.search(candidate)
                if match:
                    year, term = int(match["year"]), int(match["term"])
    if year is None or term is None:
        raise ValueError("年度・学期を特定できません")

    header_index = next(
        (
            i
            for i, row in enumerate(rows)
            if sum(_clean(value) in _WEEKDAYS for value in row) >= 3
        ),
        None,
    )
    if header_index is None:
        raise ValueError("曜日・時限表のヘッダーが見つかりません")
    header = [_clean(value) for value in rows[header_index]]
    weekday_columns = {
        index: _WEEKDAYS.index(value)
        for index, value in enumerate(header)
        if value in _WEEKDAYS
    }
    if not weekday_columns:
        raise ValueError("曜日列が見つかりません")

    meetings: dict[str, list[Meeting]] = defaultdict(list)
    names: dict[str, str] = {}
    for index in range(header_index + 1, len(rows)):
        match = _PERIOD.match(_clean(rows[index][0]) if rows[index] else "")
        if not match:
            continue
        period = int(match.group(1))
        detail_rows = rows[index + 1 : index + 5]
        for column, weekday in weekday_columns.items():
            code = _course_code(rows[index][column] if column < len(rows[index]) else "")
            if not code:
                continue
            meetings[code].append(Meeting(term=term, weekday=weekday, period=period))
            for detail in detail_rows:
                if column < len(detail):
                    candidate = _clean(detail[column])
                    if candidate and candidate not in _EMPTY:
                        names.setdefault(code, candidate)
                        break

    # The optional "集中講義など" table has useful names and teachers but no
    # weekly meetings.  Importing it keeps the normalized model complete while
    # leaving calendar generation to the regular timetable.
    extra_header = next(
        (
            i
            for i, row in enumerate(rows)
            if any("授業コード" in _clean(value) for value in row)
        ),
        None,
    )
    extras: dict[str, tuple[str, str, str]] = {}
    if extra_header is not None:
        columns = {_clean(value): i for i, value in enumerate(rows[extra_header])}
        code_i = next((i for label, i in columns.items() if "授業コード" in label), None)
        subject_i = next((i for label, i in columns.items() if label == "科目"), None)
        teacher_i = next((i for label, i in columns.items() if "担当教員" in label), None)
        mode_i = next((i for label, i in columns.items() if "授業形態" in label), None)
        if code_i is not None:
            for row in rows[extra_header + 1 :]:
                code = _course_code(row[code_i] if code_i < len(row) else "")
                if code:
                    extras[code] = (
                        _clean(row[subject_i]) if subject_i is not None and subject_i < len(row) else "",
                        _clean(row[teacher_i]) if teacher_i is not None and teacher_i < len(row) else "",
                        _clean(row[mode_i]) if mode_i is not None and mode_i < len(row) else "",
                    )

    codes = set(meetings) | set(extras)
    courses = []
    for code in sorted(codes):
        subject, teacher, classroom = extras.get(code, ("", "", ""))
        courses.append(
            Course(
                code=code,
                name=subject or names.get(code, ""),
                teacher=teacher,
                classroom=classroom,
                meetings=sorted(set(meetings.get(code, [])), key=lambda x: (x.term, x.weekday, x.period)),
            )
        )
    return Registration(name=name, year=year, semester=term, courses=courses)
