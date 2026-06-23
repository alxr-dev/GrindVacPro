"""GrindVacPro — Message formatting for Telegram bot."""

from __future__ import annotations

import html


def format_card(title: str, company: str, url: str, score: int,
                pros: list[str], cons: list[str], cover_letter: str) -> str:
    """Build HTML vacancy card message."""
    safe_title = html.escape(title)
    safe_company = html.escape(company)
    safe_cover = html.escape(cover_letter)

    parts = [
        f"<b>🎯 Score: {score}/100</b>",
        "",
        f"🏢 <b>{safe_company}</b>",
        f"💼 <a href='{url}'>{safe_title}</a>",
        "",
    ]
    if pros:
        parts.append("<b>✅ Плюсы:</b>")
        for p in pros:
            parts.append(f"• {html.escape(p)}")
        parts.append("")
    if cons:
        parts.append("<b>❌ Минусы:</b>")
        for c in cons:
            parts.append(f"• {html.escape(c)}")
        parts.append("")
    parts.append("<b>📝 Сопроводительное письмо:</b>")
    parts.append(f"<code>{safe_cover}</code>")
    return "\n".join(parts)


def format_confirm(action: str) -> str:
    """Confirm message for accept ('a') or reject ('r')."""
    verb = "отклик" if action == "a" else "отказ"
    return f"Подтвердить <b>{verb}</b>?"


def format_thanks(reason: str) -> str:
    return f"Сохранено: <b>{html.escape(reason)}</b>"
