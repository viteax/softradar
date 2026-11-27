"""Ежедневный отчет менеджеру на почту (брифинг: основной канал – почта, формат – Excel)."""

import asyncio
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

from .config import Settings


def _send(s: Settings, subject: str, body: str, data: bytes, filename: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_from or s.smtp_user, s.report_to
    msg.set_content(body)
    msg.add_attachment(
        data,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
    ctx = ssl.create_default_context()
    if s.smtp_port == 465:
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30) as smtp:
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)


def summary(rows: list[dict]) -> str:
    fit = [r for r in rows if r.get("verdict") == "fit"]
    partial = [r for r in rows if r.get("verdict") == "partial"]
    lines = [
        f"СофтРадар, отчет на {datetime.now():%d.%m.%Y %H:%M}",
        f"Подходят (КП готово): {len(fit)}, нужна проверка: {len(partial)}.",
        "",
        "Топ к подаче:",
    ]
    for r in sorted(fit, key=lambda r: -(r.get("score") or 0))[:10]:
        d = r["data"]
        lines.append(
            f"• {d['title'][:90]} – до {(d.get('deadline') or '')[:16].replace('T', ' ')} – {d['url']}"
        )
    lines += ["", "Полный отчет с условиями, позициями и рисками – во вложении (Excel)."]
    return "\n".join(lines)


async def send_report(s: Settings, rows: list[dict], data: bytes) -> None:
    name = f"softradar_{datetime.now():%Y-%m-%d}.xlsx"
    await asyncio.to_thread(
        _send, s, f"СофтРадар: закупки ПО на {datetime.now():%d.%m.%Y}", summary(rows), data, name
    )
