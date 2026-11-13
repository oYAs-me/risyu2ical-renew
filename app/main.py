from __future__ import annotations

import os
from html import escape
from pathlib import Path
from urllib.parse import quote

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
_raw_public_path = os.getenv("PUBLIC_PATH", "/tool/risyu2ical").strip("/")
PUBLIC_PATH = f"/{_raw_public_path}" if _raw_public_path else ""
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://yhop.net").rstrip("/")
SITE_NAME = "埼玉大学 履修 iCalendar"
DEFAULT_DESCRIPTION = (
    "埼玉大学 CampusSquare の履修登録データ（RSReferCsv）から、"
    "Google Calendar・Apple カレンダー・Outlook に登録できる iCalendar 購読用 URL を作成します。"
)
store = CalendarStore(os.getenv("RISYU2ICAL_DB", str(DATA_DIR / "calendars.sqlite3")))
syllabus_client = SyllabusClient(
    enabled=os.getenv("SYLLABUS_ENABLED", "0").lower() in {"1", "true", "yes"},
    timeout=float(os.getenv("SYLLABUS_TIMEOUT", "5")),
    cache_ttl=float(os.getenv("SYLLABUS_CACHE_TTL", "86400")),
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
if PUBLIC_PATH:
    app.mount(f"{PUBLIC_PATH}/static", StaticFiles(directory=Path(__file__).parent / "static"), name="public_static")


def _page_layout(
    title: str | None,
    body_html: str,
    *,
    description: str = DEFAULT_DESCRIPTION,
    noindex: bool = False,
) -> str:
    full_title = f"{title} - {SITE_NAME}" if title else SITE_NAME
    safe_title = escape(full_title)
    safe_site = escape(SITE_NAME)
    safe_desc = escape(description)
    og_url = escape(f"{PUBLIC_ORIGIN}{PUBLIC_PATH}/")
    og_image = escape(f"{PUBLIC_ORIGIN}{PUBLIC_PATH}/static/ogp.png")
    robots_tag = '\n  <meta name="robots" content="noindex">' if noindex else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#22467E">
  <meta name="description" content="{safe_desc}">{robots_tag}
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ja_JP">
  <meta property="og:site_name" content="{safe_site}">
  <meta property="og:title" content="{safe_title}">
  <meta property="og:description" content="{safe_desc}">
  <meta property="og:url" content="{og_url}">
  <meta property="og:image" content="{og_image}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{safe_title}">
  <meta name="twitter:description" content="{safe_desc}">
  <meta name="twitter:image" content="{og_image}">
  <link rel="stylesheet" href="{PUBLIC_PATH}/static/style.css">
  <title>{safe_title}</title>
</head>
<body>
  <header class="site-header">
    <div class="site-header__inner">
      <a class="site-header__brand" href="{PUBLIC_PATH}/">{safe_site}</a>
      <span class="site-header__meta">埼玉大学 CampusSquare RSReferCsv → iCalendar 変換</span>
    </div>
  </header>
  <div class="page-container">
    <main class="card">
{body_html}
    </main>
  </div>
  <footer class="site-footer">
    <p>埼玉大学の履修登録データ（RSReferCsv）からカレンダー購読用 URL（.ics）を生成します。</p>
  </footer>
  <script>
    (() => {{
      const isApple = /iPhone|iPad|iPod|Macintosh/i.test(navigator.userAgent);
      if (!isApple) return;
      for (const a of document.querySelectorAll("a[data-apple-href]")) {{
        a.setAttribute("href", a.getAttribute("data-apple-href"));
      }}
    }})();
  </script>
</body>
</html>"""


_EXTERNAL_ICON = (
    '<svg class="external-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">'
    '<path d="M6 3.5H3.5C2.95 3.5 2.5 3.95 2.5 4.5V12.5C2.5 13.05 2.95 13.5 3.5 13.5H11.5C12.05 13.5 12.5 13.05 12.5 12.5V10" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
    '<path d="M9.5 2.5H13.5V6.5M13.5 2.5L7.5 8.5" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)


def _calendar_guides_html(verb: str, calendar_url: str | None = None) -> str:
    if calendar_url:
        public_host = PUBLIC_ORIGIN.removeprefix("https://").removeprefix("http://")
        webcal_url = f"webcal://{public_host}{calendar_url}"
        google_href = escape(f"https://calendar.google.com/calendar/r?cid={quote(webcal_url, safe='')}")
        apple_href = escape(webcal_url)
        apple_extra = ""
        outlook_href = "https://outlook.live.com/calendar/0/addfromweb"
    else:
        google_href = "https://calendar.google.com/calendar/r/settings/addbyurl"
        apple_href = "https://www.icloud.com/calendar/"
        apple_extra = ' data-apple-href="calshow://"'
        outlook_href = "https://outlook.live.com/calendar/"

    return f"""<h2>カレンダーアプリへの追加</h2>
<dl class="guide-list">
  <div class="guide-item">
    <dt><a class="guide-app-link" href="{google_href}" target="_blank" rel="noopener noreferrer">Google Calendar{_EXTERNAL_ICON}</a></dt>
    <dd>設定の「カレンダーを追加」から「URLで追加」を選び、{escape(verb)}。</dd>
  </div>
  <div class="guide-item">
    <dt><a class="guide-app-link" href="{apple_href}"{apple_extra} target="_blank" rel="noopener noreferrer">Apple カレンダー{_EXTERNAL_ICON}</a></dt>
    <dd>「ファイル」→「新規照会カレンダー」でURLを登録します。</dd>
  </div>
  <div class="guide-item">
    <dt><a class="guide-app-link" href="{outlook_href}" target="_blank" rel="noopener noreferrer">Outlook{_EXTERNAL_ICON}</a></dt>
    <dd>「予定表を追加」→「Webから購読」でURLを登録します。</dd>
  </div>
</dl>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    body = f"""<h1>埼玉大学 履修 iCalendar の作成</h1>
<p class="lead">埼玉大学 CampusSquare の「履修登録操作／履修登録状況照会」で各講義を「テキスト出力」してください。<br>
ダウンロードした <strong>RSReferCsv</strong> をアップロードすると、講義スケジュールをカレンダーアプリに登録できる URL を作成します。</p>
<ol class="steps-list">
  <li>埼玉大学 CampusSquare から各ターム・各講義の <code>RSReferCsv</code> をダウンロードします。</li>
  <li>下のフォームから CSV ファイルを選択します（複数ファイルを一度に選択できます）。</li>
  <li>「カレンダーを作成」を押すと、購読用の iCalendar URL が発行されます。</li>
  <li>下のリンクから Google Calendar・Apple カレンダー・Outlook へすぐに登録できます。</li>
</ol>
<form class="form-section" action="{PUBLIC_PATH}/generate" method="post" enctype="multipart/form-data">
  <label class="field-label" for="file">
    <span>RSReferCsv ファイル</span>
    <span class="requirement-badge">必須</span>
  </label>
  <p id="file-help" class="support-text">複数選択すると一度にカレンダーが作成されます（最大8ファイル、各10MBまで）。</p>
  <div class="file-input-wrap">
    <input id="file" type="file" name="files" accept=".csv" multiple required aria-describedby="file-help">
  </div>
  <ul id="file-list" class="file-list" aria-live="polite"></ul>
  <div class="button-group">
    <button class="btn btn--primary btn--full" type="submit">カレンダーを作成</button>
  </div>
</form>
{_calendar_guides_html("作成後のURLを貼り付けます")}
<script>
(() => {{
  const input = document.getElementById("file");
  const list = document.getElementById("file-list");
  if (!input || !list) return;
  input.addEventListener("change", () => {{
    list.textContent = "";
    for (const file of input.files || []) {{
      const li = document.createElement("li");
      li.textContent = file.name;
      list.appendChild(li);
    }}
  }});
}})();
</script>"""
    return _page_layout(None, body)


def _result_page(calendar_name: str, url: str, course_count: int) -> str:
    safe_name, safe_url = escape(calendar_name), escape(url)
    full_url = f"{escape(PUBLIC_ORIGIN)}{safe_url}"
    body = f"""<div class="banner banner--success" role="status">
  <svg class="banner__icon" width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
    <path d="M7.5 12.5L10.5 15.5L16.5 9.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <div>
    <h1 class="banner__title">カレンダーを作成しました</h1>
    <p class="banner__body">{safe_name}（{course_count}科目）のカレンダーを作成しました。</p>
  </div>
</div>
<div class="url-panel">
  <span class="url-panel__label">購読用カレンダー URL</span>
  <div class="url-panel__row">
    <a id="calendar-url" class="url" href="{safe_url}">{full_url}</a>
    <button id="copy-url-btn" class="btn btn--outline" type="button">URLをコピー</button>
  </div>
  <p id="copy-status" class="copy-status" aria-live="polite"></p>
</div>
{_calendar_guides_html("URLを登録します", url)}
<div class="button-group">
  <a class="btn btn--outline" href="{PUBLIC_PATH}/">別のカレンダーを作成</a>
</div>
<script>
(() => {{
  const btn = document.getElementById("copy-url-btn");
  const link = document.getElementById("calendar-url");
  const status = document.getElementById("copy-status");
  if (!btn || !link || !status) return;
  btn.addEventListener("click", async () => {{
    try {{
      await navigator.clipboard.writeText(link.textContent.trim());
      status.textContent = "URLをクリップボードにコピーしました。";
    }} catch {{
      status.textContent = "コピーに失敗しました。URLを手動で選択してコピーしてください。";
    }}
  }});
}})();
</script>"""
    return _page_layout("作成しました", body, noindex=True)


def _error_page(message: str) -> HTMLResponse:
    body = f"""<div class="banner banner--error" role="alert">
  <svg class="banner__icon" width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
    <path d="M12 7.5V13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    <circle cx="12" cy="16.5" r="1.25" fill="currentColor"/>
  </svg>
  <div>
    <h1 class="banner__title">カレンダーを作成できませんでした</h1>
    <p class="banner__body">{escape(message)}</p>
  </div>
</div>
<div class="button-group">
  <a class="btn btn--outline" href="{PUBLIC_PATH}/">入力画面へ戻る</a>
</div>"""
    return HTMLResponse(_page_layout("作成できません", body, noindex=True), status_code=502)


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
