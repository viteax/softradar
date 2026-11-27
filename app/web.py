"""Веб: дашборд менеджера, карточка закупки, КП (docx), отчет (xlsx), JSON API."""

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import settings
from .db import DB
from .filters import now_msk
from .kp import VERDICT, kp_docx, report_xlsx, rub
from .pipeline import Pipeline

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
db = DB(settings.data_dir / "softradar.db")
pipeline = Pipeline(settings, db)
env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape())


def _dt(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m %H:%M") if iso else "–"


def _left(iso: str | None) -> str:
    if not iso:
        return ""
    h = (datetime.fromisoformat(iso) - now_msk()).total_seconds() / 3600
    if h < 0:
        return "истек"
    return f"{h:.0f} ч" if h < 48 else f"{h / 24:.0f} дн"


env.filters.update(
    rub=rub,
    dt=_dt,
    left=_left,
    pct=lambda x: f"{x * 100:.0f}%" if isinstance(x, int | float) else "–",
    ts=lambda x: time.strftime("%d.%m %H:%M", time.localtime(x)) if x else "–",
    pretty=lambda x: json.dumps(x, ensure_ascii=False, indent=1),
    q=lambda x: quote(str(x), safe=""),
)
env.globals["VERDICT"] = VERDICT


def render(name: str, status: int = 200, **ctx) -> HTMLResponse:
    return HTMLResponse(env.get_template(name).render(**ctx), status)


def bucket(r: dict) -> str:
    if r.get("verdict") in ("fit", "partial", "reject"):
        return r["verdict"]
    return "queue" if r.get("filter_ok") else "filtered"


async def index(request: Request) -> HTMLResponse:
    rows = db.tenders()
    tab = request.query_params.get("tab") or ""
    groups: dict[str, list] = {"fit": [], "partial": [], "reject": [], "queue": [], "filtered": []}
    for r in rows:
        groups[bucket(r)].append(r)
    if tab not in groups:
        tab = next((k for k in ("fit", "partial", "queue", "reject", "filtered") if groups[k]), "fit")
    runs = db.q("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    analyzed = [r for r in rows if r.get("analyzed")]
    tokens = sum(r.get("tokens") or 0 for r in analyzed)
    return render(
        "index.html",
        groups=groups,
        tab=tab,
        rows=groups[tab],
        last_run=dict(runs[0]) | {"stats": json.loads(runs[0]["stats"] or "{}")} if runs else None,
        running=pipeline.running,
        progress=pipeline.progress,
        tokens=tokens,
        analyzed=len(analyzed),
        cost_per=(
            sum(
                settings.cost(
                    (r.get("kp") or {}).get("prompt_tokens") or 0,
                    (r.get("kp") or {}).get("completion_tokens") or 0,
                    r.get("tokens") or 0,
                )
                for r in analyzed
            )
            / len(analyzed)
            if analyzed
            else 0
        ),
        s=settings,
        llm=settings.llm_ready,
    )


async def tender(request: Request) -> HTMLResponse:
    r = db.tender(request.path_params["key"])
    if not r:
        return render("message.html", 404, text="Закупка не найдена")
    return render(
        "tender.html",
        r=r,
        d=r["data"],
        a=r.get("analysis") or {},
        kp=r.get("kp") or {},
        running=pipeline.running,
        s=settings,
        bucket=bucket(r),
    )


async def kp_file(request: Request) -> Response:
    r = db.tender(request.path_params["key"])
    if not r or not (r.get("kp") or {}).get("lines"):
        return PlainTextResponse("КП для этой закупки нет", 404)
    data = kp_docx(r["data"], r.get("analysis") or {}, r["kp"])
    name = f"КП_{r['data']['number'].replace('/', '-')}.docx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


async def report(request: Request) -> Response:
    rows = [r for r in db.tenders() if r.get("analyzed")]
    name = f"softradar_report_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
    return Response(
        report_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


async def send_report_now(request: Request) -> Response:
    try:
        ok = await pipeline.daily_report(force=True)
    except Exception as e:  # noqa: BLE001
        pipeline.say(f"отчет на почту не отправлен: {e}")
        ok = False
    if not ok and not settings.mail_ready:
        pipeline.say("почта не настроена: SMTP_HOST, SMTP_USER, SMTP_PASSWORD, REPORT_TO в .env")
    return RedirectResponse("/", status_code=303)


async def run_now(request: Request) -> Response:
    if not pipeline.running:
        asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.2)
    return RedirectResponse("/", 303)


async def reanalyze(request: Request) -> Response:
    key = request.path_params["key"]
    if not pipeline.running:

        async def job():
            async with pipeline.lock:
                await pipeline.analyze(key)

        asyncio.create_task(job())
        await asyncio.sleep(0.2)
    return RedirectResponse(f"/t/{quote(key, safe='')}", 303)


async def add_url(request: Request) -> Response:
    form = await request.form()
    url = str(form.get("url") or "")
    if pipeline.running:
        return render("message.html", text="Сейчас идет прогон – попробуйте через пару минут.")
    try:
        async with pipeline.lock:
            key = await pipeline.add_by_url(url)
        asyncio.create_task(_analyze_locked(key))
        await asyncio.sleep(0.2)
    except ValueError as e:
        return render("message.html", 400, text=str(e))
    return RedirectResponse(f"/t/{quote(key, safe='')}", 303)


async def _analyze_locked(key: str) -> None:
    async with pipeline.lock:
        await pipeline.analyze(key)


async def api_tenders(request: Request) -> JSONResponse:
    verdict = request.query_params.get("verdict")
    out = []
    for r in db.tenders():
        if verdict and r.get("verdict") != verdict:
            continue
        d = dict(r["data"])
        d.pop("page_text", None)
        out.append(
            {
                "key": r["key"],
                "score": r.get("score"),
                "verdict": r.get("verdict"),
                "filter_ok": bool(r.get("filter_ok")),
                "filter_reasons": r.get("filter_reasons"),
                "tender": d,
                "analysis": r.get("analysis"),
                "kp": r.get("kp"),
                "tokens": r.get("tokens"),
            }
        )
    return JSONResponse(out)


async def api_tender(request: Request) -> JSONResponse:
    r = db.tender(request.path_params["key"])
    return JSONResponse(r) if r else JSONResponse({"error": "not found"}, 404)


async def api_status(request: Request) -> JSONResponse:
    return JSONResponse(
        {"running": pipeline.running, "progress": pipeline.progress, "log": list(pipeline.log)[:40]}
    )


async def about(request: Request) -> HTMLResponse:
    return render("about.html", s=settings)


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(pipeline.loop()) if settings.autorun else None
    yield
    if task:
        task.cancel()
    await pipeline.http.aclose()


routes = [
    Route("/", index),
    Route("/about", about),
    Route("/t/{key:path}/kp.docx", kp_file),
    Route("/t/{key:path}/reanalyze", reanalyze, methods=["POST"]),
    Route("/t/{key:path}", tender),
    Route("/report.xlsx", report),
    Route("/report/send", send_report_now, methods=["POST"]),
    Route("/run", run_now, methods=["POST"]),
    Route("/add", add_url, methods=["POST"]),
    Route("/api/tenders", api_tenders),
    Route("/api/tenders/{key:path}", api_tender),
    Route("/api/status", api_status),
    Route("/healthz", healthz),
    Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
]
app = Starlette(routes=routes, lifespan=lifespan)
