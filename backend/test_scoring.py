from datetime import date, timedelta

from scoring import StreakState, points_for_steps, needs_review, update_streak


def test_points_scale():
    assert points_for_steps(4_999) == 0
    assert points_for_steps(5_000) == 1
    assert points_for_steps(9_999) == 1
    assert points_for_steps(10_000) == 2
    assert points_for_steps(19_999) == 2
    assert points_for_steps(20_000) == 3
    assert points_for_steps(35_000) == 3


def test_review_flag():
    assert not needs_review(29_999)
    assert needs_review(30_000)


def _run(days_steps):
    """Прогоняет последовательность дней подряд, возвращает список StreakUpdate."""
    state = StreakState(0, None, 0)
    d = date(2026, 7, 17)
    out = []
    for i, steps in enumerate(days_steps):
        upd = update_streak(state, d + timedelta(days=i), steps)
        state = upd.state
        out.append(upd)
    return out


def test_bonus_only_on_seventh_day_and_replaces():
    ups = _run([10_000] * 7)
    # +4 только на 7-й день, промежуточного +2 нет
    assert [u.bonus_points for u in ups] == [0, 0, 0, 0, 0, 0, 4]
    assert ups[-1].state.current_len == 7
    assert ups[-1].state.bonus_awarded_cycles == 1


def test_break_resets_streak():
    ups = _run([10_000, 10_000, 4_000, 10_000])
    assert ups[2].state.current_len == 0
    assert ups[3].state.current_len == 1


def test_two_full_cycles():
    ups = _run([10_000] * 14)
    assert ups[6].bonus_points == 4
    assert ups[13].bonus_points == 4
    assert ups[13].state.bonus_awarded_cycles == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all passed")
