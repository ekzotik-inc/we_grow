# Деплой на Render (GitHub → Render, без локального запуска)

Всё в облаке: код берётся с GitHub, бот и база работают на Render. На вашем
компьютере ничего запускать не нужно.

## Что уже есть

- **База** — `test_bd` (PostgreSQL, Oregon). Создавать новую не нужно, наши
  таблицы лягут в отдельную схему `wegrow` и не тронут остальное.
- **Код** — в этом репозитории, ветка `claude/laughing-babbage-2tyt1p`.

## Что понадобится под рукой (3 значения)

1. **Internal Database URL** базы `test_bd`
   Dashboard → `test_bd` → блок **Connections** → строка **Internal Database URL**
   (вид `postgresql://...@dpg-xxxx-a/test_bd_a1wf`, без домена — так и надо, бот
   внутри Render).
2. **BOT_TOKEN** — токен бота от **@BotFather** в Telegram (команда `/newbot`).
3. **ADMIN_IDS** — ваш Telegram ID (узнать: напишите **@userinfobot**, он пришлёт
   число).

## Пошагово

1. https://dashboard.render.com → **New +** → **Blueprint**.
2. Выберите репозиторий `ekzotik-inc/we_grow` и ветку
   `claude/laughing-babbage-2tyt1p`.
3. Render прочитает [`render.yaml`](../render.yaml) и покажет сервис
   **wegrow-bot** (worker). Нажмите **Apply**.
4. Откройте сервис **wegrow-bot** → вкладка **Environment** → впишите 3 значения:
   - `DATABASE_URL` = Internal Database URL из шага выше
   - `BOT_TOKEN` = токен от BotFather
   - `ADMIN_IDS` = ваш Telegram ID
   Сохраните — сервис пересоберётся сам.
5. Вкладка **Logs**: дождитесь строк `БД подключена, схема применена` и
   `Старт polling`. Значит бот жив.
6. Откройте бота в Telegram, отправьте **/start**.

## Тарифы

- Бот-воркер (`plan: starter`) — **платный** (~$7/мес): у Render нет бесплатного
  тарифа для постоянных воркеров.
- База `test_bd` пока может оставаться **free**. Апгрейд базы: Dashboard →
  `test_bd` → Settings → Change Plan (строка подключения не меняется).

## Если что-то не так

- В логах `BOT_TOKEN не задан` → не заполнена переменная BOT_TOKEN (шаг 4).
- В логах ошибка подключения к БД → проверьте, что вписан **Internal** URL (не
  External) и что регион воркера — Oregon (как у базы). Оба условия уже заданы в
  `render.yaml`.
- Пришлите текст ошибки из **Logs** — разберём.

## Безопасность

Не публикуйте `DATABASE_URL` и `BOT_TOKEN` в чатах и коммитах — они вводятся
только в дашборде Render (поля `sync: false`, в репозиторий не попадают). Если
пароль базы где-то засветился — сделайте `test_bd` → **Reset Password**, в
дашборде обновится Internal URL, впишите новый в переменную.
