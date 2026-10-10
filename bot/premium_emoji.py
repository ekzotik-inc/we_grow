"""Premium (кастомные) эмодзи Telegram с безопасным фолбэком.

Тег <tg-emoji emoji-id="..."> работает только при parse_mode=HTML и только если
у владельца бота есть Telegram Premium. Пока премиум не включён или ID нет —
pe() возвращает обычный эмодзи, и бот работает без ошибок.

Набор — «Animated Emoji» (анимированные версии обычных эмодзи, bot/emoji_ids.json).
Чтобы не расставлять pe() руками по всем текстам, EmojiMiddleware на сессии бота
подменяет обычные эмодзи на анимированные в КАЖДОМ исходящем HTML-сообщении
(текст и подписи). Уже размеченные <tg-emoji> (Stepy) не трогаются.

См. docs/premium-emoji.md.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from aiogram.client.session.middlewares.base import BaseRequestMiddleware

_IDS_PATH = Path(__file__).with_name("emoji_ids.json")

ENABLED = os.getenv("PREMIUM_EMOJI", "").strip().lower() in {"1", "true", "yes", "on"}

# Telegram принимает не больше 100 кастомных эмодзи в одном сообщении.
_MAX_PER_MESSAGE = 90

_IDS: dict[str, str] = {}
if _IDS_PATH.exists():
    try:
        raw = json.loads(_IDS_PATH.read_text(encoding="utf-8"))
        # оставляем только непустые ID
        _IDS = {k: str(v) for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, (str, int)) and str(v).strip()}
    except json.JSONDecodeError:
        _IDS = {}

# Длинные последовательности (ZWJ, флаги, с FE0F) — первыми, чтобы «👨‍💻» не
# распалось на «👨» + «💻». Необязательный FE0F после эмодзи съедаем вместе с ним.
_EMOJI_RE = (re.compile("(" + "|".join(re.escape(k) for k in sorted(_IDS, key=len, reverse=True))
                        + ")️?") if _IDS else None)
# Сегменты, внутри которых менять нельзя: готовые tg-emoji, теги, code/pre.
_SKIP_RE = re.compile(r"(<tg-emoji\b.*?</tg-emoji>|<code\b.*?</code>|<pre\b.*?</pre>|<[^>]*>)",
                      re.S)


def pe(emoji: str) -> str:
    """Премиум-версия эмодзи (HTML-тег) или обычный эмодзи как фолбэк."""
    cid = _IDS.get(emoji) or _IDS.get(emoji.replace("️", ""))
    if ENABLED and cid:
        return f'<tg-emoji emoji-id="{cid}">{emoji}</tg-emoji>'
    return emoji


def enrich(text: str) -> str:
    """Заменяет в готовом HTML-тексте обычные эмодзи на анимированные.

    Не трогает уже размеченные <tg-emoji>, атрибуты тегов и <code>/<pre>;
    соблюдает лимит Telegram на число кастомных эмодзи в сообщении.
    При выключенном премиуме возвращает текст без изменений."""
    if not ENABLED or _EMOJI_RE is None or not text:
        return text
    budget = _MAX_PER_MESSAGE - text.count("<tg-emoji")

    def repl(m: re.Match) -> str:
        nonlocal budget
        if budget <= 0:
            return m.group(0)
        budget -= 1
        return f'<tg-emoji emoji-id="{_IDS[m.group(1)]}">{m.group(0)}</tg-emoji>'

    parts = _SKIP_RE.split(text)
    for i in range(0, len(parts), 2):          # чётные — обычный текст
        if parts[i]:
            parts[i] = _EMOJI_RE.sub(repl, parts[i])
    return "".join(parts)


class EmojiMiddleware(BaseRequestMiddleware):
    """Подменяет эмодзи в тексте/подписи исходящих HTML-сообщений бота.

    Только методы-сообщения: у всплывающих ответов на кнопки (answerCallbackQuery)
    тоже есть поле text, но разметку они не понимают."""

    _METHODS = {"SendMessage", "EditMessageText", "SendPhoto", "SendAnimation",
                "SendVideo", "SendDocument", "SendAudio", "SendVoice",
                "EditMessageCaption", "SendMediaGroup", "CopyMessage"}

    @staticmethod
    def _is_html(mode, bot) -> bool:
        from aiogram.client.default import Default
        if isinstance(mode, Default):
            mode = bot.default.parse_mode
        return isinstance(mode, str) and mode.upper() == "HTML"

    async def __call__(self, make_request, bot, method):
        if ENABLED and type(method).__name__ in self._METHODS:
            if self._is_html(getattr(method, "parse_mode", None), bot):
                for field in ("text", "caption"):
                    value = getattr(method, field, None)
                    if isinstance(value, str) and value:
                        setattr(method, field, enrich(value))
            for item in getattr(method, "media", None) or []:   # альбомы
                cap = getattr(item, "caption", None)
                if isinstance(cap, str) and cap and self._is_html(
                        getattr(item, "parse_mode", None), bot):
                    item.caption = enrich(cap)
        return await make_request(bot, method)
