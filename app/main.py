from __future__ import annotations

import os
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .csv_parser import parse_rsrefer_csv
from .ical import build_icalendar
from .models import Registration, merge_registrations
from .storage import CalendarStore
from .syllabus import SyllabusClient, SyllabusError

app = FastAPI(title="risyu2ical-renew", version="0.1.0")
DATA_DIR = Path(os.getenv("RISYU2ICAL_DATA_DIR", "data"))
PUBLIC_PATH = "/" + os.getenv("PUBLIC_PATH", "/tool/risyu2ical").strip("/")
store = CalendarStore(os.getenv("RISYU2ICAL_DB", str(DATA_DIR / "calendars.sqlite3")))
syllabus_client = SyllabusClient(
    enabled=os.getenv("SYLLABUS_ENABLED", "0").lower() in {"1", "true", "yes"},
    timeout=float(os.getenv("SYLLABUS_TIMEOUT", "5")),
    cache_ttl=float(os.getenv("SYLLABUS_CACHE_TTL", "86400")),
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="{PUBLIC_PATH}/static/style.css"><title>履修 iCalendar</title></head>
<body><main>
<h1>履修 iCalendar</h1>
<p>CampusSquareの「履修登録操作／履修登録状況照会」で各講義を「テキスト出力」してください。<br>
そこでダウンロードできる "RSReferCsv" をアップロードすることで、講義をカレンダーアプリに登録できます。</p>
<p>RSReferCsvを複数選択すると一度にカレンダーが作成されるので便利です</p>
<form action="{PUBLIC_PATH}/generate" method="post" enctype="multipart/form-data">
  <label for="file">RSReferCsv</label>
  <input id="file" type="file" name="files" accept=".csv" multiple required>
  <button type="submit">カレンダーを作成</button>
</form>
<h2>カレンダーアプリへの追加</h2>
<p><strong>Google Calendar:</strong> 設定の「カレンダーを追加」から「URLで追加」を選び、作成後のURLを貼り付けます。</p>
<p><strong>Appleカレンダー:</strong> 「ファイル」→「新規照会カレンダー」でURLを登録します。</p>
<p><strong>Outlook:</strong> 「予定表を追加」→「Webから購読」でURLを登録します。</p>
</main></body>
"""


def _result_page(calendar_name: str, url: str, course_count: int) -> str:
    safe_name, safe_url = escape(calendar_name), escape(url)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="{PUBLIC_PATH}/static/style.css"><title>作成しました</title></head>
<body><main><h1>作成しました</h1>
<p>{safe_name}（{course_count}科目）のカレンダーを作成しました。</p>
<p><a class="url" href="{safe_url}">https://yhop.net{safe_url}</a></p>
<h2>カレンダーアプリへの追加</h2>
<p><strong>Google Calendar:</strong> 設定の「カレンダーを追加」から「URLで追加」でURLを登録します。</p>
<p><strong>Appleカレンダー:</strong> 「ファイル」→「新規照会カレンダー」でURLを登録します。</p>
<p><strong>Outlook:</strong> 「予定表を追加」→「Webから購読」でURLを登録します。</p>
<p><a href="{PUBLIC_PATH}/">別のカレンダーを作成</a></p>
</main></body></html>"""


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="{PUBLIC_PATH}/static/style.css"><title>作成できません</title></head>
<body><main><h1>作成できません</h1><p class="error">{escape(message)}</p><p><a href="{PUBLIC_PATH}/">入力画面へ戻る</a></p></main></body></html>""",
        status_code=502,
    )


@app.post("/upload")
@app.post("/generate")
async def generate(
    files: list[UploadFile] = File(...),
) -> HTMLResponse:
    if not files or len(files) > 8:
        raise HTTPException(status_code=400, detail="CSVは1〜8ファイルまで指定してください")
    registrations: list[Registration] = []
    try:
        for file in files:
            payload = await file.read()
            if len(payload) > 10 * 1024 * 1024:
                raise ValueError(f"{file.filename or 'CSV'}: ファイルが大きすぎます")
            registrations.append(parse_rsrefer_csv(payload))
        registration = merge_registrations(registrations)
    except ValueError as exc:
        return _error_page(str(exc))
    terms = sorted({meeting.term for course in registration.courses for meeting in course.meetings})
    term_label = "・".join(f"第{term}" for term in terms) + "ターム"
    calendar_name = f"{registration.year}年度 履修カレンダー（{term_label}）"
    if syllabus_client.enabled:
        for course in registration.courses:
            try:
                info = syllabus_client.lookup(course.code, registration.year)
            except SyllabusError as exc:
                return _error_page(f"{course.code}のシラバスを取得できませんでした: {exc}")
            if info is None or not info.classroom:
                return _error_page(f"{course.code}の教室情報を取得できませんでした")
            course.name, course.teacher, course.classroom = info.subject, info.teacher, info.classroom
    ical = build_icalendar(calendar_name, registration.courses)
    token = store.save(calendar_name, ical)
    return HTMLResponse(_result_page(
        calendar_name,
        f"{PUBLIC_PATH}/calendar/{token}.ics",
        len(registration.courses),
    ))


def _calendar_response(token: str) -> Response:
    item = store.get(token)
    if item is None:
        raise HTTPException(status_code=404, detail="カレンダーが見つかりません")
    name, ical = item
    headers = {"Content-Disposition": f'attachment; filename="{token}.ics"'}
    return Response(content=ical, media_type="text/calendar; charset=utf-8", headers=headers)


@app.get("/calendar/{token}.ics")
def calendar(token: str) -> Response:
    return _calendar_response(token)


@app.get("/download/{token}.ics")
def download(token: str) -> Response:
    return _calendar_response(token)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
