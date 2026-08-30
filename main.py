import asyncio
import os
import sys
import time
import base64
import io
import qrcode
from datetime import datetime
import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UserNotParticipantError, SessionPasswordNeededError
from telethon.tl.types import ChannelParticipantsAdmins, ChatAdminRights
from telethon.tl.functions.channels import EditAdminRequest, InviteToChannelRequest
from config import API_ID, API_HASH, SESSION_FILE, BOT_TOKENS

# Get BASE_DIR
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# System Startup Time
START_TIME = time.time()

# Global variables
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
me_id = None
active_channel = None
blocking_active = False

loaded_bots = []   # List of dicts: {'token': ..., 'id': ..., 'username': ...}
bot_states = {}    # Dict: {token: {'queue': [], 'banned_count': 0, 'start_time': None, 'is_banned_until': 0, 'username': ..., 'id': ...}}
assigned_user_ids = set()
admin_ids = set()
CONTROL_CHAT_ID = -1003930058805  # Default control chat ID, will be updated dynamically

# Session for aiohttp
http_session = None

# Running tasks references
bot_tasks = []
scraper_task = None

# Web QR Login States
qr_client = None
qr_login_instance = None
qr_state = {"status": "idle", "qr_base64": None, "error": None}

# Initialize FastAPI App
app = FastAPI(title="Telegram Channel Cleaner Web Panel")


async def init_bots():
    """Load and verify bot tokens from config.py."""
    global loaded_bots, bot_states, http_session
    
    tokens = BOT_TOKENS
    loaded_bots = []
    bot_states = {}
    
    if not tokens:
        print("⚠️ config.py файлында BOT_TOKENS бос!")
        return
        
    print(f"🤖 config.py ішінен {len(tokens)} токен табылды. Тексерілуде...")
    
    for token in tokens:
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            async with http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        res = data["result"]
                        bot_info = {
                            'token': token,
                            'id': res['id'],
                            'username': res['username']
                        }
                        loaded_bots.append(bot_info)
                        bot_states[token] = {
                            'queue': [],
                            'banned_count': 0,
                            'start_time': None,
                            'is_banned_until': 0,
                            'username': res['username'],
                            'id': res['id']
                        }
                        print(f"✅ Бот сәтті қосылды: @{res['username']} (ID: {res['id']})")
                    else:
                        print(f"❌ Токен жарамсыз (API қатесі): {token}")
                else:
                    print(f"❌ Токен жарамсыз (HTTP {resp.status}): {token}")
        except Exception as e:
            print(f"❌ Токенді тексеру кезінде қате ({token}): {e}")


def format_duration(seconds):
    """Format duration in seconds to human-readable Kazakh format."""
    seconds = int(seconds)
    if seconds <= 0:
        return "0 секунд"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} сағат")
    if minutes > 0:
        parts.append(f"{minutes} минут")
    if secs > 0 or not parts:
        parts.append(f"{secs} секунд")
    return " ".join(parts)


async def send_bot_message(token, text):
    """Send message to control chat using bot token and sleep 5s."""
    global CONTROL_CHAT_ID, http_session
    if not http_session:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": CONTROL_CHAT_ID,
        "text": text
    }
    try:
        async with http_session.post(url, json=payload) as resp:
            if resp.status != 200:
                print(f"Error sending bot message: {await resp.text()}")
    except Exception as e:
        print(f"Failed to send bot message: {e}")
    finally:
        # "жазып болып демалып 5сек қаита істеу керек"
        await asyncio.sleep(5)


def parse_chat_id(input_str):
    """Normalize telegram chat/channel ID format."""
    input_str = input_str.strip()
    if "t.me/" in input_str:
        input_str = input_str.split("t.me/")[-1].split("/")[0]
        if not input_str.startswith("@") and not input_str.replace("-", "").isdigit():
            input_str = "@" + input_str
            
    if input_str.replace("-", "").isdigit():
        val = int(input_str)
        if val > 0:
            s_val = str(val)
            if s_val.startswith("100"):
                return -val
            else:
                return int(f"-100{s_val}")
        return val
    return input_str


async def bot_worker(bot_info):
    """Ban loop for a single bot client."""
    global blocking_active, active_channel, bot_states, http_session, CONTROL_CHAT_ID
    token = bot_info['token']
    username = bot_info['username']
    state = bot_states[token]
    
    print(f"Worker started for bot: @{username}")
    
    while blocking_active:
        now = time.time()
        if now < state['is_banned_until']:
            await asyncio.sleep(1)
            continue
            
        if state['queue']:
            user_id = state['queue'].pop(0)
            
            if state['start_time'] is None:
                state['start_time'] = time.time()
                
            url = f"https://api.telegram.org/bot{token}/banChatMember"
            payload = {
                "chat_id": active_channel.id,
                "user_id": user_id
            }
            
            try:
                async with http_session.post(url, json=payload) as resp:
                    resp_data = await resp.json()
                    
                    if resp_data.get("ok"):
                        state['banned_count'] += 1
                        
                        # Report every 500 bans
                        if state['banned_count'] % 500 == 0:
                            elapsed = time.time() - state['start_time']
                            msg = (f"🤖 Бот @{username}\n"
                                   f"✅ {state['banned_count']} адамды блокталды.\n"
                                   f"⏱ Нақты кеткен уақыт: {format_duration(elapsed)}")
                            await send_bot_message(token, msg)
                            
                        # Rate limit: 30 bans per 60 seconds (2 seconds delay per ban)
                        await asyncio.sleep(2)
                    else:
                        error_code = resp_data.get("error_code")
                        description = resp_data.get("description", "")
                        
                        if error_code == 429:
                            # Parse FloodWait/Spam block duration
                            retry_after = resp_data.get("parameters", {}).get("retry_after", 3600)
                            state['is_banned_until'] = time.time() + retry_after
                            
                            duration_str = format_duration(retry_after)
                            msg = (f"⚠️ Бот @{username} уақытша спам блок алды!\n"
                                   f"📊 Барлығы блокталған: {state['banned_count']}\n"
                                   f"⏳ Күту уақыты: {duration_str}\n"
                                   f"❓ Себебі: {description}")
                            
                            await send_bot_message(token, msg)
                        else:
                            # Skip if user cannot be banned (already kicked, left, etc.)
                            await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Exception in bot @{username} ban task: {e}")
                await asyncio.sleep(1)
        else:
            await asyncio.sleep(1)


async def member_generator():
    """Yields member IDs that need to be banned, ignoring admins and already processed IDs.
    Uses Cyrillic and Latin alphabetical search queries to bypass Telegram's 10,000 limit."""
    global active_channel, admin_ids, assigned_user_ids, blocking_active
    
    # 1. Start with regular participant search
    try:
        async for user in client.iter_participants(active_channel):
            if not blocking_active:
                break
            if user.id not in admin_ids and user.id not in assigned_user_ids and not user.bot:
                assigned_user_ids.add(user.id)
                yield user.id
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
    except Exception as e:
        print(f"Error in normal member fetch: {e}")
        
    # 2. Bypassing 10k limit using alphabetical search (Latin + Cyrillic + Numbers)
    chars = "abcdefghijklmnopqrstuvwxyzабвгдежзийклмнопрстуфхцчшщъыьэюя0123456789"
    for char in chars:
        if not blocking_active:
            break
        try:
            async for user in client.iter_participants(active_channel, search=char):
                if not blocking_active:
                    break
                if user.id not in admin_ids and user.id not in assigned_user_ids and not user.bot:
                    assigned_user_ids.add(user.id)
                    yield user.id
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            print(f"Error in alphabetical search for '{char}': {e}")
            await asyncio.sleep(1)


async def scraper_loop():
    """Scrapes 150 members and refills bot queues when they fall <= 20.
    Executes check and distribution every 4 seconds."""
    global blocking_active, bot_states
    gen = member_generator()
    
    while blocking_active:
        # Check which bots need refill
        bots_needing_refill = [b for b in bot_states.values() if len(b['queue']) <= 20]
        
        if bots_needing_refill:
            batch = []
            for _ in range(150):
                if not blocking_active:
                    break
                try:
                    user_id = await asyncio.wait_for(gen.__anext__(), timeout=0.1)
                    batch.append(user_id)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
            
            if batch:
                print(f"Scraped {len(batch)} users. Distributing to {len(bots_needing_refill)} bots...")
                # Distribute IDs to bots
                for bot in bots_needing_refill:
                    if not batch:
                        break
                    space = 100 - len(bot['queue'])
                    if space > 0:
                        to_add = batch[:space]
                        bot['queue'].extend(to_add)
                        batch = batch[space:]
                        print(f"Queue of @{bot['username']} refilled by {len(to_add)}. Queue size: {len(bot['queue'])}")
                        
        # 4 seconds check interval: "user bot ір 4 сек саиын 150 адам id береді"
        await asyncio.sleep(4)


@client.on(events.NewMessage)
async def command_handler(event):
    global active_channel, me_id, CONTROL_CHAT_ID, blocking_active, bot_tasks, scraper_task, admin_ids, assigned_user_ids
    
    # Listen to commands from the owner or in the control chat
    text = event.text.strip()
    
    # Dynamically update CONTROL_CHAT_ID on command reception to guarantee messaging works
    if text.startswith(".") and (event.chat_id == CONTROL_CHAT_ID or event.sender_id == me_id):
        CONTROL_CHAT_ID = event.chat_id

    # 1. .help
    if text == ".help":
        help_text = (
            "🤖 **Көп-Ботты Канал Тазалау Бағдарламасы**\n\n"
            "📌 **Қолжетімді командалар тізімі:**\n"
            "🔹 `.help` — Осы анықтама тізімін шығару.\n"
            "🔹 `.ping` — Жүйенің жауап беру жылдамдығы мен жұмыс уақытын тексеру.\n"
            "🔹 `.add bots <channel_id>` — Боттарды арнаға қосып, әкімші құқықтарын беру.\n"
            "🔹 `.start <channel_id>` — Мақсатты арнаны анықтап сақтау.\n"
            "🔹 `.start blok` немесе `.start kick` — Тазалауды бастау.\n"
            "🔹 `.stop` — Блоктауды тоқтату."
        )
        await event.reply(help_text)

    # 2. .ping
    elif text == ".ping":
        start_t = time.time()
        reply_msg = await event.reply("🏓 Понг...")
        ping_ms = (time.time() - start_t) * 1000
        
        uptime_sec = time.time() - START_TIME
        uptime_str = format_duration(uptime_sec)
        
        await reply_msg.edit(
            f"🏓 **Понг!**\n"
            f"⚡️ **Пинг:** {ping_ms:.2f} мс\n"
            f"⏱ **Жұмыс уақыты:** {uptime_str}"
        )

    # 3. .add bots <channel_id>
    elif text.startswith(".add bots "):
        target_input = text[10:].strip()
        if not target_input:
            await event.reply("❌ Арнаны немесе топты көрсетіңіз. Мысалы: `.add bots @my_channel`")
            return
            
        status_msg = await event.reply("⏳ Боттарды арнаға қосу және әкімші құқықтарын беру басталды...")
        
        try:
            target_chat = await client.get_entity(parse_chat_id(target_input))
        except Exception as e:
            await status_msg.edit(f"❌ Арна табылмады: {e}")
            return
            
        if not loaded_bots:
            await status_msg.edit("⚠️ Қосылған боттар жоқ! Алдымен config.py файлын толтырыңыз.")
            return
            
        rights = ChatAdminRights(
            change_info=True,
            post_messages=True,
            edit_messages=True,
            delete_messages=True,
            ban_users=True,
            invite_users=True,
            pin_messages=True,
            add_admins=False,
            anonymous=False,
            manage_call=True,
            other=True
        )
        
        success_count = 0
        for bot_info in loaded_bots:
            try:
                bot_entity = await client.get_entity(bot_info['username'])
                try:
                    await client(EditAdminRequest(target_chat, bot_entity, rights, rank="Bot Admin"))
                except UserNotParticipantError:
                    # Try inviting first
                    await client(InviteToChannelRequest(target_chat, [bot_entity]))
                    await client(EditAdminRequest(target_chat, bot_entity, rights, rank="Bot Admin"))
                success_count += 1
                await client.send_message(CONTROL_CHAT_ID, f"✅ @{bot_info['username']} сәтті әкімші етіп тағайындалды.")
            except Exception as e:
                await client.send_message(CONTROL_CHAT_ID, f"❌ @{bot_info['username']} қосу кезінде қате: {e}")
                
        await status_msg.edit(f"🏁 Боттарды қосу аяқталды: {success_count}/{len(loaded_bots)} бот әкімші етілді.")

    # 4. .start <channel_id> (Saves the channel/group)
    elif text.startswith(".start ") and not (text.endswith("blok") or text.endswith("kick") or text.endswith("block")):
        target_input = text[7:].strip()
        if not target_input:
            await event.reply("❌ Арна сілтемесін немесе ID-ін жазыңыз. Мысалы: `.start @my_channel`")
            return
            
        status_msg = await event.reply("⏳ Арна ізделуде...")
        
        try:
            active_channel = await client.get_entity(parse_chat_id(target_input))
            await status_msg.edit(f"📢 Арна табылды: '{active_channel.title}' (ID: {active_channel.id})\n\nБлоктауды бастау үшін `.start blok` немесе `.start kick` деп жазыңыз.")
        except Exception as e:
            active_channel = None
            await status_msg.edit(f"❌ Арнаны табу мүмкін болмады: {e}")

    # 5. .start blok немесе .start kick немесе .start block
    elif text in [".start blok", ".start kick", ".start block"]:
        if not active_channel:
            await event.reply("❌ Алдымен арнаны таңдау керек! Мысалы: `.start @my_channel` деп жазыңыз.")
            return
            
        if blocking_active:
            await event.reply("⚠️ Блоктау процесі қазірдің өзінде іске қосулы!")
            return
            
        if not loaded_bots:
            await event.reply("❌ Боттар тізімі бос немесе жүктелмеген. config.py тексеріңіз.")
            return
            
        status_msg = await event.reply("🚀 Арнаны тазалау барысын дайындау басталды...")
        
        # Determine admins to protect them
        admin_ids.clear()
        admin_ids.add(me_id)
        for bot_info in loaded_bots:
            admin_ids.add(bot_info['id'])
            
        try:
            async for admin in client.iter_participants(active_channel, filter=ChannelParticipantsAdmins):
                admin_ids.add(admin.id)
        except Exception as e:
            await event.reply(f"⚠️ Әкімшілерді анықтау сәтсіз: {e}. Скрипт жалғаса береді...")
            
        # Reset states
        assigned_user_ids.clear()
        for token, state in bot_states.items():
            state['queue'].clear()
            state['banned_count'] = 0
            state['start_time'] = None
            state['is_banned_until'] = 0
            
        blocking_active = True
        
        # Start bot workers
        bot_tasks.clear()
        for bot_info in loaded_bots:
            task = asyncio.create_task(bot_worker(bot_info))
            bot_tasks.append(task)
            
        # Start scraper loop
        scraper_task = asyncio.create_task(scraper_loop())
        
        await status_msg.edit(f"✅ Тазалау басталды! 20 бот қосылып, әрқайсысы 2 секундта 1 адамнан блоктайды.\n"
                              f"📢 Қорғалатын әкімшілер саны: {len(admin_ids)}")

    # 6. .stop
    elif text == ".stop":
        if not blocking_active:
            await event.reply("⚠️ Белсенді блокталған процесс жоқ.")
            return
            
        blocking_active = False
        
        # Cancel tasks
        if scraper_task:
            scraper_task.cancel()
            scraper_task = None
            
        for task in bot_tasks:
            task.cancel()
        bot_tasks.clear()
        
        # Clear queues
        for token, state in bot_states.items():
            state['queue'].clear()
            
        await event.reply("🛑 Арнаны тазалау процесі тоқтатылды!")


# =====================================================================
# FASTAPI ENDPOINTS & WEB PANEL LOGIC
# =====================================================================

class ChannelSelect(BaseModel):
    channel_id: str


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    # Serve Web Panel UI in Kazakh
    html_content = """
    <!DOCTYPE html>
    <html lang="kk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram Channel Cleaner Web Panel</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            body {
                font-family: 'Inter', sans-serif;
                background-color: #0f172a;
                color: #f8fafc;
            }
        </style>
    </head>
    <body class="p-6">
        <div class="max-w-7xl mx-auto space-y-6">
            <!-- Header -->
            <header class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-slate-800 p-6 rounded-2xl shadow-xl border border-slate-700">
                <div>
                    <h1 class="text-2xl md:text-3xl font-bold text-sky-400 flex items-center gap-2">
                        <i class="fa-solid fa-broom-ball"></i> Telegram Channel Cleaner
                    </h1>
                    <p class="text-slate-400 text-sm mt-1">Көп-ботты каналды тазалау және блоктау веб-панелі</p>
                </div>
                <div class="flex flex-wrap gap-3">
                    <button onclick="openQRModal()" class="bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold py-2 px-4 rounded-xl shadow-lg transition flex items-center gap-2">
                        <i class="fa-solid fa-qrcode"></i> Жаңа Аккаунт Қосу
                    </button>
                    <button onclick="loadChannels()" class="bg-slate-700 hover:bg-slate-600 text-white font-semibold py-2 px-4 rounded-xl shadow transition flex items-center gap-2">
                        <i class="fa-solid fa-arrows-rotate"></i> Каналдарды Жаңарту
                    </button>
                </div>
            </header>

            <!-- Stats Grid -->
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                <!-- Total Kicked -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg flex items-center gap-4">
                    <div class="p-4 bg-red-500/10 text-red-400 rounded-xl">
                        <i class="fa-solid fa-user-slash text-2xl"></i>
                    </div>
                    <div>
                        <p class="text-slate-400 text-sm font-medium">Блокталған мүшелер</p>
                        <h3 id="stat-total-banned" class="text-2xl font-bold text-red-500 mt-1">0</h3>
                    </div>
                </div>
                <!-- Active Bots -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg flex items-center gap-4">
                    <div class="p-4 bg-green-500/10 text-green-400 rounded-xl">
                        <i class="fa-solid fa-robot text-2xl"></i>
                    </div>
                    <div>
                        <p class="text-slate-400 text-sm font-medium">Белсенді боттар</p>
                        <h3 id="stat-active-bots" class="text-2xl font-bold text-green-400 mt-1">0 / 20</h3>
                    </div>
                </div>
                <!-- Target Channel -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg flex items-center gap-4 col-span-1 sm:col-span-2">
                    <div class="p-4 bg-sky-500/10 text-sky-400 rounded-xl">
                        <i class="fa-solid fa-bullhorn text-2xl"></i>
                    </div>
                    <div>
                        <p class="text-slate-400 text-sm font-medium">Мақсатты арна</p>
                        <h3 id="stat-target-channel" class="text-xl font-bold text-white mt-1 truncate">Жүктелуде...</h3>
                    </div>
                </div>
            </div>

            <!-- Controls and Channels -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Channels List Panel -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg col-span-1 flex flex-col space-y-4">
                    <h2 class="text-lg font-semibold flex items-center gap-2"><i class="fa-solid fa-list-check text-sky-400"></i> Арнаны Таңдау</h2>
                    <div class="flex-1 overflow-y-auto max-h-[300px] space-y-2 pr-1" id="channels-container">
                        <p class="text-slate-400 text-sm">Каналдар тізімін жаңартуды басыңыз...</p>
                    </div>
                </div>

                <!-- Process Manager -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg col-span-1 lg:col-span-2 flex flex-col justify-between space-y-6">
                    <div>
                        <h2 class="text-lg font-semibold flex items-center gap-2"><i class="fa-solid fa-sliders text-sky-400"></i> Жұмысты Басқару</h2>
                        <p class="text-slate-400 text-sm mt-1">Каналды таңдап, блоктау процесін осы жерден басқарыңыз.</p>
                        
                        <div id="target-details" class="mt-4 p-4 bg-slate-900 rounded-xl border border-slate-700/50 hidden">
                            <p class="text-xs text-slate-400">Таңдалған арна:</p>
                            <h4 id="target-title" class="font-bold text-white text-lg">Канал аты</h4>
                            <p id="target-id" class="text-xs text-sky-400 font-mono mt-0.5">ID: -100123456</p>
                        </div>
                    </div>

                    <div class="flex gap-4">
                        <button id="btn-start" onclick="startCleaning()" class="flex-1 bg-green-500 hover:bg-green-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-6 rounded-xl shadow-lg transition flex items-center justify-center gap-2 text-lg">
                            <i class="fa-solid fa-play"></i> Бастау
                        </button>
                        <button id="btn-stop" onclick="stopCleaning()" class="flex-1 bg-red-500 hover:bg-red-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-6 rounded-xl shadow-lg transition flex items-center justify-center gap-2 text-lg">
                            <i class="fa-solid fa-stop"></i> Тоқтату
                        </button>
                    </div>
                </div>
            </div>

            <!-- Bots Performance Panel -->
            <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg">
                <h2 class="text-lg font-semibold flex items-center gap-2 mb-4"><i class="fa-solid fa-chart-line text-sky-400"></i> 20 Боттың жұмыс күйі мен өнімділігі</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-700 text-slate-400 text-sm">
                                <th class="pb-3 font-semibold">Бот атауы</th>
                                <th class="pb-3 font-semibold">Күйі</th>
                                <th class="pb-3 font-semibold">Блокталғандар</th>
                                <th class="pb-3 font-semibold">Кезек мөлшері</th>
                            </tr>
                        </thead>
                        <tbody id="bots-table-body" class="divide-y divide-slate-700/50">
                            <!-- Populated dynamically -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- QR Code Modal -->
        <div id="qr-modal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
            <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-2xl max-w-md w-full text-center space-y-4">
                <h3 class="text-xl font-bold text-white flex items-center justify-center gap-2"><i class="fa-brands fa-telegram text-sky-400"></i> Telegram-ға QR арқылы кіру</h3>
                <p class="text-slate-300 text-sm">Панельге жаңа сессия қосу үшін Telegram қосымшасынан QR кодты сканерлеңіз.</p>
                
                <div class="flex justify-center bg-white p-4 rounded-xl max-w-[240px] mx-auto" id="qr-code-container">
                    <!-- Base64 QR code image -->
                    <div class="w-[200px] h-[200px] bg-slate-200 animate-pulse rounded flex items-center justify-center text-slate-500">QR код жүктелуде...</div>
                </div>

                <div id="qr-status" class="text-sm font-medium text-amber-400">Күтуде...</div>

                <div class="flex justify-end gap-2 pt-2 border-t border-slate-700/50">
                    <button onclick="closeQRModal()" class="bg-slate-700 hover:bg-slate-600 text-white font-medium py-2 px-4 rounded-xl transition">Жабу</button>
                </div>
            </div>
        </div>

        <script>
            let currentSelectedChannel = null;
            let statusInterval = null;

            // Load channel list
            async function loadChannels() {
                const container = document.getElementById("channels-container");
                container.innerHTML = `<div class="text-slate-400 text-sm animate-pulse flex items-center gap-2"><i class="fa-solid fa-spinner animate-spin"></i> Арналар тізімі жүктелуде...</div>`;
                
                try {
                    const response = await fetch("/api/channels");
                    const channels = await response.json();
                    
                    if (channels.length === 0) {
                        container.innerHTML = `<p class="text-slate-400 text-sm">Ешқандай канал немесе супертоп табылдамы.</p>`;
                        return;
                    }
                    
                    container.innerHTML = "";
                    channels.forEach(ch => {
                        const div = document.createElement("div");
                        div.className = "p-3 bg-slate-900/50 hover:bg-slate-700/50 border border-slate-700 rounded-xl cursor-pointer transition flex items-center justify-between";
                        div.onclick = () => selectChannel(ch);
                        div.innerHTML = `
                            <div>
                                <h4 class="font-semibold text-sm text-white">${ch.title}</h4>
                                <p class="text-xs text-slate-400">${ch.username ? "@" + ch.username : "Жеке арна"}</p>
                            </div>
                            <span class="text-xs text-sky-400 font-mono">${ch.id}</span>
                        `;
                        container.appendChild(div);
                    });
                } catch(e) {
                    container.innerHTML = `<p class="text-red-400 text-sm">Жүктеу қатесі: ${e.message}</p>`;
                }
            }

            function selectChannel(ch) {
                currentSelectedChannel = ch;
                const details = document.getElementById("target-details");
                details.classList.remove("hidden");
                document.getElementById("target-title").innerText = ch.title;
                document.getElementById("target-id").innerText = "ID: " + ch.id;
            }

            // Start cleaning
            async function startCleaning() {
                if (!currentSelectedChannel) {
                    alert("Алдымен тазалайтын каналды таңдаңыз!");
                    return;
                }
                
                try {
                    const response = await fetch("/api/start", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ channel_id: String(currentSelectedChannel.id) })
                    });
                    const res = await response.json();
                    if (res.status === "started") {
                        alert("Тазалау процесі сәтті іске қосылды!");
                    } else {
                        alert("Қате: " + res.message);
                    }
                } catch(e) {
                    alert("Қосылу қатесі: " + e.message);
                }
            }

            // Stop cleaning
            async function stopCleaning() {
                try {
                    const response = await fetch("/api/stop", { method: "POST" });
                    const res = await response.json();
                    if (res.status === "stopped") {
                        alert("Тазалау процесі тоқтатылды!");
                    }
                } catch(e) {
                    alert("Тоқтату қатесі: " + e.message);
                }
            }

            // Poll stats
            async function updateStats() {
                try {
                    const response = await fetch("/api/stats");
                    const data = await response.json();
                    
                    document.getElementById("stat-total-banned").innerText = data.total_banned;
                    document.getElementById("stat-active-bots").innerText = `${data.active_bots_count} / ${data.total_bots_count}`;
                    
                    if (data.active_channel) {
                        document.getElementById("stat-target-channel").innerText = `${data.active_channel.title} (ID: ${data.active_channel.id})`;
                    } else {
                        document.getElementById("stat-target-channel").innerText = "Ешқандай канал таңдалмаған";
                    }

                    // Update buttons
                    document.getElementById("btn-start").disabled = data.blocking_active;
                    document.getElementById("btn-stop").disabled = !data.blocking_active;

                    // Update bots table
                    const tbody = document.getElementById("bots-table-body");
                    tbody.innerHTML = "";
                    data.bots.forEach(bot => {
                        const tr = document.createElement("tr");
                        tr.className = "border-b border-slate-700/30 text-sm";
                        
                        let badgeClass = "bg-green-500/10 text-green-400";
                        if (bot.status.includes("Blocked")) badgeClass = "bg-red-500/10 text-red-400";
                        else if (bot.status === "Idle") badgeClass = "bg-slate-500/10 text-slate-400";

                        tr.innerHTML = `
                            <td class="py-3 font-medium text-white">@${bot.username}</td>
                            <td class="py-3"><span class="px-2 py-1 rounded text-xs font-semibold ${badgeClass}">${bot.status}</span></td>
                            <td class="py-3 font-semibold text-slate-300">${bot.banned_count}</td>
                            <td class="py-3 text-slate-400">${bot.queue_size} / 100</td>
                        `;
                        tbody.appendChild(tr);
                    });
                } catch(e) {
                    console.error("Stats fetch error:", e);
                }
            }

            // Web QR Login Modal
            let qrInterval = null;
            function openQRModal() {
                document.getElementById("qr-modal").classList.remove("hidden");
                startQRLoginFlow();
            }

            function closeQRModal() {
                document.getElementById("qr-modal").classList.add("hidden");
                if (qrInterval) clearInterval(qrInterval);
            }

            async function startQRLoginFlow() {
                const container = document.getElementById("qr-code-container");
                const status = document.getElementById("qr-status");
                
                container.innerHTML = `<div class="w-[200px] h-[200px] flex items-center justify-center text-slate-500"><i class="fa-solid fa-spinner animate-spin text-xl mr-2"></i> QR код жасалуда...</div>`;
                status.innerText = "Қосылуда...";
                
                try {
                    const response = await fetch("/api/qr/start", { method: "POST" });
                    
                    qrInterval = setInterval(async () => {
                        const stResp = await fetch("/api/qr/status");
                        const stData = await stResp.json();
                        
                        status.innerText = "Күйі: " + stData.status;
                        
                        if (stData.qr_base64) {
                            container.innerHTML = `<img src="${stData.qr_base64}" class="w-[200px] h-[200px]" />`;
                        }
                        
                        if (stData.status === "authorized") {
                            clearInterval(qrInterval);
                            status.className = "text-sm font-medium text-green-400";
                            status.innerText = "Сәтті кірдіңіз! Бағдарлама қайта жүктелуде...";
                            setTimeout(() => closeQRModal(), 3000);
                        } else if (stData.status === "failed") {
                            clearInterval(qrInterval);
                            status.className = "text-sm font-medium text-red-400";
                            status.innerText = "Қате: " + stData.error;
                        }
                    }, 2000);
                } catch(e) {
                    status.innerText = "Жүйеге қосылу қатесі: " + e.message;
                }
            }

            // Initializations
            loadChannels();
            updateStats();
            statusInterval = setInterval(updateStats, 2000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/stats")
async def get_stats():
    global blocking_active, active_channel, bot_states, START_TIME
    
    total_banned = sum(b['banned_count'] for b in bot_states.values())
    active_bots_count = sum(1 for b in bot_states.values() if time.time() >= b['is_banned_until'])
    
    bots_list = []
    for token, b in bot_states.items():
        status = "Active"
        wait_remaining = max(0, int(b['is_banned_until'] - time.time()))
        if wait_remaining > 0:
            status = f"Spam Blocked (wait {format_duration(wait_remaining)})"
        elif not blocking_active:
            status = "Idle"
            
        bots_list.append({
            "username": b['username'],
            "banned_count": b['banned_count'],
            "queue_size": len(b['queue']),
            "status": status,
            "wait_remaining": wait_remaining
        })
        
    uptime_sec = time.time() - START_TIME
    
    return {
        "blocking_active": blocking_active,
        "active_channel": {
            "id": active_channel.id if active_channel else None,
            "title": active_channel.title if active_channel else "Ешқандай канал таңдалмаған"
        } if active_channel else None,
        "total_banned": total_banned,
        "active_bots_count": active_bots_count,
        "total_bots_count": len(bot_states),
        "uptime": format_duration(uptime_sec),
        "bots": bots_list
    }


@app.get("/api/channels")
async def get_channels():
    if not client.is_connected():
        return []
    channels = []
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                channels.append({
                    "id": dialog.id,
                    "title": dialog.name,
                    "username": getattr(dialog.entity, 'username', None)
                })
    except Exception as e:
        print(f"Error fetching dialogs: {e}")
    return channels


@app.post("/api/start")
async def web_start_cleaning(data: ChannelSelect):
    global active_channel, me_id, blocking_active, bot_tasks, scraper_task, admin_ids, assigned_user_ids
    
    try:
        active_channel = await client.get_entity(parse_chat_id(data.channel_id))
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": f"Арна табылмады: {str(e)}"}, status_code=400)
        
    if blocking_active:
        return {"status": "already_running"}
        
    # Determine admins to protect them
    admin_ids.clear()
    admin_ids.add(me_id)
    for bot_info in loaded_bots:
        admin_ids.add(bot_info['id'])
        
    try:
        async for admin in client.iter_participants(active_channel, filter=ChannelParticipantsAdmins):
            admin_ids.add(admin.id)
    except Exception as e:
        print(f"Web start admin determination warning: {e}")
        
    # Reset states
    assigned_user_ids.clear()
    for token, state in bot_states.items():
        state['queue'].clear()
        state['banned_count'] = 0
        state['start_time'] = None
        state['is_banned_until'] = 0
        
    blocking_active = True
    
    # Start bot workers
    bot_tasks.clear()
    for bot_info in loaded_bots:
        task = asyncio.create_task(bot_worker(bot_info))
        bot_tasks.append(task)
        
    # Start scraper loop
    scraper_task = asyncio.create_task(scraper_loop())
    
    return {"status": "started"}


@app.post("/api/stop")
async def web_stop_cleaning():
    global blocking_active, scraper_task, bot_tasks
    if not blocking_active:
        return {"status": "not_running"}
        
    blocking_active = False
    
    if scraper_task:
        scraper_task.cancel()
        scraper_task = None
        
    for task in bot_tasks:
        task.cancel()
    bot_tasks.clear()
    
    for token, state in bot_states.items():
        state['queue'].clear()
        
    return {"status": "stopped"}


async def web_qr_worker():
    """Background worker that awaits QR authorization from Telegram."""
    global qr_client, qr_login_instance, qr_state
    
    try:
        user = await qr_login_instance.wait(timeout=60)
        qr_state["status"] = "authorized"
        qr_state["user"] = f"{user.first_name} (@{user.username})"
        print(f"🎉 Web QR Login successful: {qr_state['user']}")
    except SessionPasswordNeededError:
        qr_state["status"] = "needs_password"
    except Exception as e:
        qr_state["status"] = "failed"
        qr_state["error"] = str(e)
        try:
            os.remove(f"{qr_state['session_name']}.session")
        except:
            pass
    finally:
        await qr_client.disconnect()


@app.post("/api/qr/start")
async def start_web_qr():
    global qr_client, qr_login_instance, qr_state
    
    timestamp = int(time.time())
    session_name = str(BASE_DIR / f"session_qr_{timestamp}")
    qr_state = {"status": "generating", "session_name": session_name}
    
    try:
        qr_client = TelegramClient(session_name, API_ID, API_HASH)
        await qr_client.connect()
        
        qr_login_instance = await qr_client.qr_login()
        
        # Generate QR code base64
        qr_img = qrcode.make(qr_login_instance.url)
        buffered = io.BytesIO()
        qr_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        qr_state["qr_base64"] = f"data:image/png;base64,{img_str}"
        qr_state["status"] = "waiting"
        
        # Run wait task in background
        asyncio.create_task(web_qr_worker())
        
        return {"status": "started"}
    except Exception as e:
        qr_state["status"] = "failed"
        qr_state["error"] = str(e)
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@app.get("/api/qr/status")
async def get_web_qr_status():
    global qr_state
    return qr_state


@app.post("/api/qr/password")
async def submit_2fa_password(data: dict):
    global qr_client, qr_state
    password = data.get("password")
    if qr_state["status"] != "needs_password" or not qr_client:
        return JSONResponse(content={"status": "error", "message": "Not in 2FA state"}, status_code=400)
        
    try:
        user = await qr_client.sign_in(password=password)
        qr_state["status"] = "authorized"
        qr_state["user"] = f"{user.first_name} (@{user.username})"
        return {"status": "authorized"}
    except Exception as e:
        qr_state["status"] = "failed"
        qr_state["error"] = str(e)
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=400)


async def self_ping_loop():
    """Send a GET request to ourselves every 10 minutes to keep Render alive."""
    await asyncio.sleep(30)  # Wait 30 seconds after startup before the first ping
    
    # Read public Render external URL or fallback to localhost
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        port = int(os.getenv("PORT", 8080))
        render_url = f"http://localhost:{port}"
        
    print(f"🔄 Render self-ping loop started. Target: {render_url}")
    
    while True:
        try:
            # Send HTTP GET request to keep service active
            async with http_session.get(render_url) as resp:
                if resp.status == 200:
                    print(f"✅ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Render self-ping successful!")
                else:
                    print(f"⚠️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Render self-ping status: {resp.status}")
        except Exception as e:
            print(f"❌ Render self-ping failed: {e}")
            
        # Wait 10 minutes (600 seconds)
        await asyncio.sleep(600)


# =====================================================================
# SYSTEM STARTUP & MAIN LOOP
# =====================================================================

async def main():
    global me_id, http_session
    print("==================================================")
    print("  Telegram Арнаны Тазалау Скрипті (Multi-Bot)      ")
    print("==================================================")
    
    # Initialize aiohttp session
    http_session = aiohttp.ClientSession()
    
    # Load bots
    await init_bots()
    
    # Start Userbot
    await client.start()
    me = await client.get_me()
    me_id = me.id
    print(f"🎉 Userbot іске қосылды: {me.first_name} (@{me.username})")
    print("Командаларды күтуде...")
    
    # Launch FastAPI Server
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    print(f"🌐 Веб-панель қосылды: http://localhost:{port}")
    
    # Start Self-Ping task to keep Render alive
    asyncio.create_task(self_ping_loop())
    
    try:
        await client.run_until_disconnected()
    finally:
        if http_session:
            await http_session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Скрипт тоқтатылды.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Қате: {e}")
        sys.exit(1)
