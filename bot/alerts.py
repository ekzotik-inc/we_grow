"""Ошибки — сразу владельцам в Telegram, а не только в логи Render.

Ставится обработчиком на корневой логгер (бот и webapp): любая запись уровня
ERROR — необработанная ошибка хендлера (main._on_error), упавшая задача
планировщика (APScheduler), исключение в эндпоинте Mini App (uvicorn) —
уходит владельцам коротким сообщением с местом ошибки.

Защита от лавины: одинаковая ошибка (тип + место) — не чаще раза в 15 минут,
всего не больше 20 сообщений в час; повторы считаются и показываются в
следующем сообщении. Отправка — в отдельном потоке через Bot API, чтобы не
блокировать event loop; сбой отправки никогда не логируется как ERROR
(иначе обработчик вызвал бы сам себя).
"""
from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable

SAME_ERROR_EVERY = 15 * 60      # сек между одинаковыми ошибками
HOURLY_CAP = 20                 # максимум сообщений в час
_IGNORE = ("bot.alerts", "aiogram.event")   # aiogram.event дублирует _on_error


def _esc_cut(s: str, limit: int, tail: bool = False) -> str:
    """html.escape, но не длиннее limit символов ПОСЛЕ экранирования;
    tail=True — оставить конец (у трейсбэка важна последняя строка)."""
    out, size = [], 0
    for ch in (reversed(s) if tail else s):
        e = html.escape(ch)
        if size + len(e) > limit:
            break
        out.append(e)
        size += len(e)
    return "".join(reversed(out) if tail else out)


class TelegramAlertHandler(logging.Handler):
    def __init__(self, token: str, recipients: Callable[[], Iterable[int]], service: str):
        super().__init__(level=logging.ERROR)
        self._token = token
        self._recipients = recipients
        self._service = service
        self._last: dict[str, float] = {}
        self._muted: dict[str, int] = {}
        self._sent: list[float] = []
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(record: logging.LogRecord) -> str:
        """Тип исключения + последнее место в нашем коде; без исключения — текст."""
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            frames = traceback.extract_tb(exc.__traceback__)
            ours = [f for f in frames if "site-packages" not in f.filename] or frames
            where = f"{os.path.basename(ours[-1].filename)}:{ours[-1].lineno}" if ours else "?"
            return f"{type(exc).__name__}@{where}"
        return f"{record.name}:{record.getMessage()[:80]}"

    def _allow(self, key: str, now: float) -> int | None:
        """None — не слать; иначе число подавленных повторов этой ошибки."""
        with self._lock:
            self._sent = [t for t in self._sent if now - t < 3600]
            if now - self._last.get(key, 0) < SAME_ERROR_EVERY or len(self._sent) >= HOURLY_CAP:
                self._muted[key] = self._muted.get(key, 0) + 1
                return None
            self._last[key] = now
            self._sent.append(now)
            return self._muted.pop(key, 0)

    def format_alert(self, record: logging.LogRecord, muted: int) -> str:
        """Текст для Telegram. Каждая часть экранируется и режется ОТДЕЛЬНО
        (_esc_cut), чтобы лимит 4096 не разрезал тег или &amp; — такое
        сообщение Telegram отверг бы целиком."""
        text = (f"🚨 <b>Ошибка · {_esc_cut(self._service, 60)}</b>\n"
                f"<code>{_esc_cut(self.fingerprint(record), 200)}</code>\n"
                f"{_esc_cut(record.getMessage(), 700)}")
        if muted:
            text += f"\n<i>(+{muted} таких же за последние 15 мин)</i>"
        if record.exc_info and record.exc_info[1] is not None:
            tb = "".join(traceback.format_exception(*record.exc_info))
            text += f"\n<pre>{_esc_cut(tb, 2600, tail=True)}</pre>"
        return text

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_IGNORE):
            return
        try:
            muted = self._allow(self.fingerprint(record), time.time())
            if muted is None:
                return
            text = self.format_alert(record, muted)
            ids = list(self._recipients())
        except Exception:  # noqa: BLE001 — обработчик логов не должен падать
            return
        if ids:
            self._dispatch(ids, text)

    def _dispatch(self, ids: list[int], text: str) -> None:
        threading.Thread(target=self._send, args=(ids, text), daemon=True).start()

    def _send(self, ids: list[int], text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        for chat_id in ids:
            body = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                           "parse_mode": "HTML"}).encode()
            try:
                with urllib.request.urlopen(url, data=body, timeout=10) as r:
                    json.load(r)
            except Exception as e:  # noqa: BLE001
                # Только WARNING и без URL (в нём токен) — иначе рекурсия/утечка.
                logging.getLogger("bot.alerts").warning("alert to %s not sent: %s",
                                                        chat_id, type(e).__name__)


def install(token: str, recipients: Callable[[], Iterable[int]], service: str) -> None:
    """Повесить обработчик на корневой логгер (повторный вызов — без дублей)."""
    root = logging.getLogger()
    if any(isinstance(h, TelegramAlertHandler) for h in root.handlers):
        return
    root.addHandler(TelegramAlertHandler(token, recipients, service))
