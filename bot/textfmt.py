"""Преобразование markdown-текста админа в безопасный HTML + премиум-эмодзи.

Поддержка: **жирный**, *курсив*, __подчёркнутый__, ~~зачёркнутый~~, `код`.
Спецсимволы экранируются, затем известные эмодзи заменяются на премиум-версии.
"""
from __future__ import annotations

import html
import re

from bot.premium_emoji import enrich


def md_to_html(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
    t = re.sub(r"__(.+?)__", r"<u>\1</u>", t, flags=re.S)
    t = re.sub(r"~~(.+?)~~", r"<s>\1</s>", t, flags=re.S)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t, flags=re.S)
    # одиночные * — курсив (не трогаем уже преобразованный **)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t, flags=re.S)
    return enrich(t)
