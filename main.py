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

# BASE_DIR yo'lini olish
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Tizim ishga tushgan vaqt
START_TIME = time.time()

# Global o'zgaruvchilar
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
me_id = None
active_channel = None
blocking_active = False
CURRENT_LANG = "uz"  # Sukut bo'yicha til O'zbekcha

loaded_bots = []   # Botlar ro'yxati: [{'token': ..., 'id': ..., 'username': ...}]
bot_states = {}    # Botlar holati: {token: {'queue': [], 'banned_count': 0, 'start_time': None, 'is_banned_until': 0, 'username': ..., 'id': ...}}
assigned_user_ids = set()
admin_ids = set()
CONTROL_CHAT_ID = -1003930058805  # Nazorat chati ID-si, dinamik ravishda yangilanadi

# aiohttp sessiyasi
http_session = None

# Ishlayotgan vazifalar (tasks)
bot_tasks = []
scraper_task = None

# Veb QR Login holatlari
qr_client = None
qr_login_instance = None
qr_state = {"status": "idle", "qr_base64": None, "error": None}

# FastAPI ilovasini yaratish
app = FastAPI(title="Telegram Channel Cleaner Web Panel")

# =====================================================================
# TIL LOQALIZATSIYASI (LOCALIZATION DICTIONARY)
# =====================================================================

LOCALES = {
    "uz": {
        "help_text": (
            "🤖 **Ko'p-botli Kanal Tozalovchi Dastur**\n\n"
            "📌 **Mavjud komandalar ro'yxati:**\n"
            "🔹 `.help` — Yordam menyusini ko'rsatish.\n"
            "🔹 `.ping` — Ping tezligi va tizim ish vaqtini (uptime) ko'rsatish.\n"
            "🔹 `.lang <uz|en|ru>` — Tizim tilini o'zgartirish.\n"
            "🔹 `.add bots <kanal_id>` — 20 ta botni kanalga qo'shish va admin qilish.\n"
            "🔹 `.start <kanal_id>` — Maqsadli kanalni saqlab qo'yish.\n"
            "🔹 `.start blok` yoki `.start kick` — Tozalashni boshlash.\n"
            "🔹 `.stop` — Tozalash jarayonini to'xtatish."
        ),
        "ping_text": "🏓 **Pong!**\n⚡️ **Ping:** {ping:.2f} ms\n⏱ **Ish vaqti:** {uptime}",
        "spamblock_alert": "⚠️ Bot @{username} vaqtincha spam-blok oldi!\n📊 Jami bloklangan: {banned_count}\n⏳ Kutish vaqti: {duration}\n❓ Sababi: {description}",
        "ban_report": "🤖 Bot @{username}\n✅ {banned_count} kishi bloklandi.\n⏱ Sarflangan vaqt: {duration}",
        "lang_changed": "✅ Tizim tili muvaffaqiyatli **O'zbek** tiliga o'zgartirildi!",
        "lang_invalid": "❌ Noto'g'ri til kodi! Faqat `uz`, `en` yoki `ru` tillaridan foydalaning.",
        "channel_not_found": "❌ Kanal topilmadi: {error}",
        "no_bots": "⚠️ Qo'shilgan botlar yo'q! Avval config.py faylini to'ldiring.",
        "start_status": "🚀 Kanalni tozalash jarayoni boshlandi! 20 ta bot faollashdi, har biri 2 soniyada 1 kishini bloklaydi.\n📢 Himoyalangan adminlar soni: {admin_count}",
        "stop_status": "🛑 Kanalni tozalash jarayoni to'xtatildi!",
        "add_bots_start": "⏳ Botlarni kanalga qo'shish va admin huquqlarini berish boshlandi...",
        "add_bots_success": "✅ @{username} muvaffaqiyatli admin etib tayinlandi.",
        "add_bots_error": "❌ @{username} qo'shishda xatolik: {error}",
        "add_bots_finish": "🏁 Botlarni qo'shish yakunlandi: {success}/{total} bot admin qilindi.",
        "choose_channel": "❌ Avval kanalni tanlashingiz kerak! Masalan: `.start @kanal_nomi` deb yozing."
    },
    "en": {
        "help_text": (
            "🤖 **Multi-Bot Channel Cleaner**\n\n"
            "📌 **Available commands list:**\n"
            "🔹 `.help` — Show this help message.\n"
            "🔹 `.ping` — Check latency and system uptime.\n"
            "🔹 `.lang <uz|en|ru>` — Change system language.\n"
            "🔹 `.add bots <channel_id>` — Add 20 bots to the channel and make them admins.\n"
            "🔹 `.start <channel_id>` — Set the target channel.\n"
            "🔹 `.start blok` or `.start kick` — Start the cleaning process.\n"
            "🔹 `.stop` — Stop the cleaning process."
        ),
        "ping_text": "🏓 **Pong!**\n⚡️ **Ping:** {ping:.2f} ms\n⏱ **Uptime:** {uptime}",
        "spamblock_alert": "⚠️ Bot @{username} received a temporary spamblock!\n📊 Total banned: {banned_count}\n⏳ Wait duration: {duration}\n❓ Reason: {description}",
        "ban_report": "🤖 Bot @{username}\n✅ Kicked {banned_count} members.\n⏱ Elapsed time: {duration}",
        "lang_changed": "✅ System language successfully changed to **English**!",
        "lang_invalid": "❌ Invalid language code! Use only `uz`, `en`, or `ru`.",
        "channel_not_found": "❌ Channel not found: {error}",
        "no_bots": "⚠️ No bots loaded! Populate config.py first.",
        "start_status": "🚀 Cleaning process started! 20 bots active, each banning 1 member every 2 seconds.\n📢 Protected admins count: {admin_count}",
        "stop_status": "🛑 Cleaning process stopped!",
        "add_bots_start": "⏳ Adding bots to the channel and granting admin rights...",
        "add_bots_success": "✅ @{username} successfully promoted to admin.",
        "add_bots_error": "❌ Error adding @{username}: {error}",
        "add_bots_finish": "🏁 Bot promotion finished: {success}/{total} bots promoted.",
        "choose_channel": "❌ You must choose a channel first! Example: `.start @channel_name`"
    },
    "ru": {
        "help_text": (
            "🤖 **Мульти-Бот Очиститель Каналов**\n\n"
            "📌 **Список доступных команд:**\n"
            "🔹 `.help` — Показать эту справку.\n"
            "🔹 `.ping` — Проверить пинг и время работы системы.\n"
            "🔹 `.lang <uz|en|ru>` — Изменить рабочий язык.\n"
            "🔹 `.add bots <channel_id>` — Добавить 20 ботов в канал и сделать их админами.\n"
            "🔹 `.start <channel_id>` — Установить целевой канал.\n"
            "🔹 `.start blok` или `.start kick` — Начать процесс очистки.\n"
            "🔹 `.stop` — Остановить очистку."
        ),
        "ping_text": "🏓 **Понг!**\n⚡️ **Пинг:** {ping:.2f} мс\n⏱ **Время работы:** {uptime}",
        "spamblock_alert": "⚠️ Бот @{username} получил временный спамблок!\n📊 Всего забанено: {banned_count}\n⏳ Время ожидания: {duration}\n❓ Причина: {description}",
        "ban_report": "🤖 Бот @{username}\n✅ Забанено {banned_count} участников.\n⏱ Затраченное время: {duration}",
        "lang_changed": "✅ Язык системы успешно изменен на **Русский**!",
        "lang_invalid": "❌ Неверный код языка! Используйте `uz`, `en` или `ru`.",
        "channel_not_found": "❌ Канал не найден: {error}",
        "no_bots": "⚠️ Нет загруженных ботов! Сначала заполните config.py.",
        "start_status": "🚀 Процесс очистки запущен! 20 ботов активны, каждый банит 1 человека каждые 2 секунды.\n📢 Количество защищенных админов: {admin_count}",
        "stop_status": "🛑 Процесс очистки остановлен!",
        "add_bots_start": "⏳ Начало добавления ботов в канал и выдачи прав администратора...",
        "add_bots_success": "✅ @{username} успешно назначен администратором.",
        "add_bots_error": "❌ Ошибка добавления @{username}: {error}",
        "add_bots_finish": "🏁 Добавление ботов завершено: {success}/{total} ботов назначены админами.",
        "choose_channel": "❌ Сначала нужно выбрать канал! Пример: `.start @имя_канала`"
    }
}


def format_duration(seconds, lang="uz"):
    """Vaqtni berilgan tilga mos ravishda formatlash."""
    seconds = int(seconds)
    if seconds <= 0:
        if lang == "uz": return "0 soniya"
        if lang == "ru": return "0 секунд"
        return "0 seconds"
        
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        if lang == "uz": parts.append(f"{hours} soat")
        elif lang == "ru": parts.append(f"{hours} час(ов)")
        else: parts.append(f"{hours} hour(s)")
    if minutes > 0:
        if lang == "uz": parts.append(f"{minutes} daqiqa")
        elif lang == "ru": parts.append(f"{minutes} минут(ы)")
        else: parts.append(f"{minutes} minute(s)")
    if secs > 0 or not parts:
        if lang == "uz": parts.append(f"{secs} soniya")
        elif lang == "ru": parts.append(f"{secs} секунд(ы)")
        else: parts.append(f"{secs} second(s)")
        
    return " ".join(parts)


async def init_bots():
    """config.py faylidan bot tokenlarini yuklash va tekshirish."""
    global loaded_bots, bot_states, http_session
    
    tokens = BOT_TOKENS
    loaded_bots = []
    bot_states = {}
    
    if not tokens:
        print("⚠️ config.py faylida BOT_TOKENS bo'sh!")
        return
        
    print(f"🤖 config.py faylidan {len(tokens)} ta token topildi. Tekshirilmoqda...")
    
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
                        print(f"✅ Bot muvaffaqiyatli qo'shildi: @{res['username']} (ID: {res['id']})")
                    else:
                        print(f"❌ Token yaroqsiz (API xatosi): {token}")
                else:
                    print(f"❌ Token yaroqsiz (HTTP {resp.status}): {token}")
        except Exception as e:
            print(f"❌ Tokenni tekshirishda xatolik ({token}): {e}")


async def send_bot_message(token, text):
    """Nazorat chatiga bot tokeni orqali xabar yuborish va 5 soniya kutish."""
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
                print(f"Bot xabarini yuborishda xatolik: {await resp.text()}")
    except Exception as e:
        print(f"Bot xabarini yuborishda xatolik: {e}")
    finally:
        # "xabar yozgandan so'ng 5 soniya dam olish kerak"
        await asyncio.sleep(5)


def parse_chat_id(input_str):
    """Kanal ID-sini standart formatga keltirish."""
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
    """Bitta bot uchun bloklash loopi."""
    global blocking_active, active_channel, bot_states, http_session, CONTROL_CHAT_ID, CURRENT_LANG
    token = bot_info['token']
    username = bot_info['username']
    state = bot_states[token]
    
    print(f"Worker ishga tushdi bot uchun: @{username}")
    
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
                        
                        # Har 500 ta blokdan so'ng hisobot yuborish
                        if state['banned_count'] % 500 == 0:
                            elapsed = time.time() - state['start_time']
                            duration_str = format_duration(elapsed, CURRENT_LANG)
                            msg = LOCALES[CURRENT_LANG]["ban_report"].format(
                                username=username,
                                banned_count=state['banned_count'],
                                duration=duration_str
                            )
                            await send_bot_message(token, msg)
                            
                        # Rate limit: 2 soniyada 1 kishi
                        await asyncio.sleep(2)
                    else:
                        error_code = resp_data.get("error_code")
                        description = resp_data.get("description", "")
                        
                        if error_code == 429:
                            # Spam-blok kutish vaqtini aniqlash
                            retry_after = resp_data.get("parameters", {}).get("retry_after", 3600)
                            state['is_banned_until'] = time.time() + retry_after
                            
                            duration_str = format_duration(retry_after, CURRENT_LANG)
                            msg = LOCALES[CURRENT_LANG]["spamblock_alert"].format(
                                username=username,
                                banned_count=state['banned_count'],
                                duration=duration_str,
                                description=description
                            )
                            await send_bot_message(token, msg)
                        else:
                            # Agar bloklab bo'lmasa, keyingisiga o'tish
                            await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Xatolik bot workerda @{username}: {e}")
                await asyncio.sleep(1)
        else:
            await asyncio.sleep(1)


async def member_generator():
    """Kanal a'zolarini qidirib generator sifatida qaytaradi.
    10k limitdan o'tish uchun alifboviy qidiruvdan foydalanadi."""
    global active_channel, admin_ids, assigned_user_ids, blocking_active
    
    # 1. Oddiy a'zolarni olish
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
        print(f"Oddiy qidiruvda xatolik: {e}")
        
    # 2. Alifboviy qidiruv (Lotin + Kirill + Raqamlar)
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
            print(f"Alifboviy qidiruvda xatolik ({char}): {e}")
            await asyncio.sleep(1)


async def scraper_loop():
    """A'zolarni yig'ish va bot navbatlariga har 4 soniyada tarqatish."""
    global blocking_active, bot_states
    gen = member_generator()
    
    while blocking_active:
        # Navbati kamaygan botlarni tekshirish
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
                # Botlarga tarqatish
                for bot in bots_needing_refill:
                    if not batch:
                        break
                    space = 100 - len(bot['queue'])
                    if space > 0:
                        to_add = batch[:space]
                        bot['queue'].extend(to_add)
                        batch = batch[space:]
                        print(f"Queue of @{bot['username']} refilled by {len(to_add)}. Queue size: {len(bot['queue'])}")
                        
        # Har 4 soniyada bitta tekshirish
        await asyncio.sleep(4)


@client.on(events.NewMessage)
async def command_handler(event):
    global active_channel, me_id, CONTROL_CHAT_ID, blocking_active, bot_tasks, scraper_task, admin_ids, assigned_user_ids, CURRENT_LANG
    
    text = event.text.strip()
    
    # Nazorat chati ID-sini avtomatik aniqlash
    if text.startswith(".") and (event.chat_id == CONTROL_CHAT_ID or event.sender_id == me_id):
        CONTROL_CHAT_ID = event.chat_id

    # 1. .help
    if text == ".help":
        await event.reply(LOCALES[CURRENT_LANG]["help_text"])

    # 2. .ping
    elif text == ".ping":
        start_t = time.time()
        reply_msg = await event.reply("🏓 ...")
        ping_ms = (time.time() - start_t) * 1000
        
        uptime_sec = time.time() - START_TIME
        uptime_str = format_duration(uptime_sec, CURRENT_LANG)
        
        await reply_msg.edit(
            LOCALES[CURRENT_LANG]["ping_text"].format(ping=ping_ms, uptime=uptime_str)
        )

    # 3. .lang <kod>
    elif text.startswith(".lang "):
        lang_code = text[6:].strip().lower()
        if lang_code in LOCALES:
            CURRENT_LANG = lang_code
            await event.reply(LOCALES[CURRENT_LANG]["lang_changed"])
        else:
            await event.reply(LOCALES[CURRENT_LANG]["lang_invalid"])

    # 4. .add bots <kanal_id>
    elif text.startswith(".add bots "):
        target_input = text[10:].strip()
        if not target_input:
            await event.reply("❌ ID yoki username kiriting!")
            return
            
        status_msg = await event.reply(LOCALES[CURRENT_LANG]["add_bots_start"])
        
        try:
            target_chat = await client.get_entity(parse_chat_id(target_input))
        except Exception as e:
            await status_msg.edit(LOCALES[CURRENT_LANG]["channel_not_found"].format(error=str(e)))
            return
            
        if not loaded_bots:
            await status_msg.edit(LOCALES[CURRENT_LANG]["no_bots"])
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
                    await client(InviteToChannelRequest(target_chat, [bot_entity]))
                    await client(EditAdminRequest(target_chat, bot_entity, rights, rank="Bot Admin"))
                success_count += 1
                await client.send_message(CONTROL_CHAT_ID, LOCALES[CURRENT_LANG]["add_bots_success"].format(username=bot_info['username']))
            except Exception as e:
                await client.send_message(CONTROL_CHAT_ID, LOCALES[CURRENT_LANG]["add_bots_error"].format(username=bot_info['username'], error=str(e)))
                
        await status_msg.edit(LOCALES[CURRENT_LANG]["add_bots_finish"].format(success=success_count, total=len(loaded_bots)))

    # 5. .start <kanal_id>
    elif text.startswith(".start ") and not (text.endswith("blok") or text.endswith("kick") or text.endswith("block")):
        target_input = text[7:].strip()
        if not target_input:
            await event.reply("❌ ID yoki username kiriting!")
            return
            
        status_msg = await event.reply("⏳ ...")
        
        try:
            active_channel = await client.get_entity(parse_chat_id(target_input))
            await status_msg.edit(f"📢 Kanal topildi: '{active_channel.title}' (ID: {active_channel.id})\n\nBloklashni boshlash uchun `.start blok` deb yozing.")
        except Exception as e:
            active_channel = None
            await status_msg.edit(LOCALES[CURRENT_LANG]["channel_not_found"].format(error=str(e)))

    # 6. .start blok
    elif text in [".start blok", ".start kick", ".start block"]:
        if not active_channel:
            await event.reply(LOCALES[CURRENT_LANG]["choose_channel"])
            return
            
        if blocking_active:
            await event.reply("⚠️ Jarayon allaqachon boshlangan!")
            return
            
        if not loaded_bots:
            await event.reply(LOCALES[CURRENT_LANG]["no_bots"])
            return
            
        status_msg = await event.reply("🚀 ...")
        
        admin_ids.clear()
        admin_ids.add(me_id)
        for bot_info in loaded_bots:
            admin_ids.add(bot_info['id'])
            
        try:
            async for admin in client.iter_participants(active_channel, filter=ChannelParticipantsAdmins):
                admin_ids.add(admin.id)
        except Exception as e:
            await event.reply(f"⚠️ Adminlarni aniqlashda ogohlantirish: {e}")
            
        # Reset qilish
        assigned_user_ids.clear()
        for token, state in bot_states.items():
            state['queue'].clear()
            state['banned_count'] = 0
            state['start_time'] = None
            state['is_banned_until'] = 0
            
        blocking_active = True
        
        # Workerlarni boshlash
        bot_tasks.clear()
        for bot_info in loaded_bots:
            task = asyncio.create_task(bot_worker(bot_info))
            bot_tasks.append(task)
            
        # Scraperloopni boshlash
        scraper_task = asyncio.create_task(scraper_loop())
        
        await status_msg.edit(LOCALES[CURRENT_LANG]["start_status"].format(admin_count=len(admin_ids)))

    # 7. .stop
    elif text == ".stop":
        if not blocking_active:
            await event.reply("⚠️ Faol jarayon yo'q.")
            return
            
        blocking_active = False
        
        if scraper_task:
            scraper_task.cancel()
            scraper_task = None
            
        for task in bot_tasks:
            task.cancel()
        bot_tasks.clear()
        
        for token, state in bot_states.items():
            state['queue'].clear()
            
        await event.reply(LOCALES[CURRENT_LANG]["stop_status"])


# =====================================================================
# VEB PANEL LOGIKASI & ENDPOINTLAR (FASTAPI)
# =====================================================================

class ChannelSelect(BaseModel):
    channel_id: str


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    # Veb UI html fayli
    html_content = """
    <!DOCTYPE html>
    <html lang="uz">
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
                        <i class="fa-solid fa-broom-ball"></i> <span data-i18n="title">Telegram Channel Cleaner</span>
                    </h1>
                    <p class="text-slate-400 text-sm mt-1" data-i18n="subtitle">Ko'p-botli kanalni tozalash va bloklash veb-paneli</p>
                </div>
                <div class="flex flex-wrap items-center gap-3">
                    <!-- Language Selector -->
                    <select id="lang-select" onchange="changeLanguage(this.value)" class="bg-slate-700 text-white font-semibold py-2 px-3 rounded-xl border border-slate-600 focus:outline-none focus:border-sky-500">
                        <option value="uz" selected>O'zbekcha (UZ)</option>
                        <option value="en">English (EN)</option>
                        <option value="ru">Русский (RU)</option>
                    </select>
                    
                    <button onclick="openQRModal()" class="bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold py-2 px-4 rounded-xl shadow-lg transition flex items-center gap-2">
                        <i class="fa-solid fa-qrcode"></i> <span data-i18n="add_acc">Yangi Akkaunt Qo'shish</span>
                    </button>
                    <button onclick="loadChannels()" class="bg-slate-700 hover:bg-slate-600 text-white font-semibold py-2 px-4 rounded-xl shadow transition flex items-center gap-2">
                        <i class="fa-solid fa-arrows-rotate"></i> <span data-i18n="reload_ch">Kanallarni Yangilash</span>
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
                        <p class="text-slate-400 text-sm font-medium" data-i18n="kicked_members">Bloklangan a'zolar</p>
                        <h3 id="stat-total-banned" class="text-2xl font-bold text-red-500 mt-1">0</h3>
                    </div>
                </div>
                <!-- Active Bots -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg flex items-center gap-4">
                    <div class="p-4 bg-green-500/10 text-green-400 rounded-xl">
                        <i class="fa-solid fa-robot text-2xl"></i>
                    </div>
                    <div>
                        <p class="text-slate-400 text-sm font-medium" data-i18n="active_bots">Faol botlar</p>
                        <h3 id="stat-active-bots" class="text-2xl font-bold text-green-400 mt-1">0 / 20</h3>
                    </div>
                </div>
                <!-- Target Channel -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg flex items-center gap-4 col-span-1 sm:col-span-2">
                    <div class="p-4 bg-sky-500/10 text-sky-400 rounded-xl">
                        <i class="fa-solid fa-bullhorn text-2xl"></i>
                    </div>
                    <div>
                        <p class="text-slate-400 text-sm font-medium" data-i18n="target_channel">Maqsadli kanal</p>
                        <h3 id="stat-target-channel" class="text-xl font-bold text-white mt-1 truncate" data-i18n="not_selected">Hech qanday kanal tanlanmagan</h3>
                    </div>
                </div>
            </div>

            <!-- Controls and Channels -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Channels List Panel -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg col-span-1 flex flex-col space-y-4">
                    <h2 class="text-lg font-semibold flex items-center gap-2"><i class="fa-solid fa-list-check text-sky-400"></i> <span data-i18n="select_channel_title">Kanalni Tanlash</span></h2>
                    <div class="flex-1 overflow-y-auto max-h-[300px] space-y-2 pr-1" id="channels-container">
                        <p class="text-slate-400 text-sm">...</p>
                    </div>
                </div>

                <!-- Process Manager -->
                <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg col-span-1 lg:col-span-2 flex flex-col justify-between space-y-6">
                    <div>
                        <h2 class="text-lg font-semibold flex items-center gap-2"><i class="fa-solid fa-sliders text-sky-400"></i> <span data-i18n="select_channel_title">Kanalni Tanlash</span></h2>
                        <p class="text-slate-400 text-sm mt-1" data-i18n="select_channel_desc">Kanalni tanlang va bloklash jarayonini shu yerdan boshqaring.</p>
                        
                        <div id="target-details" class="mt-4 p-4 bg-slate-900 rounded-xl border border-slate-700/50 hidden">
                            <p class="text-xs text-slate-400" data-i18n="selected_ch_lbl">Tanlangan kanal:</p>
                            <h4 id="target-title" class="font-bold text-white text-lg">Kanal nomi</h4>
                            <p id="target-id" class="text-xs text-sky-400 font-mono mt-0.5">ID: -100123456</p>
                        </div>
                    </div>

                    <div class="flex gap-4">
                        <button id="btn-start" onclick="startCleaning()" class="flex-1 bg-green-500 hover:bg-green-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-6 rounded-xl shadow-lg transition flex items-center justify-center gap-2 text-lg">
                            <i class="fa-solid fa-play"></i> <span data-i18n="btn_start">Boshlash</span>
                        </button>
                        <button id="btn-stop" onclick="stopCleaning()" class="flex-1 bg-red-500 hover:bg-red-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-6 rounded-xl shadow-lg transition flex items-center justify-center gap-2 text-lg">
                            <i class="fa-solid fa-stop"></i> <span data-i18n="btn_stop">To'xtatish</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Bots Performance Panel -->
            <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-lg">
                <h2 class="text-lg font-semibold flex items-center gap-2 mb-4"><i class="fa-solid fa-chart-line text-sky-400"></i> <span data-i18n="performance_title">20 ta botning holati va unumdorligi</span></h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-700 text-slate-400 text-sm">
                                <th class="pb-3 font-semibold" data-i18n="th_username">Bot foydalanuvchi nomi</th>
                                <th class="pb-3 font-semibold" data-i18n="th_status">Holati</th>
                                <th class="pb-3 font-semibold" data-i18n="th_kicked">Bloklanganlar</th>
                                <th class="pb-3 font-semibold" data-i18n="th_queue">Navbat hajmi</th>
                            </tr>
                        </thead>
                        <tbody id="bots-table-body" class="divide-y divide-slate-700/50">
                            <!-- Dinamik to'ldiriladi -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- QR Code Modal -->
        <div id="qr-modal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
            <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-2xl max-w-md w-full text-center space-y-4">
                <h3 class="text-xl font-bold text-white flex items-center justify-center gap-2"><i class="fa-brands fa-telegram text-sky-400"></i> <span data-i18n="modal_title">Telegram-ga QR orqali kirish</span></h3>
                <p class="text-slate-300 text-sm" data-i18n="modal_desc">Panelga yangi sessiya qo'shish uchun Telegram ilovasidan QR kodni skanerlang.</p>
                
                <div class="flex justify-center bg-white p-4 rounded-xl max-w-[240px] mx-auto" id="qr-code-container">
                    <div class="w-[200px] h-[200px] bg-slate-200 animate-pulse rounded flex items-center justify-center text-slate-500" data-i18n="modal_loading">QR kod yuklanmoqda...</div>
                </div>

                <div id="qr-status" class="text-sm font-medium text-amber-400">...</div>

                <div class="flex justify-end gap-2 pt-2 border-t border-slate-700/50">
                    <button onclick="closeQRModal()" class="bg-slate-700 hover:bg-slate-600 text-white font-medium py-2 px-4 rounded-xl transition" data-i18n="modal_close">Yopish</button>
                </div>
            </div>
        </div>

        <script>
            const TRANSLATIONS = {
                uz: {
                    title: "Telegram Channel Cleaner",
                    subtitle: "Ko'p-botli kanalni tozalash va bloklash veb-paneli",
                    add_acc: "Yangi Akkaunt Qo'shish",
                    reload_ch: "Kanallarni Yangilash",
                    kicked_members: "Bloklangan a'zolar",
                    active_bots: "Faol botlar",
                    target_channel: "Maqsadli kanal",
                    not_selected: "Hech qanday kanal tanlanmagan",
                    select_channel_title: "Kanalni Tanlash",
                    select_channel_desc: "Kanalni tanlang va bloklash jarayonini shu yerdan boshqaring.",
                    selected_ch_lbl: "Tanlangan kanal:",
                    btn_start: "Boshlash",
                    btn_stop: "To'xtatish",
                    performance_title: "20 ta botning holati va unumdorligi",
                    th_username: "Bot foydalanuvchi nomi",
                    th_status: "Holati",
                    th_kicked: "Bloklanganlar",
                    th_queue: "Navbat hajmi",
                    modal_title: "Telegram-ga QR orqali kirish",
                    modal_desc: "Panelga yangi sessiya qo'shish uchun Telegram ilovasidan QR kodni skanerlang.",
                    modal_loading: "QR kod yuklanmoqda...",
                    modal_close: "Yopish"
                },
                en: {
                    title: "Telegram Channel Cleaner",
                    subtitle: "Multi-bot channel cleaning and blocking web panel",
                    add_acc: "Add New Account",
                    reload_ch: "Refresh Channels",
                    kicked_members: "Blocked members",
                    active_bots: "Active bots",
                    target_channel: "Target channel",
                    not_selected: "No channel selected",
                    select_channel_title: "Select Channel",
                    select_channel_desc: "Select a channel and manage the blocking process from here.",
                    selected_ch_lbl: "Selected channel:",
                    btn_start: "Start",
                    btn_stop: "Stop",
                    performance_title: "Status and performance of 20 bots",
                    th_username: "Bot username",
                    th_status: "Status",
                    th_kicked: "Blocked count",
                    th_queue: "Queue size",
                    modal_title: "Login via QR to Telegram",
                    modal_desc: "Scan the QR code using your Telegram app to add a new session to the panel.",
                    modal_loading: "QR code loading...",
                    modal_close: "Close"
                },
                ru: {
                    title: "Telegram Channel Cleaner",
                    subtitle: "Веб-панель для очистки и блокировки каналов с помощью мульти-ботов",
                    add_acc: "Добавить Аккаунт",
                    reload_ch: "Обновить Каналы",
                    kicked_members: "Заблокированные участники",
                    active_bots: "Активные боты",
                    target_channel: "Целевой канал",
                    not_selected: "Канал не выбран",
                    select_channel_title: "Выбор Канала",
                    select_channel_desc: "Выберите канал и управляйте процессом блокировки отсюда.",
                    selected_ch_lbl: "Выбранный канал:",
                    btn_start: "Начать",
                    btn_stop: "Остановить",
                    performance_title: "Состояние и производительность 20 ботов",
                    th_username: "Имя бота",
                    th_status: "Статус",
                    th_kicked: "Заблокировано",
                    th_queue: "Размер очереди",
                    modal_title: "Вход в Telegram по QR-коду",
                    modal_desc: "Отсканируйте QR-код через приложение Telegram, чтобы добавить новую сессию.",
                    modal_loading: "Загрузка QR-кода...",
                    modal_close: "Закрыть"
                }
            };

            let currentLang = localStorage.getItem("app_lang") || "uz";
            document.getElementById("lang-select").value = currentLang;

            function changeLanguage(lang) {
                currentLang = lang;
                localStorage.setItem("app_lang", lang);
                
                // Serverga ham xabar berish
                fetch("/api/lang", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ lang: lang })
                });

                document.querySelectorAll("[data-i18n]").forEach(elem => {
                    const key = elem.getAttribute("data-i18n");
                    if (TRANSLATIONS[lang][key]) {
                        elem.innerText = TRANSLATIONS[lang][key];
                    }
                });
            }

            // Dastlabki tilni o'rnatish
            setTimeout(() => changeLanguage(currentLang), 100);

            let currentSelectedChannel = null;
            let statusInterval = null;

            async function loadChannels() {
                const container = document.getElementById("channels-container");
                container.innerHTML = `<div class="text-slate-400 text-sm animate-pulse flex items-center gap-2"><i class="fa-solid fa-spinner animate-spin"></i> ...</div>`;
                
                try {
                    const response = await fetch("/api/channels");
                    const channels = await response.json();
                    
                    if (channels.length === 0) {
                        container.innerHTML = `<p class="text-slate-400 text-sm">Kanal topilmadi.</p>`;
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
                                <p class="text-xs text-slate-400">${ch.username ? "@" + ch.username : "Private"}</p>
                            </div>
                            <span class="text-xs text-sky-400 font-mono">${ch.id}</span>
                        `;
                        container.appendChild(div);
                    });
                } catch(e) {
                    container.innerHTML = `<p class="text-red-400 text-sm">Xato: ${e.message}</p>`;
                }
            }

            function selectChannel(ch) {
                currentSelectedChannel = ch;
                const details = document.getElementById("target-details");
                details.classList.remove("hidden");
                document.getElementById("target-title").innerText = ch.title;
                document.getElementById("target-id").innerText = "ID: " + ch.id;
            }

            async function startCleaning() {
                if (!currentSelectedChannel) {
                    alert("Avval kanalni tanlang!");
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
                        alert("Muvaffaqiyatli boshlandi!");
                    } else {
                        alert("Xato: " + res.message);
                    }
                } catch(e) {
                    alert("Xato: " + e.message);
                }
            }

            async function stopCleaning() {
                try {
                    const response = await fetch("/api/stop", { method: "POST" });
                    const res = await response.json();
                    if (res.status === "stopped") {
                        alert("To'xtatildi!");
                    }
                } catch(e) {
                    alert("Xato: " + e.message);
                }
            }

            async function updateStats() {
                try {
                    const response = await fetch("/api/stats");
                    const data = await response.json();
                    
                    document.getElementById("stat-total-banned").innerText = data.total_banned;
                    document.getElementById("stat-active-bots").innerText = `${data.active_bots_count} / ${data.total_bots_count}`;
                    
                    if (data.active_channel) {
                        document.getElementById("stat-target-channel").innerText = `${data.active_channel.title} (ID: ${data.active_channel.id})`;
                    } else {
                        document.getElementById("stat-target-channel").innerText = TRANSLATIONS[currentLang]["not_selected"];
                    }

                    document.getElementById("btn-start").disabled = data.blocking_active;
                    document.getElementById("btn-stop").disabled = !data.blocking_active;

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
                    console.error("Stats xatosi:", e);
                }
            }

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
                
                container.innerHTML = `<div class="w-[200px] h-[200px] flex items-center justify-center text-slate-500"><i class="fa-solid fa-spinner animate-spin text-xl mr-2"></i> ...</div>`;
                status.innerText = "Kutilmoqda...";
                
                try {
                    const response = await fetch("/api/qr/start", { method: "POST" });
                    
                    qrInterval = setInterval(async () => {
                        const stResp = await fetch("/api/qr/status");
                        const stData = await stResp.json();
                        
                        status.innerText = "Holat: " + stData.status;
                        
                        if (stData.qr_base64) {
                            container.innerHTML = `<img src="${stData.qr_base64}" class="w-[200px] h-[200px]" />`;
                        }
                        
                        if (stData.status === "authorized") {
                            clearInterval(qrInterval);
                            status.className = "text-sm font-medium text-green-400";
                            status.innerText = "Muvaffaqiyatli ulandi! Tizim qayta yuklanmoqda...";
                            setTimeout(() => closeQRModal(), 3000);
                        } else if (stData.status === "failed") {
                            clearInterval(qrInterval);
                            status.className = "text-sm font-medium text-red-400";
                            status.innerText = "Xato: " + stData.error;
                        }
                    }, 2000);
                } catch(e) {
                    status.innerText = "Xato: " + e.message;
                }
            }

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
    global blocking_active, active_channel, bot_states, START_TIME, CURRENT_LANG
    
    total_banned = sum(b['banned_count'] for b in bot_states.values())
    active_bots_count = sum(1 for b in bot_states.values() if time.time() >= b['is_banned_until'])
    
    bots_list = []
    for token, b in bot_states.items():
        status = "Active"
        wait_remaining = max(0, int(b['is_banned_until'] - time.time()))
        if wait_remaining > 0:
            status = f"Spam Blocked (wait {format_duration(wait_remaining, CURRENT_LANG)})"
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
            "title": active_channel.title if active_channel else "No Channel Selected"
        } if active_channel else None,
        "total_banned": total_banned,
        "active_bots_count": active_bots_count,
        "total_bots_count": len(bot_states),
        "uptime": format_duration(uptime_sec, CURRENT_LANG),
        "bots": bots_list
    }


class LangUpdate(BaseModel):
    lang: str


@app.post("/api/lang")
async def web_change_lang(data: LangUpdate):
    global CURRENT_LANG
    if data.lang in LOCALES:
        CURRENT_LANG = data.lang
        print(f"🌐 Veb panel tili o'zgartirildi: {CURRENT_LANG}")
        return {"status": "ok", "lang": CURRENT_LANG}
    return JSONResponse(content={"status": "error", "message": "Invalid language"}, status_code=400)


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
        print(f"Kanal yig'ishda xatolik: {e}")
    return channels


@app.post("/api/start")
async def web_start_cleaning(data: ChannelSelect):
    global active_channel, me_id, blocking_active, bot_tasks, scraper_task, admin_ids, assigned_user_ids
    
    try:
        active_channel = await client.get_entity(parse_chat_id(data.channel_id))
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": f"Kanal topilmadi: {str(e)}"}, status_code=400)
        
    if blocking_active:
        return {"status": "already_running"}
        
    admin_ids.clear()
    admin_ids.add(me_id)
    for bot_info in loaded_bots:
        admin_ids.add(bot_info['id'])
        
    try:
        async for admin in client.iter_participants(active_channel, filter=ChannelParticipantsAdmins):
            admin_ids.add(admin.id)
    except Exception as e:
        print(f"Web start admin tekshirishda ogohlantirish: {e}")
        
    assigned_user_ids.clear()
    for token, state in bot_states.items():
        state['queue'].clear()
        state['banned_count'] = 0
        state['start_time'] = None
        state['is_banned_until'] = 0
        
    blocking_active = True
    
    # Workerlarni boshlash
    bot_tasks.clear()
    for bot_info in loaded_bots:
        task = asyncio.create_task(bot_worker(bot_info))
        bot_tasks.append(task)
        
    # Scraperloopni boshlash
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
    """Veb QR kirish uchun fonda ishlovchi vazifa."""
    global qr_client, qr_login_instance, qr_state
    
    try:
        user = await qr_login_instance.wait(timeout=60)
        qr_state["status"] = "authorized"
        qr_state["user"] = f"{user.first_name} (@{user.username})"
        print(f"🎉 Web QR login muvaffaqiyatli: {qr_state['user']}")
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
        
        # QR-kod rasm yaratish
        qr_img = qrcode.make(qr_login_instance.url)
        buffered = io.BytesIO()
        qr_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        qr_state["qr_base64"] = f"data:image/png;base64,{img_str}"
        qr_state["status"] = "waiting"
        
        # Fondagi vazifani boshlash
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
    """Har 10 daqiqada Render serveri uxlab qolmasligi uchun o'ziga so'rov yuborish."""
    await asyncio.sleep(30)
    
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        port = int(os.getenv("PORT", 8080))
        render_url = f"http://localhost:{port}"
        
    print(f"🔄 Render self-ping loop boshlandi: {render_url}")
    
    while True:
        try:
            async with http_session.get(render_url) as resp:
                if resp.status == 200:
                    print(f"✅ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Render self-ping muvaffaqiyatli!")
                else:
                    print(f"⚠️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Render self-ping status: {resp.status}")
        except Exception as e:
            print(f"❌ Render self-ping xatolik: {e}")
            
        # 10 daqiqa kutish (600 soniya)
        await asyncio.sleep(600)


# =====================================================================
# SYSTEM STARTUP & ASOSIY EVENT LOOP
# =====================================================================

async def main():
    global me_id, http_session
    print("==================================================")
    print("  Telegram Kanalini Tozalash Skripti (Multi-Bot)   ")
    print("==================================================")
    
    # aiohttp sessiyasini yuklash
    http_session = aiohttp.ClientSession()
    
    # Botlarni yuklash
    await init_bots()
    
    # Userbotni boshlash
    await client.start()
    me = await client.get_me()
    me_id = me.id
    print(f"🎉 Userbot ishga tushdi: {me.first_name} (@{me.username})")
    print("Komandalar kutilmoqda...")
    
    # FastAPI Serverini boshlash
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    print(f"🌐 Veb-panel ishga tushdi: http://localhost:{port}")
    
    # Self-ping vazifasini boshlash
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
        print("\n👋 Skript to'xtatildi.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Xato: {e}")
        sys.exit(1)
