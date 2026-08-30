import asyncio
import os
import sys
import time
import qrcode
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH

BASE_DIR = Path(__file__).resolve().parent

async def main():
    print("==================================================")
    print("  Telegram QR-код арқылы кіру (QR Login)          ")
    print("==================================================")
    print("1. Телефоныңыздан Telegram-ды ашыңыз")
    print("2. Настройки (Баптаулар) -> Устройства (Құрылғылар)")
    print("3. 'Подключить устройство' (Құрылғы қосу) батырмасын басыңыз")
    print("4. Төмендегі QR-кодты сканерлеңіз:\n")

    timestamp = int(time.time())
    session_name = str(BASE_DIR / f"session_qr_{timestamp}")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()

    qr_login = await client.qr_login()
    
    # ASCII QR code
    qr = qrcode.QRCode()
    qr.add_data(qr_login.url)
    qr.print_ascii(invert=True)
    
    print(f"\nСілтеме түрінде: {qr_login.url}\n")
    print("QR-код сканерленуін күтуде (60 секунд)...")

    authorized = False
    try:
        user = await qr_login.wait(timeout=60)
        print(f"\n[ЖЕТІСТІК] Сәтті кірдіңіз: {user.first_name} (@{user.username}) | ID: {user.id}")
        authorized = True
    except SessionPasswordNeededError:
        print("\n[2FA] Аккаунтта 2FA құпиясөз орнатылған.")
        pw = input("2FA Құпиясөзін енгізіңіз: ").strip()
        user = await client.sign_in(password=pw)
        print(f"\n[ЖЕТІСТІК] Сәтті кірдіңіз: {user.first_name} (@{user.username}) | ID: {user.id}")
        authorized = True
    except Exception as e:
        print(f"\n[ҚАТЕ немесе УАҚЫТ АЯҚТАЛДЫ]: {e}")
    finally:
        await client.disconnect()
        # If QR login failed/timed out, remove the unused session file
        if not authorized:
            try:
                os.remove(f"{session_name}.session")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
