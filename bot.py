import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
USERS_PATH = BASE_DIR / "users.json"
AUDIT_PATH = BASE_DIR / "audit.json"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_config():
    config = load_json(CONFIG_PATH, {})
    required_keys = ["telegram_bot_token", "bridge_url", "bridge_token"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise RuntimeError("В config.json не заполнены обязательные поля: " + ", ".join(missing))

    config.setdefault("poll_timeout_seconds", 30)
    config.setdefault("required_channel", "@CartelOnline1")
    config.setdefault("max_nicks_per_account", 3)
    config.setdefault("admin_ids", [])
    return config


def load_storage():
    storage = load_json(USERS_PATH, {})
    return storage if isinstance(storage, dict) else {}


def save_storage(storage):
    save_json(USERS_PATH, storage)


def load_audit():
    audit = load_json(AUDIT_PATH, [])
    return audit if isinstance(audit, list) else []


def save_audit(audit):
    save_json(AUDIT_PATH, audit)


def telegram_request(token, method, params=None):
    params = params or {}
    data = urllib.parse.urlencode(params).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", f"Telegram API error in {method}"))
    return payload["result"]


def send_message(token, chat_id, text):
    telegram_request(token, "sendMessage", {"chat_id": str(chat_id), "text": text})


def request_whitelist(config, telegram_id, nickname):
    payload = urllib.parse.urlencode(
        {
            "token": config["bridge_token"],
            "telegram_id": str(telegram_id),
            "nickname": nickname,
        }
    ).encode("utf-8")
    request = urllib.request.Request(config["bridge_url"], data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def is_subscribed(config, telegram_id):
    result = telegram_request(
        config["telegram_bot_token"],
        "getChatMember",
        {
            "chat_id": config["required_channel"],
            "user_id": str(telegram_id),
        },
    )
    status = result.get("result", {}).get("status", "")
    return status in {"creator", "administrator", "member"}


def get_display_name(message_from):
    username = str(message_from.get("username", "")).strip()
    if username:
        return f"@{username}"

    first_name = str(message_from.get("first_name", "")).strip()
    last_name = str(message_from.get("last_name", "")).strip()
    full_name = " ".join(part for part in [first_name, last_name] if part)
    return full_name or str(message_from.get("id", "unknown"))


def is_admin(config, telegram_id):
    admin_ids = {str(item) for item in config.get("admin_ids", [])}
    return str(telegram_id) in admin_ids


def notify_admins(config, text):
    admins = [str(item) for item in config.get("admin_ids", [])]
    for admin_id in admins:
        try:
            send_message(config["telegram_bot_token"], admin_id, text)
        except Exception:
            continue


def build_help_text(max_nicks_per_account, admin=False):
    text = (
        "Привет.\n\n"
        "Чтобы попасть в whitelist, нужно:\n"
        "1. Быть подписанным на канал @CartelOnline1\n"
        "2. Отправить команду /add НИК\n\n"
        f"Лимит: максимум {max_nicks_per_account} ника на один Telegram-аккаунт.\n\n"
        "Команды:\n"
        "/add ник\n"
        "/nicks"
    )

    if admin:
        text += (
            "\n\nАдмин-команды:\n"
            "/stats\n"
            "/who ник"
        )

    return text


def parse_add_nickname(text):
    lowered = text.lower()
    if lowered.startswith("/add "):
        return text[5:].strip()
    if lowered == "/add":
        raise ValueError("После /add нужно написать ник. Пример: /add Mirides")
    return None


def find_user_nick(storage, nickname):
    target = nickname.lower()
    for telegram_id, nicks in storage.items():
        if not isinstance(nicks, list):
            continue
        for item in nicks:
            if str(item).lower() == target:
                return str(telegram_id)
    return None


def count_total_nicks(storage):
    total = 0
    for nicks in storage.values():
        if isinstance(nicks, list):
            total += len(nicks)
    return total


def format_audit_entry(entry):
    nickname = entry.get("nickname", "?")
    added_by = entry.get("added_by_name") or entry.get("added_by_id") or "unknown"
    at = entry.get("added_at", "?")
    owner = entry.get("telegram_id", "?")
    return f"- {nickname} | added_by: {added_by} | owner: {owner} | at: {at}"


def handle_add(config, storage, audit, chat_id, telegram_id, message_from, text):
    nickname = parse_add_nickname(text)
    if nickname is None:
        return storage, audit

    if not nickname:
        raise ValueError("После /add нужно написать ник. Пример: /add Mirides")

    current_nicks = storage.get(telegram_id, [])
    lowered_nicks = {str(nick).lower() for nick in current_nicks}

    if nickname.lower() in lowered_nicks:
        send_message(config["telegram_bot_token"], chat_id, f"Ник {nickname} уже привязан к твоему Telegram.")
        return storage, audit

    if len(current_nicks) >= int(config.get("max_nicks_per_account", 3)):
        send_message(config["telegram_bot_token"], chat_id, "У тебя уже максимум 3 ника на один Telegram-аккаунт.")
        return storage, audit

    try:
        if not is_subscribed(config, telegram_id):
            send_message(
                config["telegram_bot_token"],
                chat_id,
                f"Сначала подпишись на канал {config['required_channel']}, потом попробуй ещё раз.",
            )
            return storage, audit
    except urllib.error.HTTPError as exc:
        send_message(
            config["telegram_bot_token"],
            chat_id,
            f"Не удалось проверить подписку. Добавь бота в канал как администратора. Ошибка: {exc.code}",
        )
        return storage, audit
    except Exception as exc:
        send_message(config["telegram_bot_token"], chat_id, f"Ошибка проверки подписки: {exc}")
        return storage, audit

    try:
        result = request_whitelist(config, telegram_id, nickname)
    except Exception as exc:
        send_message(config["telegram_bot_token"], chat_id, f"Ошибка связи с сервером: {exc}")
        return storage, audit

    if not result.get("ok"):
        error = result.get("error", "unknown_error")
        if error == "invalid_nick":
            send_message(
                config["telegram_bot_token"],
                chat_id,
                "Неверный ник. Разрешены только Minecraft-ники 3-16 символов: буквы, цифры и _.",
            )
        else:
            send_message(config["telegram_bot_token"], chat_id, f"Игрок не добавлен: {error}")
        return storage, audit

    current_nicks.append(nickname)
    storage[telegram_id] = current_nicks
    save_storage(storage)

    entry = {
        "nickname": nickname,
        "telegram_id": telegram_id,
        "added_by_id": telegram_id,
        "added_by_name": get_display_name(message_from),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    audit.append(entry)
    save_audit(audit)

    send_message(config["telegram_bot_token"], chat_id, f"Готово. Ник {nickname} добавлен в whitelist.")
    notify_admins(
        config,
        "Новый ник добавлен:\n"
        f"ник: {nickname}\n"
        f"добавил: {entry['added_by_name']} ({entry['added_by_id']})\n"
        f"владелец: {telegram_id}\n"
        f"всего ников у владельца: {len(current_nicks)}\n"
        f"всего ников в базе: {count_total_nicks(storage)}",
    )
    return storage, audit


def handle_nicks(config, storage, chat_id, telegram_id):
    nicks = storage.get(telegram_id, [])
    if not nicks:
        send_message(config["telegram_bot_token"], chat_id, "У тебя пока нет привязанных ников.")
    else:
        send_message(config["telegram_bot_token"], chat_id, "Твои ники:\n- " + "\n- ".join(str(nick) for nick in nicks))


def handle_stats(config, storage, audit, chat_id):
    total_users = len([key for key, value in storage.items() if isinstance(value, list)])
    total_nicks = count_total_nicks(storage)
    recent = audit[-5:]
    lines = [
        "Статистика whitelist:",
        f"Пользователей: {total_users}",
        f"Всего ников: {total_nicks}",
        "Последние добавления:",
    ]
    if recent:
        lines.extend(format_audit_entry(entry) for entry in recent)
    else:
        lines.append("- пока пусто")
    send_message(config["telegram_bot_token"], chat_id, "\n".join(lines))


def handle_who(config, audit, chat_id, text):
    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        send_message(config["telegram_bot_token"], chat_id, "Пример: /who Mirides")
        return

    nickname = parts[1].strip()
    matches = [entry for entry in audit if str(entry.get("nickname", "")).lower() == nickname.lower()]
    if not matches:
        send_message(config["telegram_bot_token"], chat_id, f"Ник {nickname} не найден в журнале.")
        return

    entry = matches[-1]
    send_message(
        config["telegram_bot_token"],
        chat_id,
        "Информация по нику:\n"
        f"ник: {entry.get('nickname', nickname)}\n"
        f"добавил: {entry.get('added_by_name', 'unknown')} ({entry.get('added_by_id', 'unknown')})\n"
        f"владелец: {entry.get('telegram_id', 'unknown')}\n"
        f"добавлен: {entry.get('added_at', 'unknown')}",
    )


def process_message(config, storage, audit, message):
    token = config["telegram_bot_token"]
    chat_id = message["chat"]["id"]
    telegram_id = str(message["from"]["id"])
    text = message.get("text", "").strip()
    message_from = message.get("from", {})
    admin = is_admin(config, telegram_id)

    if not text:
        return storage, audit

    if text in {"/start", "/help"}:
        send_message(token, chat_id, build_help_text(int(config.get("max_nicks_per_account", 3)), admin=admin))
        return storage, audit

    if text == "/nicks":
        handle_nicks(config, storage, chat_id, telegram_id)
        return storage, audit

    if text.lower().startswith("/add"):
        try:
            return handle_add(config, storage, audit, chat_id, telegram_id, message_from, text)
        except ValueError as exc:
            send_message(token, chat_id, str(exc))
            return storage, audit

    if admin and text == "/stats":
        handle_stats(config, storage, audit, chat_id)
        return storage, audit

    if admin and text.lower().startswith("/who "):
        handle_who(config, audit, chat_id, text)
        return storage, audit

    if admin and text == "/stats all":
        handle_stats(config, storage, audit, chat_id)
        return storage, audit

    send_message(token, chat_id, build_help_text(int(config.get("max_nicks_per_account", 3)), admin=admin))
    return storage, audit


def main():
    config = load_config()
    storage = load_storage()
    audit = load_audit()
    token = config["telegram_bot_token"]
    offset = 0

    while True:
        try:
            response = telegram_request(
                token,
                "getUpdates",
                {"timeout": int(config["poll_timeout_seconds"]), "offset": offset},
            )
            for update in response.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                if message:
                    storage, audit = process_message(config, storage, audit, message)
        except Exception as exc:
            print(f"Bot loop error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
