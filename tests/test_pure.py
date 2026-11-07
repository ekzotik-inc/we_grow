"""Чистая логика без БД: лучшая серия, алерты об ошибках, картинка итогов."""
import logging
import sys
from datetime import date, timedelta

from backend.scoring import best_streak

D0 = date(2026, 11, 2)


def days(*steps):
    return {D0 + timedelta(days=i): s for i, s in enumerate(steps) if s is not None}


# ---- best_streak ----------------------------------------------------------

def test_best_streak_counts_longest_run_of_10k_days():
    assert best_streak(days(12000, 11000, 3000, 10000, 10000, 10000)) == 3


def test_best_streak_missing_date_breaks_run():
    # 3-й день не сдан вовсе (нет записи) — серия рвётся так же, как при малых шагах
    assert best_streak(days(12000, 12000, None, 12000)) == 2


def test_best_streak_order_independent_and_empty():
    d = days(15000, 15000, 15000)
    assert best_streak(dict(reversed(list(d.items())))) == 3
    assert best_streak({}) == 0
    assert best_streak(days(9999, 9999)) == 0


# ---- alerts ---------------------------------------------------------------

def _record(exc: Exception) -> logging.LogRecord:
    try:
        raise exc
    except Exception:
        return logging.LogRecord("bot.main", logging.ERROR, __file__, 1, "boom %s", ("x",),
                                 sys.exc_info())


def test_alert_same_error_is_throttled_and_counted():
    from bot.alerts import TelegramAlertHandler
    sent = []
    h = TelegramAlertHandler("t", lambda: [1], "test")
    h._dispatch = lambda ids, text: sent.append(text)      # без сети и потоков
    for _ in range(3):
        h.emit(_record(ValueError("bad")))
    assert len(sent) == 1                                   # повторы подавлены
    h._last.clear()                                         # «прошло 15 минут»
    h.emit(_record(ValueError("bad")))
    assert len(sent) == 2 and "+2 таких же" in sent[1]      # подавленные посчитаны
    h.emit(_record(KeyError("other")))                      # другая ошибка — сразу
    assert len(sent) == 3


def test_alert_text_is_escaped_and_short():
    from bot.alerts import TelegramAlertHandler
    h = TelegramAlertHandler("t", lambda: [1], "бот")
    rec = _record(ValueError("<b>" * 3000))
    rec.msg, rec.args = "<script>" + "&" * 3000, ()
    text = h.format_alert(rec, 0)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "<b>" not in text.split("</b>", 1)[1]           # из исключения теги не протекли
    assert len(text) <= 4096 and text.endswith("</pre>")    # лимит Telegram, теги целы
    assert "&amp" not in text.replace("&amp;", "")          # ни одной разрезанной сущности
    assert h.fingerprint(_record(ValueError())).startswith("ValueError@test_pure.py:")


def test_alert_ignores_own_logger():
    from bot.alerts import TelegramAlertHandler
    h = TelegramAlertHandler("t", lambda: [1], "test")
    called = []
    h._allow = lambda *a: called.append(1)
    h.emit(logging.LogRecord("bot.alerts", logging.ERROR, __file__, 1, "x", (), None))
    assert not called


# ---- финал: картинка и подпись --------------------------------------------

def _person(champion: bool):
    from bot.final import Personal
    return Personal(1, "Айдана Жанышбекова", "Секвойи", 1 if champion else 3, 5, 23.5,
                    168420, 13, 24310, 7, champion)


def test_final_card_is_jpeg_1080x1350():
    import io
    from PIL import Image
    from bot.final import render
    img = Image.open(io.BytesIO(render(_person(True))))
    assert img.format == "JPEG" and img.size == (1080, 1350)


def test_final_caption_champion_gets_prizes_others_get_place():
    from bot.final import Standings, caption
    st = Standings(board=[{"id": 1, "name": "Секвойи", "points": 12.5}],
                   winner={"id": 1, "name": "Секвойи", "points": 12.5}, pending=0)
    champ = caption(_person(True), st)
    other = caption(_person(False), st)
    assert "Это твоя команда" in champ and "Redmi Buds" in champ
    assert "3 место из 5" in other and "Redmi Buds" not in other
    assert "«Секвойи»" in other and len(champ) <= 1024
