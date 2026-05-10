#!/usr/bin/env python3
"""
Telegram diagnostic and test script.

Usage:
    python scripts/test_telegram.py            # check token + show recent chats
    python scripts/test_telegram.py --send     # also send a test message
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests


def _load_credentials() -> tuple[str, str]:
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        # Simple manual parse — avoids requiring python-dotenv
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def check_bot(token: str) -> bool:
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getMe",
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        bot = data["result"]
        print(f"  Bot OK: @{bot['username']} (id={bot['id']})")
        return True
    print(f"  ERROR: {data.get('description', 'unknown')}")
    print("  -> El token es incorrecto o el bot ha sido eliminado.")
    return False


def get_recent_chats(token: str) -> list[dict]:
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"limit": 20, "timeout": 0},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        print(f"  getUpdates error: {data.get('description')}")
        return []

    chats = {}
    for update in data["result"]:
        msg = update.get("message") or update.get("channel_post") or update.get("my_chat_member")
        if msg:
            chat = msg.get("chat", {})
            cid = str(chat.get("id", ""))
            if cid and cid not in chats:
                chats[cid] = {
                    "id": cid,
                    "type": chat.get("type"),
                    "title": chat.get("title") or chat.get("username") or chat.get("first_name", ""),
                }
    return list(chats.values())


def send_test_message(token: str, chat_id: str) -> bool:
    from weather_station.sender import TelegramSender
    s = TelegramSender(bot_token=token, chat_id=chat_id)
    return s.send_text(
        "<b>Estación meteorológica</b>\n"
        "Mensaje de prueba — la conexión con Telegram funciona correctamente."
    )


def main():
    parser = argparse.ArgumentParser(description="Telegram diagnostic for weather station")
    parser.add_argument("--send", action="store_true", help="Send a test text message")
    args = parser.parse_args()

    token, chat_id = _load_credentials()

    print("=== 1. Verificando token del bot ===")
    if not token:
        print("  ERROR: TELEGRAM_BOT_TOKEN no está definido en .env ni en el entorno.")
        sys.exit(1)
    if not check_bot(token):
        sys.exit(1)

    print("\n=== 2. Chats recientes (getUpdates) ===")
    chats = get_recent_chats(token)
    if chats:
        print("  Chats encontrados:")
        for c in chats:
            marker = " <-- usa este" if c["id"] == chat_id else ""
            print(f"    id={c['id']:>15}  type={c['type']:<12}  name={c['title']}{marker}")
    else:
        print("  No hay mensajes recientes.")
        print("  -> Abre Telegram, busca tu bot y envíale /start")
        print("     Luego vuelve a ejecutar este script.")

    print(f"\n=== 3. Chat ID configurado: {chat_id or '(vacío)'} ===")
    if not chat_id:
        print("  ERROR: TELEGRAM_CHAT_ID no está definido en .env")
        sys.exit(1)

    if args.send:
        print("\n=== 4. Enviando mensaje de prueba ===")
        ok = send_test_message(token, chat_id)
        if ok:
            print("  Mensaje enviado correctamente.")
        else:
            print("  ERROR al enviar. Comprueba el chat_id con la lista del paso 2.")
            sys.exit(1)
    else:
        print("\n  Ejecuta con --send para enviar un mensaje de prueba:")
        print(f"  python scripts/test_telegram.py --send")


if __name__ == "__main__":
    main()
