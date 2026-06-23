"""GrindVacPro — Callback query handlers for Telegram bot."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select, update

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink

from .keyboards import (
    ACCEPT_REASONS,
    DECLINE_REASONS,
    build_card_kb,
    build_confirm_kb,
    build_reason_kb,
)
from .messages import format_card, format_confirm, format_thanks

logger = logging.getLogger("telegram_bot.callbacks")

router = Router()

# ── Helpers ───────────────────────────────────────────────────────

async def _get_link_and_vacancy(session, vacancy_id: int):
    """Return (VacancyLink, Vacancy | None) or None if link missing."""
    result = await session.execute(
        select(VacancyLink).where(VacancyLink.vacancy_id == vacancy_id)
    )
    link = result.scalar_one_or_none()
    if link is None:
        return None, None
    result = await session.execute(select(Vacancy).where(Vacancy.id == vacancy_id))
    vacancy = result.scalar_one_or_none()
    return link, vacancy


# ── Handlers ─────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data.startswith("vac:"))
async def on_vacancy_callback(callback: CallbackQuery) -> None:
    """Stateless router for all vacancy-related callbacks."""
    if callback.from_user.id != settings.telegram_user_id:
        logger.warning(
            "Ignoring callback from user %d (expected %d)",
            callback.from_user.id,
            settings.telegram_user_id,
        )
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split(":")
    # Expected formats:
    #   vac:ID:show
    #   vac:ID:a    → show confirm accept
    #   vac:ID:r    → show confirm reject
    #   vac:ID:pa   → proceed accept (save status)
    #   vac:ID:pr   → proceed reject (save status)
    #   vac:ID:ra:IDX  → reason accept
    #   vac:ID:rr:IDX  → reason decline
    #   vac:ID:rd:IDX  → reason decline

    if len(parts) < 3:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    try:
        vacancy_id = int(parts[1])
    except ValueError:
        await callback.answer("Некорректный ID вакансии", show_alert=True)
        return

    action = parts[2]
    idx = int(parts[3]) if len(parts) > 3 else None

    maker = get_session_maker()
    async with maker() as session:
        link, vacancy = await _get_link_and_vacancy(session, vacancy_id)
        if link is None or vacancy is None:
            await callback.answer("Вакансия не найдена", show_alert=True)
            return

        # ── Show card ──────────────────────────────────────────────
        if action == "show":
            text = format_card(
                title=vacancy.title,
                company=vacancy.company_name,
                url=link.url,
                score=vacancy.ai_score or 0,
                pros=(vacancy.ai_analysis or {}).get("pros", []),
                cons=(vacancy.ai_analysis or {}).get("cons", []),
                cover_letter=(vacancy.ai_analysis or {}).get("cover_letter", ""),
            )
            await callback.message.edit_text(
                text,
                reply_markup=build_card_kb(vacancy_id).as_markup(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await callback.answer()
            return

        # ── Confirm screen (transition) ───────────────────────────
        if action in ("a", "r"):
            text = format_confirm(action)
            await callback.message.edit_text(
                text,
                reply_markup=build_confirm_kb(vacancy_id, action).as_markup(),
                parse_mode="HTML",
            )
            await callback.answer()
            return

        # ── Proceed (save status, show reasons) ───────────────────
        if action in ("pa", "pr"):
            # Save status immediately, then show reasons
            new_status = "accepted" if action == "pa" else "declined"
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.id == link.id)
                .values(status=new_status)
            )
            await session.commit()

            text = "Выберите причину:"
            kind = "a" if action == "pa" else "r"
            await callback.message.edit_text(
                text,
                reply_markup=build_reason_kb(vacancy_id, kind).as_markup(),
            )
            await callback.answer()
            return

        # ── Reason selection → save notes ─────────────────────────
        if action in ("ra", "rd"):
            if idx is None:
                await callback.answer("Выберите причину", show_alert=True)
                return
            reasons = ACCEPT_REASONS if action == "ra" else DECLINE_REASONS
            if idx >= len(reasons):
                await callback.answer("Некорректный индекс", show_alert=True)
                return
            reason = reasons[idx]

            await session.execute(
                update(Vacancy)
                .where(Vacancy.id == vacancy_id)
                .values(notes=reason)
            )
            await session.commit()

            text = format_thanks(reason)
            await callback.message.edit_text(
                text,
                reply_markup=build_card_kb(vacancy_id).as_markup(),
                parse_mode="HTML",
            )
            await callback.answer("Сохранено")
            return

        await callback.answer("Неизвестное действие", show_alert=True)
