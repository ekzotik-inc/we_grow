"""Premium (кастомные) эмодзи Telegram с безопасным фолбэком.

Тег <tg-emoji emoji-id="..."> работает только при parse_mode=HTML и только если
у владельца бота есть Telegram Premium. Пока премиум не включён или ID нет —
pe() возвращает обычный эмодзи, и бот работает без ошибок.

См. docs/premium-emoji.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_IDS_PATH = Path(__file__).with_name("emoji_ids.json")

ENABLED = os.getenv("PREMIUM_EMOJI", "").strip().lower() in {"1", "true", "yes", "on"}

_IDS: dict[str, str] = {}
if _IDS_PATH.exists():
    try:
        raw = json.loads(_IDS_PATH.read_text(encoding="utf-8"))
        # оставляем только непустые ID
        _IDS = {k: str(v) for k, v in raw.items() if isinstance(v, (str, int)) and str(v).strip()}
    except json.JSONDecodeError:
        _IDS = {}


def pe(emoji: str) -> str:
    """Премиум-версия эмодзи (HTML-тег) или обычный эмодзи как фолбэк."""
    cid = _IDS.get(emoji)
    if ENABLED and cid:
        return f'<tg-emoji emoji-id="{cid}">{emoji}</tg-emoji>'
    return emoji
