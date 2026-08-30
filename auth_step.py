import asyncio
import sys
import json
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, SESSION_FILE, BASE_DIR

AUTH_STATE_FILE = BASE_DIR / "auth_state.json"

def get_client():
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def send_code(phone: str):
    """Tasdiqlash kodini yuborish."""
    client = get_client()
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        state = {
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash
        }
        with open(AUTH_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        print(f"[OK] Tasdiqlash kodi {phone} raqamiga yuborildi!")
        print("Telegram-ga kelgan 5 xonali kodni kiriting.")
    except Exception as e:
        print(f"[ERROR] Kod so'rashda xatolik: {e}")
    finally:
        await client.disconnect()

async def verify_code(code: str, password: str = None):
    """Kodni tekshirish va kirish."""
    if not AUTH_STATE_FILE.exists():
        print("[ERROR] Avval send_code bajarilishi kerak!")
        return

    with open(AUTH_STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    phone = state["phone"]
    phone_code_hash = state["phone_code_hash"]

    client = get_client()
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                print("[2FA_REQUIRED] Akkauntda 2FA yoqilgan! 2FA parolingizni kiriting.")
                return
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"[SUCCESS] Muvaffaqiyatli ulandi! Akkaunt: {me.first_name} (@{me.username}) | ID: {me.id}")
        if AUTH_STATE_FILE.exists():
            AUTH_STATE_FILE.unlink()
    except Exception as e:
        print(f"[ERROR] Kirishda xatolik: {e}")
    finally:
        await client.disconnect()

async def verify_2fa(password: str):
    """2FA parolini tekshirish."""
    client = get_client()
    await client.connect()
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        print(f"[SUCCESS] Muvaffaqiyatli ulandi! Akkaunt: {me.first_name} (@{me.username}) | ID: {me.id}")
        if AUTH_STATE_FILE.exists():
            AUTH_STATE_FILE.unlink()
    except Exception as e:
        print(f"[ERROR] 2FA xatoligi: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Foydalanish: python auth_step.py [send_code <phone> | verify <code> [2fa_pass] | 2fa <pass>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "send_code":
        phone = sys.argv[2]
        asyncio.run(send_code(phone))
    elif cmd == "verify":
        code = sys.argv[2]
        pw = sys.argv[3] if len(sys.argv) > 3 else None
        asyncio.run(verify_code(code, pw))
    elif cmd == "2fa":
        pw = sys.argv[2]
        asyncio.run(verify_2fa(pw))
