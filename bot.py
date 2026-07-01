import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
STORAGE_PATH = BASE_DIR / "users.json"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config():
    config = load_json(CONFIG_PATH, {})
    required_keys = ["telegram_bot_token", "bridge_url", "bridge_token"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise RuntimeError("В config.json не заполнены обязательные поля: " + ", ".join(missing))

    config.setdefault("poll_timeout_seconds", 30)
    config.setdefault("required_channel", "@CartelOnline1")
    config.setdefault("max_nicks_per_account", 3)
    return config


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_storage():
    storage = load_json(STORAGE_PATH, {})
    return storage if isinstance(storage, dict) else {}


def save_storage(storage):
    save_json(STORAGE_PATH, storage)


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


def build_help_text(max_nicks_per_account):
    return (
        "Привет.\n\n"
        "Чтобы попасть в whitelist, нужно:\n"
        "1. Быть подписанным на канал @CartelOnline1\n"
        "2. Отправить команду /swl add НИК\n\n"
        f"Лимит: максимум {max_nicks_per_account} ника на один Telegram-аккаунт.\n\n"
        "Команды:\n"
        "/swl add ник\n"
        "/my_nicks"
    )


def extract_add_nickname(text):
    lowered = text.lower()
    if lowered.startswith("/swl add "):
        return text[len("/swl add ") :].strip()
    if lowered == "/swl add":
        raise ValueError("После /swl add нужно написать ник. Пример: /swl add Mirides")
    return None


def handle_add(config, storage, chat_id, telegram_id, text):
    nickname = extract_add_nickname(text)
    if nickname is None:
        return storage

    if not nickname:
        raise ValueError("После /swl add нужно написать ник. Пример: /swl add Mirides")

    current_nicks = storage.get(telegram_id, [])
    lowered_nicks = {nick.lower() for nick in current_nicks}

    if nickname.lower() in lowered_nicks:
        send_message(config["telegram_bot_token"], chat_id, f"Ник {nickname} уже привязан к твоему Telegram.")
        return storage

    if len(current_nicks) >= int(config.get("max_nicks_per_account", 3)):
        send_message(config["telegram_bot_token"], chat_id, "У тебя уже максимум 3 ника на один Telegram-аккаунт.")
        return storage

    try:
        if not is_subscribed(config, telegram_id):
            send_message(
                config["telegram_bot_token"],
                chat_id,
                f"Сначала подпишись на канал {config['required_channel']}, потом попробуй ещё раз.",
            )
            return storage
    except urllib.error.HTTPError as exc:
        send_message(
            config["telegram_bot_token"],
            chat_id,
            f"Не удалось проверить подписку. Добавь бота в канал как администратора. Ошибка: {exc.code}",
        )
        return storage
    except Exception as exc:
        send_message(config["telegram_bot_token"], chat_id, f"Ошибка проверки подписки: {exc}")
        return storage

    try:
        result = request_whitelist(config, telegram_id, nickname)
    except Exception as exc:
        send_message(config["telegram_bot_token"], chat_id, f"Ошибка связи с сервером: {exc}")
        return storage

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
        return storage

    current_nicks.append(nickname)
    storage[telegram_id] = current_nicks
    save_storage(storage)
    send_message(config["telegram_bot_token"], chat_id, f"Готово. Ник {nickname} добавлен в whitelist.")
    return storage


def process_message(config, storage, message):
    token = config["telegram_bot_token"]
    chat_id = message["chat"]["id"]
    telegram_id = str(message["from"]["id"])
    text = message.get("text", "").strip()

    if not text:
        return storage

    if text in {"/start", "/help"}:
        send_message(token, chat_id, build_help_text(int(config.get("max_nicks_per_account", 3))))
        return storage

    if text == "/my_nicks":
        nicks = storage.get(telegram_id, [])
        if not nicks:
            send_message(token, chat_id, "У тебя пока нет привязанных ников.")
        else:
            send_message(token, chat_id, "Твои ники:\n- " + "\n- ".join(nicks))
        return storage

    if text.lower().startswith("/swl add"):
        try:
            return handle_add(config, storage, chat_id, telegram_id, text)
        except ValueError as exc:
            send_message(token, chat_id, str(exc))
            return storage

    send_message(token, chat_id, build_help_text(int(config.get("max_nicks_per_account", 3))))
    return storage


def main():
    config = load_config()
    storage = load_storage()
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
                    storage = process_message(config, storage, message)
        except Exception as exc:
            print(f"Bot loop error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
