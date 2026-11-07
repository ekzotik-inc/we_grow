"""Модерация результата (принять / отклонить) — общая для бота и Mini App.

Раньше логика жила в хендлерах канала проверки. Теперь её вызывают и кнопки
под скриншотом (admin_settings.mod_accept / mod_reject), и админка Mini App
(webapp /api/admin/moderate), поэтому пересчёты и пуши одинаковы везде:
серия, недельный бонус (+ пуш «заработал / засчитан»), флешмоб, уведомление
участника. Смена статуса атомарна (db.transition_entry): если два админа
нажали одновременно, второй получит «уже обработано».
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from backend.scoring import points_for_steps
from bot import db, texts

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModResult:
    ok: bool
    code: str            # accepted | rejected | not_found | done | disqualified
    message: str         # коротко, для ответа админу
    points: int = 0
    mult: int = 1


async def bonus_sync(bot, tg_id: int, day) -> int:
    """Пересчёт недельного бонуса + пуш: «заработал, пришли отчёт» или
    «засчитан» (если отчёт за неделю уже есть)."""
    ch = await db.recompute_weekly_bonus_change(tg_id, day)
    note = texts.bonus_notice(ch)
    if note:
        await _send(bot, tg_id, note)
    return ch.new


async def flashmob_sync(bot, day) -> None:
    """Пересчёт командного флешмоба после правки результатов за день
    (импорт локальный — модуль флешмоба тянет роутер и клавиатуры)."""
    from bot.handlers.flashmob import sync
    await sync(bot, day)


async def _send(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001 — участник заблокировал бота и т.п.
        log.info("push to %s failed: %s", chat_id, e)


async def submission_caption(e) -> str:
    """Подпись карточки модерации (с анти-дубль-предупреждением)."""
    caption = texts.admin_new_submission(e)
    if e["screenshot_unique_id"]:
        dup = await db.duplicate_screenshot(e["screenshot_unique_id"], e["id"])
        if dup:
            caption += texts.admin_duplicate_warn(dup)
    return caption


async def accept(bot, entry_id: int) -> ModResult:
    e = await db.entry_by_id(entry_id)
    if e is None:
        return ModResult(False, "not_found", "Запись не найдена.")
    if e["status"] != "pending":
        return ModResult(False, "done", "Уже обработано.")
    # Карточка могла уйти до дисквалификации: такой результат не принимаем.
    # Статус остаётся pending: если участника восстановят, он вернётся в очередь.
    p = await db.get_participant(e["participant_id"])
    if p is not None and p["disqualified_at"]:
        return ModResult(False, "disqualified",
                         "Участник дисквалифицирован — результат не засчитывается.")
    # Тайный челлендж: множитель зависит от дня, команды и времени ОТПРАВКИ.
    mult, _ch = await db.challenge_multiplier(e["participant_id"], e["entry_date"],
                                              e["created_at"])
    pts = points_for_steps(e["steps"]) * mult
    if not await db.transition_entry(e["id"], "accepted", pts):
        return ModResult(False, "done", "Уже обработано.")
    st = await db.recompute_streak(e["participant_id"])
    await _send(bot, e["participant_id"],
                texts.accepted_note(e["steps"], pts, st.current_len, mult))
    await bonus_sync(bot, e["participant_id"], e["entry_date"])
    await flashmob_sync(bot, e["entry_date"])
    return ModResult(True, "accepted", "Принято ✅", pts, mult)


async def reject(bot, entry_id: int) -> ModResult:
    e = await db.entry_by_id(entry_id)
    if e is None:
        return ModResult(False, "not_found", "Запись не найдена.")
    if not await db.transition_entry(e["id"], "rejected", 0):
        return ModResult(False, "done", "Уже обработано.")
    await db.recompute_streak(e["participant_id"])
    await db.recompute_weekly_bonus(e["participant_id"], e["entry_date"])
    await flashmob_sync(bot, e["entry_date"])
    await _send(bot, e["participant_id"], texts.REJECTED_NOTE)
    return ModResult(True, "rejected", "Отклонено ❌")


def verdict_suffix(res: ModResult, who: str, where: str = "") -> str:
    """Приписка к карточке модерации: что решили и кто."""
    tail = f" · {where}" if where else ""
    if res.code == "accepted":
        x = f" ×{res.mult} 🎲" if res.mult > 1 else ""
        return f"\n\n✅ Принято, +{res.points}{x} ({escape(who)}{tail})"
    if res.code == "rejected":
        return f"\n\n❌ Отклонено ({escape(who)}{tail})"
    if res.code == "disqualified":
        return "\n\n⛔ Участник дисквалифицирован — результат не засчитан"
    return "\n\nℹ️ уже обработано"


async def close_review_card(bot, entry_id: int, res: ModResult, who: str) -> None:
    """После решения в Mini App — снять кнопки с карточки в канале проверки,
    чтобы никто не нажал их повторно, и подписать, кто решил."""
    e = await db.entry_by_id(entry_id)
    if e is None or not e["review_chat"] or not e["review_msg"]:
        return
    try:
        caption = await submission_caption(e) + verdict_suffix(res, who, "Mini App")
        await bot.edit_message_caption(chat_id=e["review_chat"], message_id=e["review_msg"],
                                       caption=caption, reply_markup=None)
    except Exception as ex:  # noqa: BLE001 — карточку могли удалить
        log.info("review card %s not updated: %s", entry_id, ex)
