"""Голос маскота Гроу 🌱 — спортивный, но текст чистый и «воздушный».

Формат — HTML (parse_mode=HTML по умолчанию). Оформление минималистичное:
жирные акценты и пустые строки вместо тяжёлых вложенных цитат. Премиум-эмодзи
через pe() (см. docs/premium-emoji.md).
"""
from html import escape

from bot.premium_emoji import pe

GROW = pe("🌱")

FITBIT_ANDROID = "https://play.google.com/store/apps/details?id=com.fitbit.FitbitMobile&hl=en_US"
FITBIT_IOS = "https://apps.apple.com/us/app/fitbit-health-fitness/id462638897"

WELCOME = (
    f"{pe('👟')} <b>Step Together</b> — на старт!\n\n"
    f"Привет! Я Гроу {pe('🌱')}, твой тренер на марафоне.\n"
    "Мы растём, когда двигаемся: каждый шаг — это баллы и рост твоего растения.\n\n"
    "Сначала правила 👇"
)

RULES = (
    "📋 <b>Правила марафона Step Together</b>\n\n"
    "<b>1.</b> Участвуют все сотрудники подразделения ASR.\n"
    "<b>2.</b> Регистрация и распределение по командам — в этом боте.\n"
    "<b>3.</b> Приложение для подсчёта шагов — Fitbit (Google Health):\n"
    f"    • Android: {FITBIT_ANDROID}\n"
    f"    • iOS: {FITBIT_IOS}\n"
    "<b>4.</b> В команде — от 8 до 10 участников.\n"
    "<b>5.</b> Если команда заполнена, P&amp;C предложит другую.\n"
    "<b>6.</b> Участвуешь активно и доходишь до финиша.\n"
    "<b>7.</b> Сроки: с 17 июля по 7 августа включительно.\n"
    "<b>8.</b> Каждую неделю — лидерборд участников и команд.\n\n"
    f"{pe('🎯')} <b>Баллы за день</b>\n"
    "5 000 – 9 999 — 1 балл\n"
    "10 000 – 14 999 — 2 балла\n"
    "15 000 – 30 000 — 3 балла\n\n"
    f"{pe('🥇')} <b>Бонус за серию</b> (по итогам недели)\n"
    "5 дней подряд 10 000+ — +2 балла\n"
    "7 дней подряд 10 000+ — +4 балла\n\n"
    "<b>11.</b> Шаги фиксируй каждый день до 23:55 (скрин с датой и числом).\n"
    "<b>12.</b> В воскресенье до 23:55 — недельная сводка для бонуса.\n"
    "<b>13.</b> P&amp;C может запросить скрин для проверки в течение дня.\n"
    "<b>14.</b> Нарушение правил — дисквалификация, результаты не в зачёт.\n\n"
    "Готов дойти до финиша? 🏁"
)

CONSENT_BUTTON = "Принимаю правила 🏁"
ASK_NAME = "Как тебя зовут? Напиши <b>ФИО</b>."
ASK_ASR = "Ты из подразделения <b>ASR</b>?"
FIT_LINKS = (
    "👟 <b>Fitbit</b> (Google Health) — им считаем шаги:\n"
    f"    • Android: {FITBIT_ANDROID}\n"
    f"    • iOS: {FITBIT_IOS}"
)
ASK_TEAM = "Выбери команду — вместе бежать веселее:"
RANDOM_TEAM = "🎲 Определите меня"

# После выбора команды — ожидание подтверждения P&C.
PENDING = (
    "📨 <b>Заявка отправлена!</b>\n\n"
    "Команда: <b>{team}</b>\n"
    "Ждём подтверждения от P&amp;C — придёт уведомление.\n"
    "Обычно это быстро 🌱"
)
APPROVED = (
    f"{pe('🎉')} <b>Заявка подтверждена — ты в игре!</b>\n\n"
    "Каждый день присылай шаги кнопкой «👟 Шаги за сегодня» или скрином.\n"
    "Первый шаг — самый важный 🏁"
)
REJECTED = (
    "К сожалению, заявка отклонена P&amp;C.\n"
    "Если это ошибка — свяжись с организаторами и пройди регистрацию заново: /start"
)
NOT_APPROVED_YET = "⏳ Твоя заявка ещё на подтверждении у P&amp;C. Как подтвердят — сразу напишу 🌱"

STEPS_BUTTON = "👟 Шаги за сегодня"
MENU_PROGRESS = "📊 Мой прогресс"
MENU_BOARD = "🏆 Лидерборд"
MENU_RULES = "📋 Правила"
MENU_HELP = "❓ Помощь"

HELP = (
    "❓ <b>Как участвовать</b>\n\n"
    "• Каждый день до 23:55 — «👟 Шаги за сегодня», пришли число или скрин из Fitbit.\n"
    "• Баллы: 5к — 1, 10к — 2, 15к+ — 3. Серия 10 000+ даёт недельный бонус.\n"
    "• «📊 Мой прогресс» и «🏆 Лидерборд» — открывают приложение.\n"
    "• «📋 Правила» — полный список.\n\n"
    "Команды: /start · /rules · /help · /reset"
)

ADMIN_PANEL = f"🛠 <b>Админ-панель P&amp;C</b> {pe('👑')}"


def admin_new_registration(p, team_name: str) -> str:
    uname = f"@{escape(p['username'])}" if p["username"] else "—"
    asr = "✅ да" if p["is_asr"] else "⚠️ <b>нет</b>"
    return (
        "🆕 <b>Новая заявка на участие</b>\n\n"
        f"👤 <b>{escape(p['full_name'])}</b>\n"
        f"🔗 {uname}\n"
        f"🆔 <code>{p['telegram_id']}</code>\n"
        f"🌳 Команда: <b>{escape(team_name)}</b>\n"
        f"🏢 Из ASR: {asr}\n\n"
        "Подтвердить участие?"
    )


ASK_STEPS_PHOTO = "👟 Кидай скрин из Fitbit или просто напиши число шагов."
CONFIRM_STEPS = "Вижу <b>{steps}</b> шагов — верно?"
ASK_MANUAL = "Не разобрал число. Напиши цифрами, например <code>12340</code>."
ALREADY_TODAY = "✅ Сегодня уже засчитано: <b>{steps}</b> шагов. До завтра! 🌙"

REMINDER_2100 = (
    "⏰ <b>Шаги за сегодня ещё не сданы!</b>\n"
    "Даже короткая прогулка — это баллы. Жми «👟 Шаги за сегодня» 💪"
)

WEEKLY_SUMMARY_REMINDER = (
    "📊 <b>Воскресенье — недельная сводка!</b>\n"
    "Пришли сводку по шагам из Fitbit до 23:55, чтобы забрать бонус за серию 🔥"
)

RESET_CONFIRM = (
    "⚠️ Сброс сотрёт <b>всё</b>: команду, серию, шаги и баллы. Без восстановления.\n\n"
    "Точно начать заново?"
)
RESET_YES = "🗑 Сбросить"
RESET_NO = "Отмена"
RESET_DONE = "🧹 Регистрация сброшена. Жми /start, чтобы начать заново 🌱"
RESET_CANCELLED = "Отменено — всё на месте 👍"
RESET_NOTHING = "Тебя ещё нет в марафоне. Жми /start для регистрации 🌱"


def feedback(steps: int, points: int, upd) -> str:
    """Короткая, «воздушная» обратная связь после зачёта шагов."""
    head = pe("⚡") if steps >= 10_000 else pe("👟")
    lines = [f"{head} <b>+{points} балл(а)</b> · {steps} шагов"]
    if upd.state.current_len > 0:
        lines.append(f"{pe('👣')} Серия: <b>{upd.state.current_len}</b> дн. подряд")
        if upd.milestone == 5:
            lines.append(f"До бонуса +2: ещё {upd.days_to_milestone} дн.")
        elif upd.milestone == 7:
            lines.append(f"До бонуса +4: ещё {upd.days_to_milestone} дн. {pe('🥇')}")
        else:
            lines.append(f"Полная серия недели — бонус +4 твой! {pe('🏆')}")
    return "\n".join(lines)


def weekly_bonus_note(bonus: int) -> str:
    medal = pe("🥇") if bonus >= 4 else pe("🥈")
    return f"{medal} <b>Бонус за серию: +{bonus} балла!</b>\nСтабильность — твоя суперсила 💪"


def render_leaderboard(teams, top, header: str = "Лидерборд", top_title: str = "Участники") -> str:
    """Чистое оформление лидерборда: заголовок и два коротких списка."""
    medals = ["🥇", "🥈", "🥉"]

    def rows(items, key):
        out = []
        for i, it in enumerate(items):
            mark = medals[i] if i < 3 else f"{i + 1}."
            out.append(f"{mark} {escape(it[key] or '—')} — <b>{it['points']}</b>")
        return "\n".join(out) or "— пока пусто —"

    return (
        f"🏆 <b>{escape(header)}</b>\n\n"
        f"<b>Команды</b>\n{rows(teams, 'name')}\n\n"
        f"<b>{escape(top_title)}</b>\n{rows(top, 'full_name' if top and 'full_name' in top[0] else 'name')}"
    )
