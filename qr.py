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
    print("  Telegram QR-kod orqali kirish (QR Login)          ")
    print("==================================================")
    print("1. Telefoningizdan Telegram-ni oching")
    print("2. Sozlamalar (Settings) -> Qurilmalar (Devices)")
    print("3. 'Qurilmani ulash' (Link Desktop Device) tugmasini bosing")
    print("4. Quyidagi QR-kodni skanerlang:\n")

    timestamp = int(time.time())
    session_name = str(BASE_DIR / f"session_qr_{timestamp}")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()

    qr_login = await client.qr_login()
    
    # ASCII QR code
    qr = qrcode.QRCode()
    qr.add_data(qr_login.url)
    qr.print_ascii(invert=True)
    
    print(f"\nHavola shaklida: {qr_login.url}\n")
    print("QR-kod skanerlanishini kutmoqda (60 soniya)...")

    authorized = False
    try:
        user = await qr_login.wait(timeout=60)
        print(f"\n[SUCCESS] Muvaffaqiyatli kirdingiz: {user.first_name} (@{user.username}) | ID: {user.id}")
        authorized = True
    except SessionPasswordNeededError:
        print("\n[2FA] Akkauntda 2FA paroli o'rnatilgan.")
        pw = input("2FA parolini kiriting: ").strip()
        user = await client.sign_in(password=pw)
        print(f"\n[SUCCESS] Muvaffaqiyatli kirdingiz: {user.first_name} (@{user.username}) | ID: {user.id}")
        authorized = True
    except Exception as e:
        print(f"\n[XATOLIK Yoki VAQT TUGADI]: {e}")
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
