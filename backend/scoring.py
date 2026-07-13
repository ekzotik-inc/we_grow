"""Каноническая реализация правил начисления баллов и серий.

Соответствует docs/scoring.md. Логика без побочных эффектов — чистые функции,
которые вызывает и бот, и планировщик проверки сводок.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

QUALIFYING_STEPS = 10_000  # порог для продления серии
MIN_COUNTED_STEPS = 5_000  # ниже — 0 баллов, но день «сдан»
REVIEW_STEPS = 30_000      # авто-флаг на проверку P&C
STREAK_CYCLE = 7           # длина окна серии
STREAK_BONUS = 4           # +4 за цикл, заменяет промежуточный +2 (максимум)


def points_for_steps(steps: int) -> int:
    """Базовые баллы за день по шкале (без бонуса за серию)."""
    if steps < MIN_COUNTED_STEPS:
        return 0
    if steps < 10_000:
        return 1
    if steps < 20_000:
        return 2
    return 3  # 20 000+ и 30 000+ (последнее — с флагом на проверку)


def needs_review(steps: int) -> bool:
    """Авто-флаг на ручную проверку P&C (защита от накруток)."""
    return steps >= REVIEW_STEPS


@dataclass
class StreakState:
    current_len: int
    last_qualifying_date: date | None
    bonus_awarded_cycles: int


@dataclass
class StreakUpdate:
    state: StreakState
    bonus_points: int          # начислено за завершённый цикл в этот день (0 или 4)
    days_to_next_bonus: int    # сколько ещё дней 10 000+ до следующего +4


def update_streak(state: StreakState, entry_date: date, steps: int) -> StreakUpdate:
    """Пересчёт серии при новом дне.

    Серия растёт только на днях >= 10 000 шагов и только если день идёт сразу
    за last_qualifying_date. Любой разрыв или день < 10 000 обнуляет серию.
    На каждом 7-м дне подряд начисляется +4 (заменяет промежуточный +2), после
    чего окно стартует заново.
    """
    if steps < QUALIFYING_STEPS:
        new = StreakState(0, state.last_qualifying_date, state.bonus_awarded_cycles)
        return StreakUpdate(new, 0, STREAK_CYCLE)

    consecutive = (
        state.last_qualifying_date is not None
        and (entry_date - state.last_qualifying_date).days == 1
    )
    length = state.current_len + 1 if consecutive else 1

    bonus = 0
    cycles = state.bonus_awarded_cycles
    if length % STREAK_CYCLE == 0:
        bonus = STREAK_BONUS
        cycles += 1

    new = StreakState(length, entry_date, cycles)
    days_to_next = (STREAK_CYCLE - (length % STREAK_CYCLE)) % STREAK_CYCLE
    if days_to_next == 0:
        days_to_next = STREAK_CYCLE  # только что выдали бонус — до следующего полный цикл
    return StreakUpdate(new, bonus, days_to_next)
