"""Маршруты и страницы."""

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

PAGE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>СофтРадар – закупки ПО и КП</title>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem">
<h1>СофтРадар – закупки ПО и КП</h1>
<p>Работает.</p>
</body>
</html>
"""


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(PAGE)


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


app = Starlette(routes=[Route("/", index), Route("/healthz", healthz)])
