from datetime import date, timedelta

from scoring import (
    StreakState,
    needs_review,
    points_for_steps,
    update_streak,
    weekly_streak_bonus,
)


def test_points_scale():
    assert points_for_steps(4_999) == 0
    assert points_for_steps(5_000) == 1
    assert points_for_steps(9_999) == 1
    assert points_for_steps(10_000) == 2
    assert points_for_steps(14_999) == 2
    assert points_for_steps(15_000) == 3
    assert points_for_steps(30_000) == 3
    assert points_for_steps(45_000) == 3


def test_review_flag():
    assert not needs_review(30_000)
    assert needs_review(30_001)


def test_weekly_bonus_tiers():
    assert weekly_streak_bonus([12_000] * 7) == 4          # вся неделя
    assert weekly_streak_bonus([12_000] * 5 + [3_000, 3_000]) == 2  # ровно 5 подряд
    assert weekly_streak_bonus([12_000] * 6) == 2          # 6 подряд → всё ещё +2
    assert weekly_streak_bonus([12_000] * 4) == 0          # мало
    # разрыв в середине рвёт серию — учитывается лучший отрезок
    assert weekly_streak_bonus([12_000] * 4 + [2_000] + [12_000] * 2) == 0
    assert weekly_streak_bonus([12_000] * 5 + [2_000] + [12_000]) == 2


def _run(days_steps):
    state = StreakState(0, None)
    d = date(2026, 7, 17)
    out = []
    for i, steps in enumerate(days_steps):
        upd = update_streak(state, d + timedelta(days=i), steps)
        state = upd.state
        out.append(upd)
    return out


def test_streak_counter_and_milestones():
    ups = _run([12_000] * 7)
    assert [u.state.current_len for u in ups] == [1, 2, 3, 4, 5, 6, 7]
    assert ups[3].milestone == 5 and ups[3].days_to_milestone == 1  # 4-й день → 1 до +2
    assert ups[4].milestone == 7 and ups[4].days_to_milestone == 2  # 5-й день → 2 до +4
    assert ups[6].milestone is None                                  # 7 дней — максимум


def test_break_resets_streak():
    ups = _run([12_000, 12_000, 4_000, 12_000])
    assert ups[2].state.current_len == 0
    assert ups[3].state.current_len == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all passed")
