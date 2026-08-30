import asyncio
import sys
import os
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_FILE

# Asosiy main.py skriptining yo'li
MAIN_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

async def listen_for_start():
    """Userbot o'chgan vaqtda .userbot start komandasini kutish."""
    # Eng oxirgi sessiya faylini config-dan qayta yuklash
    # config.py dinamik ravishda SESSION_FILE-ni aniqlaydi
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Supervisor: Akkaunt avtorizatsiyadan o'tmagan!")
        await client.disconnect()
        return False
        
    me = await client.get_me()
    me_id = me.id
    print(f"Supervisor: Kutish rejimi faollashdi. Akkaunt: {me.first_name}")
    
    start_received = False
    
    @client.on(events.NewMessage)
    async def handler(event):
        nonlocal start_received
        text = event.text.strip()
        if text == ".userbot start" and (event.sender_id == me_id or event.is_private):
            await event.reply("🟢 Userbot qayta ishga tushirildi. Veb-panel va tozalagich faol.")
            start_received = True
            await client.disconnect()
            
    # Asosiy loop - start_received bo'lguncha kutish
    while not start_received:
        await asyncio.sleep(1)
        
    return True

async def supervisor():
    print("Supervisor ishga tushdi...")
    
    while True:
        print("Supervisor: main.py ishga tushirilmoqda...")
        # main.py skriptini subprocess qilib ishga tushirish
        process = await asyncio.create_subprocess_exec(
            sys.executable, MAIN_SCRIPT,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        
        # main.py tugashini kutish
        exit_code = await process.wait()
        print(f"Supervisor: main.py exited with code {exit_code}")
        
        # Agar exit_code 10 bo'lsa, foydalanuvchi o'chirishni buyurgan (.userbot stop)
        if exit_code == 10:
            print("Supervisor: .userbot stop olindi. Kutish rejimiga o'tilmoqda...")
            # Telegramga ulanib .userbot start kutish
            await listen_for_start()
        else:
            # Boshqa xatolik tufayli o'chgan bo'lsa, 5 soniya kutib qayta yoqish (auto-restart)
            print("Supervisor: kutilmagan o'chish. 5 soniyadan keyin qayta ishga tushadi...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(supervisor())
    except KeyboardInterrupt:
        print("Supervisor to'xtatildi.")
