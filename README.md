# cartelwt

Telegram-бот и Paper/Purpur-плагин для простого whitelist без хаба.

Что делает:
- проверяет подписку на канал;
- ограничивает добавление до 3 ников на один Telegram-аккаунт;
- вызывает команду `swl add <ник>` на сервере;
- хранит привязанные ники в `bot/users.json`.

Команды бота:
- `/start`
- `/swl add <ник>`
- `/my_nicks`

Команда плагина:
- `/tgbridge reload`

Настройка:
- `plugin/src/main/resources/config.yml` - команда `swl add %player%`;
- `bot/config.json` - токен Telegram, адрес `bridge_url` и секрет `bridge_token`.

Запуск бота:

```powershell
python bot.py
```

Если хочешь, я ещё могу сразу собрать это в отдельную папку с готовым `cartelwt-1.0.jar`.
