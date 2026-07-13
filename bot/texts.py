"""Голос маскота Гроу 🌱 — спортивный, мотивационный. Весь текст здесь.

Формат — HTML (parse_mode=HTML по умолчанию): доступны <b>, <i>, <code>,
<blockquote> (цитата с отступом, как в премиум-ботах) и премиум-эмодзи
<tg-emoji>. Эмодзи оборачиваются через pe() (см. docs/premium-emoji.md).
Правила шлём с disable_web_page_preview.
"""
from html import escape

from bot.premium_emoji import pe

GROW = pe("🌱")

FITBIT_ANDROID = "https://play.google.com/store/apps/details?id=com.fitbit.FitbitMobile&hl=en_US"
FITBIT_IOS = "https://apps.apple.com/us/app/fitbit-health-fitness/id462638897"

WELCOME = (
    f"{pe('👟')}{pe('🔥')}{pe('⚡')} <b>На старт, внимание… ПОЕХАЛИ!</b>\n\n"
    f"Привет! Я Гроу {pe('🌱')} — твой личный тренер на марафоне <b>We Grow Marathon</b>.\n"
    "<blockquote>Здесь мы растём, когда двигаемся: "
    f"каждый шаг {pe('👣')} — это топливо {pe('💪')}\n"
    f"Три недели, тысячи шагов, один общий финиш {pe('🏁')}</blockquote>\n"
    "Погнали — сначала правила 👇"
)

# Полный список правил (все 14 пунктов). Показывается при регистрации.
RULES = (
    f"📋 <b>ПРАВИЛА МАРАФОНА WE GROW</b> {pe('🏃')}{pe('👣')}\n\n"
    "<blockquote><b>1.</b> Участие могут принять все сотрудники подразделения ASR.\n\n"
    "<b>2.</b> Регистрация и распределение по командам — здесь, в боте.\n\n"
    "<b>3.</b> Единое приложение для подсчёта шагов — Google Health (Fitbit):\n"
    f"• Android: {FITBIT_ANDROID}\n"
    f"• iOS: {FITBIT_IOS}\n\n"
    "<b>4.</b> Количество участников в команде — от 8 до 10.\n\n"
    "<b>5.</b> Если команда уже заполнена, сотрудник P&amp;C предложит "
    "распределение в другую команду.\n\n"
    "<b>6.</b> Присоединяясь к марафону, ты обязуешься активно участвовать "
    f"и дойти до финиша {pe('🏁')}\n\n"
    "<b>7.</b> Период проведения: с 17 июля по 7 августа включительно.\n\n"
    f"<b>8.</b> Каждую неделю публикуется лидерборд участников и команд {pe('📊')}</blockquote>\n"
    f"{pe('🎯')} <b>Баллы за день (правило 9):</b>\n"
    "<blockquote>• 5 000 – 9 999 шагов = <b>1 балл</b>\n"
    "• 10 000 – 14 999 шагов = <b>2 балла</b>\n"
    "• 15 000 – 30 000 шагов = <b>3 балла</b></blockquote>\n"
    f"{pe('🥇')} <b>Бонус за серию по итогам недели (правило 10):</b>\n"
    "<blockquote>• 5 дней подряд по 10 000+ = <b>+2 балла</b>\n"
    "• 7 дней подряд по 10 000+ = <b>+4 балла</b></blockquote>\n"
    "<blockquote><b>11.</b> Шаги фиксируй каждый день до 23:55 — скрин экрана "
    "с датой и количеством шагов за текущий день.\n\n"
    "<b>12.</b> В воскресенье до 23:55 отправляй недельную сводку по шагам "
    "для бонуса за серию.\n\n"
    "<b>13.</b> Сотрудник P&amp;C может запросить скриншот с результатами "
    "в течение дня для проверки.\n\n"
    "<b>14.</b> При выявлении нарушений участник дисквалифицируется, "
    "а его результаты не учитываются в командном зачёте.</blockquote>\n"
    f"Готов выложиться на полную и дойти до финиша? {pe('💪')}{pe('🔥')}"
)

CONSENT_BUTTON = "Принимаю правила и иду до конца 🏁"
ASK_NAME = f"{pe('🔥')} Отлично! Как к тебе обращаться? Напиши своё <b>ФИО</b>."
ASK_ASR = "Подтверди: ты из подразделения <b>ASR</b>? 👇"
FIT_LINKS = (
    f"{pe('👟')} <b>Поставь Fitbit</b> (Google Health), если ещё нет — им считаем шаги:\n"
    "<blockquote>"
    f"• Android: {FITBIT_ANDROID}\n"
    f"• iOS: {FITBIT_IOS}</blockquote>"
)
ASK_TEAM = f"{pe('⚽️')} <b>Выбирай команду</b> — вместе бежать веселее! Ваш общий сад ждёт:"
RANDOM_TEAM = "Определите меня в команду 🎲"

ONBOARDED = (
    f"{pe('🎉')} <b>Ты в игре!</b> Команда <b>{{team}}</b> пополнилась бойцом {pe('💪')}\n"
    "<blockquote>Каждый день жми «👟 Шаги за сегодня» или просто кидай скрин с шагами.\n"
    f"Первый шаг — самый важный. Вперёд, к финишу! {pe('🎯')}{pe('🏁')}</blockquote>"
)

STEPS_BUTTON = "👟 Шаги за сегодня"
MENU_PROGRESS = "📊 Мой прогресс"
MENU_BOARD = "🏆 Лидерборд"
MENU_RULES = "📋 Правила"
MENU_HELP = "❓ Помощь"
MENU_ADMIN = "🛠 Админка"

HELP = (
    f"{pe('👣')} <b>Как участвовать</b>\n"
    "<blockquote>"
    "• Каждый день до 23:55 жми «👟 Шаги за сегодня» и пришли число/скрин из Fitbit.\n"
    "• Баллы: 5к=1, 10к=2, 15к+=3. Серия 10 000+ даёт недельный бонус.\n"
    "• «📊 Мой прогресс» и «🏆 Лидерборд» — открывают приложение с деталями.\n"
    "• «📋 Правила» — полный список правил."
    "</blockquote>\n"
    "Команды: /start, /rules, /help, /reset"
)

ADMIN_PANEL = f"🛠 <b>Админ-панель P&amp;C</b>\nВыбери действие {pe('👑')}"
ASK_STEPS_PHOTO = f"{pe('📸')} Кидай скрин с шагами из <b>Fitbit</b> или просто напиши число."
CONFIRM_STEPS = "👀 Вижу <b>{steps}</b> шагов — всё верно?"
ASK_MANUAL = f"{pe('🤔')} Не разобрал число. Напиши его цифрами (например, <code>12340</code>)."
ALREADY_TODAY = (
    f"{pe('✅')} Сегодня шаги уже в зачёте: <b>{{steps}}</b>. "
    f"Отдыхай, спортсмен — до завтра! {pe('🌙')}"
)

REMINDER_2100 = (
    f"{pe('⏰')}{pe('⚡')} <b>Эй, чемпион!</b> День почти закрыт, а твои шаги ещё не в зачёте.\n"
    "<blockquote>Даже короткая прогулка перед сном — это баллы "
    f"{pe('💪')} Жми «👟 Шаги за сегодня»!</blockquote>"
)

WEEKLY_SUMMARY_REMINDER = (
    f"{pe('📊')} <b>Воскресенье — время недельной сводки!</b> {pe('🏁')}\n"
    "<blockquote>Пришли сводку по шагам из Fitbit за неделю до 23:55, "
    f"чтобы забрать бонус за серию {pe('🔥')}</blockquote>"
)

RESET_CONFIRM = (
    "⚠️ <b>Сброс регистрации</b> сотрёт <b>всё</b>: команду, серию, шаги и баллы.\n"
    "<blockquote>Данные не восстановить.</blockquote>\nТочно начать заново?"
)
RESET_YES = "Да, сбросить 🗑"
RESET_NO = "Отмена"
RESET_DONE = f"{pe('🗑')} <b>Готово!</b> Регистрация сброшена. Жми /start, чтобы начать заново {pe('🌱')}"
RESET_CANCELLED = f"Отменено — всё на месте {pe('👍')}"
RESET_NOTHING = f"Тебя ещё нет в марафоне. Жми /start, чтобы зарегистрироваться {pe('🌱')}"


def feedback(steps: int, points: int, upd) -> str:
    """Мгновенная спортивная обратная связь после зачёта шагов."""
    head = pe("⚡") if steps >= 10_000 else pe("👣")
    title = f"{head} <b>Засчитано: {steps} шагов = {points} балл(а)!</b>"
    if upd.state.current_len > 0:
        body = f"{pe('👣')} Серия: <b>{upd.state.current_len}</b> дн. подряд по 10 000+"
        if upd.milestone == 5:
            body += f"\nЕщё {upd.days_to_milestone} дн. — и бонус <b>+2</b> в воскресенье {pe('👏')}"
        elif upd.milestone == 7:
            body += f"\nЕщё {upd.days_to_milestone} дн. — и максимальный бонус <b>+4</b> {pe('🥇')}"
        else:
            body += f"\nПолная серия недели — бонус <b>+4</b> твой! {pe('👑')}"
    else:
        body = f"Серия обнулилась — завтра 10 000+ и разгоняемся заново {pe('⚡')}"
    return f"{title}\n<blockquote>{body}</blockquote>"


def render_leaderboard(teams, top, header: str = "Лидерборд", top_title: str = "Участники") -> str:
    """Единое оформление лидерборда: жирный заголовок + две цитаты-блока."""
    team_rows = []
    for i, t in enumerate(teams, 1):
        prefix = pe("👑") if i == 1 else f"{i}."
        team_rows.append(f"{prefix} {escape(t['name'])} — <b>{t['points']}</b>")
    top_rows = []
    for i, p in enumerate(top, 1):
        prefix = pe("🥇") if i == 1 else f"{i}."
        top_rows.append(f"{prefix} {escape(p['full_name'] or '—')} — <b>{p['points']}</b>")
    return (
        f"{pe('📊')} <b>{header}</b>\n"
        f"<blockquote>{pe('🏆')} <b>Команды</b>\n" + "\n".join(team_rows) + "</blockquote>\n"
        f"<blockquote>{pe('👣')} <b>{escape(top_title)}</b>\n" + "\n".join(top_rows) + "</blockquote>"
    )


def weekly_bonus_note(bonus: int) -> str:
    medal = pe("🥇") if bonus >= 4 else pe("🥈")
    return (
        f"{medal} <b>Бонус за серию недели: +{bonus} балла!</b>\n"
        f"<blockquote>Стабильность — твоя суперсила {pe('👏')}{pe('💪')} Так держать!</blockquote>"
    )
