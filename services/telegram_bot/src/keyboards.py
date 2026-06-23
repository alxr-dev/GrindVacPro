"""GrindVacPro — Inline keyboards for Telegram bot."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

ACCEPT_REASONS = [
    "Совпадение по стеку",
    "Интересная компания",
    "Хорошие условия",
    "Другое",
]

DECLINE_REASONS = [
    "Низкий score",
    "Не подходит стек",
    "Не удалёнка",
    "Другое",
]


def build_card_kb(vacancy_id: int) -> InlineKeyboardBuilder:
    """Two primary action buttons for a vacancy card."""
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отказался", callback_data=f"vac:{vacancy_id}:cr")
    kb.button(text="✔️ Откликнулся", callback_data=f"vac:{vacancy_id}:ca")
    kb.adjust(2)
    return kb


def build_confirm_kb(vacancy_id: int, action: str) -> InlineKeyboardBuilder:
    """Confirm / Back buttons for an action ('a' = accept, 'r' = reject)."""
    kb = InlineKeyboardBuilder()
    label = "отклик" if action == "a" else "отказ"
    kb.button(text=f"✅ Подтвердить {label}", callback_data=f"vac:{vacancy_id}:p{action}")
    kb.button(text="⬅️ Назад", callback_data=f"vac:{vacancy_id}:show")
    kb.adjust(2)
    return kb


def build_reason_kb(vacancy_id: int, kind: str) -> InlineKeyboardBuilder:
    """Reason selection buttons. kind: 'a' = accept reasons, 'r' = decline reasons."""
    reasons = ACCEPT_REASONS if kind == "a" else DECLINE_REASONS
    reason_prefix = "ra" if kind == "a" else "rd"
    kb = InlineKeyboardBuilder()
    for idx, text in enumerate(reasons):
        kb.button(text=text, callback_data=f"vac:{vacancy_id}:{reason_prefix}:{idx}")
    kb.button(text="⬅️ Назад", callback_data=f"vac:{vacancy_id}:show")
    kb.adjust(1)
    return kb
