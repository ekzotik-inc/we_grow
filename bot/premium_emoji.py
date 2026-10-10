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

STEPY_ID = "5305729158385533791"   # маскот Stepy 🪴 — всегда свой ID

_IDS: dict[str, str] = {}
_EMOJI_RE: re.Pattern | None = None
# Итог проверки набора через Telegram (getCustomEmojiStickers) — для /health.
STATUS: dict = {"source": "файл bot/emoji_ids.json", "checked": False,
                "valid": 0, "total": 0, "sets": []}


def _load_file() -> dict[str, str]:
    if not _IDS_PATH.exists():
        return {}
    try:
        raw = json.loads(_IDS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {k: str(v) for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, (str, int)) and str(v).strip()}


def set_map(mapping: dict[str, str]) -> None:
    """Подменяет рабочую карту «эмодзи → ID» (Stepy всегда свой)."""
    global _IDS, _EMOJI_RE
    m = {k: v for k, v in mapping.items() if k and v}
    m["🪴"] = STEPY_ID
    _IDS = m
    # Длинные последовательности (ZWJ, флаги, с FE0F) — первыми, чтобы «👨‍💻»
    # не распалось на «👨» + «💻». Необязательный FE0F съедаем вместе с эмодзи.
    _EMOJI_RE = (re.compile("(" + "|".join(re.escape(k) for k in sorted(m, key=len, reverse=True))
                            + ")\ufe0f?") if m else None)


def current_map() -> dict[str, str]:
    return dict(_IDS)


def _load_fallback() -> dict[str, str]:
    """Прежний рабочий набор (iOS Icons) — запасные ID на случай, если ID из
    основного файла Telegram не подтвердит."""
    try:
        raw = json.loads(_IDS_PATH.read_text(encoding="utf-8")).get("_fallback") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return {k: str(v) for k, v in raw.items() if str(v).strip()}


set_map(_load_file())

# Сегменты, внутри которых менять нельзя: готовые tg-emoji, теги, code/pre.
_SKIP_RE = re.compile(r"(<tg-emoji\b.*?</tg-emoji>|<code\b.*?</code>|<pre\b.*?</pre>|<[^>]*>)",
                      re.S)


async def validate(bot) -> dict:
    """Спрашивает у Telegram, какие ID — настоящие премиум-эмодзи, и оставляет
    только их. ID обычных анимированных стикеров Telegram в тексте не
    показывает (молча рисует обычный эмодзи) — такие отбрасываем; для них
    берём запасной ID из прежнего набора, если он есть и подтверждён."""
    primary = dict(_IDS)
    fallback = _load_fallback()
    ids = sorted({*primary.values(), *fallback.values()})
    ok: set[str] = set()
    sets: set[str] = set()
    for i in range(0, len(ids), 200):
        for st in await bot.get_custom_emoji_stickers(custom_emoji_ids=ids[i:i + 200]):
            if st.custom_emoji_id:
                ok.add(st.custom_emoji_id)
                if st.set_name:
                    sets.add(st.set_name)
    result = {}
    for k in {*primary, *fallback}:
        if primary.get(k) in ok:
            result[k] = primary[k]
        elif fallback.get(k) in ok:
            result[k] = fallback[k]
    set_map(result)
    STATUS.update(checked=True, valid=len(_IDS) - 1, total=len({*primary, *fallback}) - 1,
                  sets=sorted(sets), stepy_ok=STEPY_ID in ok,
                  primary_ok=sum(1 for v in primary.values() if v in ok) - (STEPY_ID in ok))
    return STATUS


async def load_pack(bot, name: str) -> dict:
    """Загружает набор премиум-эмодзи по имени/ссылке (t.me/addemoji/NAME):
    карта «эмодзи → ID» строится из самого набора, без файлов и редеплоя."""
    name = name.strip().rstrip("/").rsplit("/", 1)[-1]
    sset = await bot.get_sticker_set(name=name)
    if sset.sticker_type != "custom_emoji":
        raise ValueError("это набор стикеров, а не премиум-эмодзи (нужна ссылка "
                         "t.me/addemoji/…)")
    mapping: dict[str, str] = {}
    for st in sset.stickers:
        if not (st.emoji and st.custom_emoji_id):
            continue
        mapping.setdefault(st.emoji, st.custom_emoji_id)
        mapping.setdefault(st.emoji.replace("\ufe0f", ""), st.custom_emoji_id)
    if not mapping:
        raise ValueError("в наборе нет эмодзи")
    return {"name": sset.name, "title": sset.title, "map": mapping}


async def pack_name_by_emoji_id(bot, custom_emoji_id: str) -> str | None:
    """Имя набора по любому премиум-эмодзи из него."""
    stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=[custom_emoji_id])
    return stickers[0].set_name if stickers else None


async def check_ids(bot, ids: list[str]) -> dict[str, str | None]:
    """{id: имя набора или None, если Telegram не считает ID премиум-эмодзи}."""
    found = {st.custom_emoji_id: (st.set_name or "?")
             for st in await bot.get_custom_emoji_stickers(custom_emoji_ids=ids)}
    return {i: found.get(i) for i in ids}


def apply_pack(pack: dict) -> None:
    """Подключает набор ПОВЕРХ текущей (проверенной) карты: эмодзи из набора
    берутся из него, остальные остаются из файла/прежнего набора. Раньше набор
    заменял карту целиком, и эмодзи, которых в нём нет (👋 🌳 ⭐ 🔥 в главном
    меню), становились обычными."""
    merged = dict(_IDS)
    merged.update(pack["map"])
    set_map(merged)
    sets = sorted({*STATUS.get("sets", []), pack["name"]})
    STATUS.update(source=f"набор «{pack.get('title') or pack['name']}» + проверенные из файла",
                  checked=True, valid=len(_IDS) - 1, total=len(_IDS) - 1, sets=sets)


def pe(emoji: str) -> str:
    """Stepy 🪴 — сразу премиум-тегом (его ID постоянный). Остальные эмодзи
    возвращаются как есть: их подставит EmojiMiddleware в момент отправки,
    уже по проверенной Telegram карте (многие тексты собираются при импорте,
    до проверки набора, — «запекать» в них ID нельзя)."""
    if ENABLED and emoji.replace("\ufe0f", "") == "🪴":
        return f'<tg-emoji emoji-id="{STEPY_ID}">{emoji}</tg-emoji>'
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


_LEAD_RE_CACHE: dict = {}


def _iconize_inline(markup) -> None:
    """Inline-кнопки не умеют премиум-эмодзи в тексте, но с Bot API 9.4 у них
    есть icon_custom_emoji_id. Если подпись начинается с эмодзи из набора —
    переносим его в иконку (callback_data и url не меняются). Reply-кнопки
    не трогаем: их текст приходит обратно в бот и сверяется с подписями."""
    rows = getattr(markup, "inline_keyboard", None)
    if not rows or _EMOJI_RE is None:
        return
    for row in rows:
        for btn in row:
            text = getattr(btn, "text", "") or ""
            if getattr(btn, "icon_custom_emoji_id", None) or not text:
                continue
            m = _EMOJI_RE.match(text)
            if not m:
                continue
            rest = text[m.end():].lstrip()
            if not rest:          # кнопка из одного эмодзи — оставляем как есть
                continue
            btn.icon_custom_emoji_id = _IDS[m.group(1)]
            btn.text = rest


class EmojiMiddleware(BaseRequestMiddleware):
    """Подменяет эмодзи в тексте/подписи исходящих HTML-сообщений бота.

    Только методы-сообщения: у всплывающих ответов на кнопки (answerCallbackQuery)
    тоже есть поле text, но разметку они не понимают."""

    _METHODS = {"SendMessage", "EditMessageText", "SendPhoto", "SendAnimation",
                "SendVideo", "SendDocument", "SendAudio", "SendVoice",
                "EditMessageCaption", "SendMediaGroup", "CopyMessage",
                "EditMessageReplyMarkup"}

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
            # Иконки кнопок — только в личных чатах (chat_id > 0): в каналах
            # проверки/заявок премиум-эмодзи могут быть недоступны боту, а
            # ошибка на кнопке сорвала бы отправку карточки модерации. И только
            # если набор проверен Telegram (validate/apply_pack): битый ID в
            # иконке ломает отправку сообщения целиком.
            chat_id = getattr(method, "chat_id", None)
            if isinstance(chat_id, int) and chat_id > 0 and STATUS.get("checked"):
                _iconize_inline(getattr(method, "reply_markup", None))
            for item in getattr(method, "media", None) or []:   # альбомы
                cap = getattr(item, "caption", None)
                if isinstance(cap, str) and cap and self._is_html(
                        getattr(item, "parse_mode", None), bot):
                    item.caption = enrich(cap)
        return await make_request(bot, method)
