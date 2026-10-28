from __future__ import annotations

import threading
import time as clock
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


class SyllabusError(RuntimeError):
    """Base class for syllabus lookup failures."""


class SyllabusNotFound(SyllabusError):
    pass


class SyllabusUnavailable(SyllabusError):
    pass


@dataclass(frozen=True)
class SyllabusInfo:
    subject: str
    teacher: str
    classroom: str


def genre_for_course(course_code: str, year: int = 2026) -> str:
    """Return the CampusSquare syllabus genre for a year and course code.

    The 2024 and earlier endpoint used a more granular R/T routing scheme;
    2025 onward uses the consolidated mapping documented for the renewed site.
    """
    code = course_code.strip().upper()
    if not code:
        raise ValueError("授業コードが空です")
    if year <= 2024:
        if code.startswith(("NX", "XZ")):
            return "06"
        if code.startswith("T"):
            return "05" if len(code) > 2 and code[2] == "0" else f"052{code[2:3]}"
        if code.startswith("R"):
            if len(code) > 7:
                return f"052{code[-1]}"
            if code.startswith("RT") and len(code) > 2 and code[2].isdigit():
                return f"040{code[2]}" if int(code[2]) <= 5 else "04"
            if len(code) > 2 and code[2] == "9":
                return "0402"
            if len(code) > 2 and code[2].isdigit():
                return f"040{code[2]}"
    rules = (
        (lambda x: x.startswith(("NX", "XZ")), "06"),
        (lambda x: x.startswith("T"), "05"),
        (lambda x: x.startswith("R") and len(x) > 7, "05"),
        (lambda x: x.startswith("R"), "04"),
        (lambda x: x.startswith("A"), "03"),
        (lambda x: x.startswith(("Y", "P")), "02"),
        (lambda x: x.startswith("F"), "01"),
        (lambda x: x.startswith("G"), "27"),
        (lambda x: x.startswith("D"), "25"),
        (lambda x: x.startswith("MM"), "24"),
        (lambda x: x.startswith("BMD"), "19"),
        (lambda x: x.startswith("W"), "18"),
        (lambda x: x.startswith("B"), "17"),
    )
    for predicate, genre in rules:
        if predicate(code):
            return genre
    raise ValueError(f"シラバスのジャンルを特定できません: {course_code}")


class SyllabusClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout: float = 5.0,
        cache_ttl: float = 86400.0,
        base_url: str = "https://syllabus.risyu.saitama-u.ac.jp/syllabusHtml",
    ) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.base_url = base_url.rstrip("/")
        self._cache: dict[tuple[int, str], tuple[float, SyllabusInfo]] = {}
        self._lock = threading.Lock()

    def lookup(self, course_code: str, year: int) -> SyllabusInfo | None:
        if not self.enabled:
            return None
        key = (year, course_code.upper())
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > clock.monotonic():
                return cached[1]
        try:
            genre = genre_for_course(course_code, year)
        except ValueError as exc:
            raise SyllabusNotFound(str(exc)) from exc
        url = f"{self.base_url}/{year}/{genre}/{genre}_{course_code}_ja_JP.html"
        request = Request(url, headers={"User-Agent": "risyu2ical-renew/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise SyllabusNotFound(f"シラバスが見つかりません: {course_code}") from exc
            raise SyllabusUnavailable(f"シラバス取得に失敗しました ({exc.code})") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SyllabusUnavailable(f"シラバスへ接続できません: {exc}") from exc
        soup = BeautifulSoup(body, "html.parser")
        table = soup.select_one("#tabs-1 table")
        cells = [] if table is None else [
            cell.get_text(" ", strip=True).replace("\u3000", "")
            for cell in table.find_all("td")
        ]
        if len(cells) < 11:
            raise SyllabusNotFound(f"シラバスの形式を解釈できません: {course_code}")
        classroom = cells[10].split("／", 1)[0].strip()
        remote_flag = cells[12].strip().lower() if len(cells) > 12 else ""
        if not classroom:
            raise SyllabusNotFound(f"教室情報がシラバスにありません: {course_code}")
        if remote_flag in {"yes", "オンデマンド", "遠隔授業"}:
            classroom = "オンデマンド"
        info = SyllabusInfo(
            subject=cells[0].split("／", 1)[0].strip(),
            teacher=cells[9].split("／", 1)[0].strip(),
            classroom=classroom,
        )
        with self._lock:
            self._cache[key] = (clock.monotonic() + self.cache_ttl, info)
        return info
