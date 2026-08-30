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
    print("  Telegram Userbot Login / Авторизация  ")
    print("========================================")
    
    phone = input("\nТелефон нөміріңізді енгізіңіз (+7700...): ").strip()
    if not phone:
        print("[ERROR] Телефон нөмірі бос болмауы керек!")
        return

    # Clean phone number for filename
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    session_name = str(BASE_DIR / f"session_{clean_phone}")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"\n[OK] Бұл аккаунтқа кіріп тұрсыз: {me.first_name} (@{me.username}) | ID: {me.id}")
        await client.disconnect()
        return

    print(f"[{phone}] нөміріне растау коды сұралуда...")
    try:
        await client.send_code_request(phone)
    except Exception as e:
        print(f"[ERROR] Код сұрау қатесі: {e}")
        await client.disconnect()
        return
        
    code = input("Telegram-ға келген 5 сандық кодты енгізіңіз: ").strip()
    
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        password = input("2FA Құпиясөзін (Two-Step Verification Password) енгізіңіз: ")
        await client.sign_in(password=password)
    except Exception as e:
        print(f"[ERROR] Қате орын алды: {e}")
        # Clean up failed session file
        await client.disconnect()
        try:
            os.remove(f"{session_name}.session")
        except:
            pass
        return

    me = await client.get_me()
    print(f"\n[ЖЕТІСТІК] Сәтті қосылды! Аккаунт: {me.first_name} (@{me.username}) | ID: {me.id}")
    print(f"Сессия файлы сақталды: {session_name}.session")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
