import asyncio
import os
import sys
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH

BASE_DIR = Path(__file__).resolve().parent

async def main():
    print("========================================")
    print("  Telegram Userbot Login / Avtorizatsiya  ")
    print("========================================")
    
    phone = input("\nTelefon raqamingizni kiriting (+998...): ").strip()
    if not phone:
        print("[ERROR] Telefon raqami bo'sh bo'lmasligi kerak!")
        return

    # Clean phone number for filename
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    session_name = str(BASE_DIR / f"session_{clean_phone}")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"\n[OK] Ushbu akkauntga kirib turibsiz: {me.first_name} (@{me.username}) | ID: {me.id}")
        await client.disconnect()
        return

    print(f"[{phone}] raqamiga tasdiqlash kodi so'ralmoqda...")
    try:
        await client.send_code_request(phone)
    except Exception as e:
        print(f"[ERROR] Kod so'rash xatoligi: {e}")
        await client.disconnect()
        return
        
    code = input("Telegram-ga kelgan 5 xonali kodni kiriting: ").strip()
    
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        password = input("2FA Parolini (Two-Step Verification Password) kiriting: ")
        await client.sign_in(password=password)
    except Exception as e:
        print(f"[ERROR] Xatolik yuz berdi: {e}")
        # Clean up failed session file
        await client.disconnect()
        try:
            os.remove(f"{session_name}.session")
        except:
            pass
        return

    me = await client.get_me()
    print(f"\n[SUCCESS] Muvaffaqiyatli ulandi! Akkaunt: {me.first_name} (@{me.username}) | ID: {me.id}")
    print(f"Sessiya fayli saqlandi: {session_name}.session")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
