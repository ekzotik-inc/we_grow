"""Каноническая реализация правил начисления баллов и серий.

Соответствует официальным правилам марафона (см. docs/scoring.md, правила 9–10).
Логика без побочных эффектов — чистые функции, которые вызывают бот и планировщик.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

QUALIFYING_STEPS = 10_000   # порог «активного» дня для серии
MIN_COUNTED_STEPS = 5_000   # ниже — 0 баллов, но день «сдан»
REVIEW_STEPS = 30_000       # выше потолка шкалы → флаг на проверку P&C

# Недельный бонус за серию идущих подряд дней по 10 000+ (правило 10).
BONUS_5_DAYS = 2
BONUS_7_DAYS = 4


def points_for_steps(steps: int) -> int:
    """Базовые баллы за день по шкале (правило 9), без недельного бонуса.

    5 000–9 999 = 1, 10 000–14 999 = 2, 15 000–30 000 = 3.
    Выше 30 000 — те же 3 балла, но день помечается на проверку (needs_review).
    """
    if steps < MIN_COUNTED_STEPS:
        return 0
    if steps < 10_000:
        return 1
    if steps < 15_000:
        return 2
    return 3


def needs_review(steps: int) -> bool:
    """Флаг на ручную проверку P&C (защита от накруток): выше потолка шкалы."""
    return steps > REVIEW_STEPS


def weekly_streak_bonus(daily_steps: list[int]) -> int:
    """Недельный бонус по правилу 10.

    Считает максимальную длину серии идущих подряд дней с >= 10 000 шагов
    внутри недели. 7 дней подряд = +4, 5–6 дней подряд = +2, иначе 0.
    Начисляется высший достигнутый порог (не суммируется).
    """
    best = current = 0
    for steps in daily_steps:
        if steps >= QUALIFYING_STEPS:
            current += 1
            best = max(best, current)
        else:
            current = 0
    if best >= 7:
        return BONUS_7_DAYS
    if best >= 5:
        return BONUS_5_DAYS
    return 0


@dataclass
class StreakState:
    current_len: int                 # дней подряд по 10 000+
    last_qualifying_date: date | None


@dataclass
class StreakUpdate:
    state: StreakState
    milestone: int | None            # ближайшая цель бонуса: 5, 7 или None (максимум взят)
    days_to_milestone: int           # сколько ещё дней 10 000+ до неё


def update_streak(state: StreakState, entry_date: date, steps: int) -> StreakUpdate:
    """Пересчёт серии подряд идущих дней по 10 000+ (для мотивации в ответе).

    Баллы здесь не начисляются — бонус за серию считается недельно
    (weekly_streak_bonus) по правилу 10. Эта функция ведёт счётчик серии и
    подсказывает, сколько дней осталось до ближайшего бонусного порога.
    """
    if steps < QUALIFYING_STEPS:
        return StreakUpdate(StreakState(0, state.last_qualifying_date), 5, 5)

    consecutive = (
        state.last_qualifying_date is not None
        and (entry_date - state.last_qualifying_date).days == 1
    )
    length = state.current_len + 1 if consecutive else 1
    new = StreakState(length, entry_date)

    if length < 5:
        return StreakUpdate(new, 5, 5 - length)
    if length < 7:
        return StreakUpdate(new, 7, 7 - length)
    return StreakUpdate(new, None, 0)
