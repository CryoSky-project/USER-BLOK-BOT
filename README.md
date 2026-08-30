# 🤖 Telegram Userbot & Multi-Bot Channel Cleaner + Web Panel 🧹🌐

Ushbu loyiha eski yoki keraksiz Telegram kanallarini sotishga yoki boshqa maqsadlarga tayyorlash uchun uning a'zolarini (odamlarini) tez va xavfsiz bloklab tozalashga mo'ljallangan.

Loyiha **1 Userbot** (kanal a'zolarini yig'ib, botlarga taqsimlash uchun), **20 ta umumiy Bot** (odamlarni Telegram Rate Limit cheklovlaridan oshmay bloklash uchun) va **FastAPI Veb-Paneli** asosida ishlaydi.

---

## 📁 Fayllar tuzilishi va tavsifi 📑

---

### 1. 🚀 `main.py`
* **Bu nima uchun kerak:** Loyihaning **eng asosiy ishchi skripti**.
* **Nima qiladi:** 
  * **Ko'p-botli parallel bloklash**: Barcha botlar parallel (concurrent) ravishde ishlaydi. Har biri 2 soniyada 1 kishini bloklaydi. Umumiy tezlik: **daqiqasiga 600 kishi**.
  * **Alifboviy qidiruv (10k Limit Bypass)**: Telegram-ning 10,000 kishilik cheklovidan o'tish uchun a'zolarni dastlab oddiy, so'ngra **ingliz va rus alifbosining harflari hamda raqamlari bo'yicha** (`search=char`) avtomatik ravishda qidirib topadi.
  * **4 soniyalik navbat yig'ish**: Har 4 soniyada 150 kishining ID-sini yig'ib, botlarning navbatini to'ldiradi.
  * **Ko'p tilli qo'llab-quvvatlash (Lang Support)**: Tizim to'liq **O'zbek (uz)**, **Ingliz (en)** va **Rus (ru)** tillarida ishlaydi. Tilni `.lang <kod>` komandasi orqali yoki veb-paneldan o'zgartirish mumkin.
  * **Veb-panel serveri**: O'z ichida FastAPI serverini (sukut bo'yicha `8080` portida) ishga tushiradi.
  * **Render platformasiga moslik**: Render bergan `PORT` o'zgaruvchisini avtomatik o'qiydi va **har 10 daqiqada o'ziga HTTP GET so'rovini yuborib (Self-Ping)**, serverning o'chib qolmasligini (uxlamasligini) ta'minlaydi. 🔄

---

### 2. ⚙️ `config.py`
* **Bu nima uchun kerak:** Loyihaning barcha **sozlamalari va ma'lumotlarini saqlaydigan markaziy fayl**.
* **Nima qiladi:**
  * `.env` faylidan `API_ID` va `API_HASH` o'qiydi (topilmasa sukut bo'yicha qiymatlarni qo'llaydi).
  * **20 ta botning tokenlarini** to'g'ridan-to'g'ri o'zida saqlaydi (`BOT_TOKENS`).
  * **20 Sessiya rotatsiyasi**: Oxirgi 20 ta sessiya faylini nazorat qilib, eng yangisini avtomatik ravishda topib, yuklaydi.

---

### 3. 🔑 `fix.py`
* **Bu nima uchun kerak:** Telefon raqami orqali kirishga mo'ljallangan skript (sobiq `login.py`).
* **Nima qiladi:** Har bir akkaunt uchun telefon raqami bilan nomlanadigan sessiya faylini (masalan: `session_998901234567.session`) yaratadi.

---

### 4. 🔑 `qr.py`
* **Bu nima uchun kerak:** Terminalda QR-kodni skanerlab kirish skripti (sobiq `qr_login.py`).

---

### 5. 🛠️ `auth_step.py`
* **Bu nima uchun kerak:** Tizimga kirish logikasi uchun yordamchi fayl.

---

## 🌐 Veb-panel imkoniyatlari 📊
Skriptni yoqqandan so'ng brauzer orqali `http://localhost:8080` yoki Render havolangiz bo'yicha kirsangiz, quyidagi imkoniyatlar mavjud bo'ladi:

1. **📈 Interaktiv Dashbord**: Bloklanganlarning umumiy soni, faol botlarning soni va kanal ma'lumotlari real vaqtda yangilanib turadi.
2. **📱 QR-kod orqali vebdan kirish**: Sayt sahifasida QR-kod paydo bo'ladi. Uni telefon bilan skanerlab, terminalsiz yangi Telegram sessiyalarini tezda qo'shish mumkin.
3. **🤖 Botlarni boshqarish**: 20 ta botning har birining holatini (Faol, Spam-blok, Kutish vaqti) va shaxsiy bloklanganlar sonini ko'rish mumkin.
4. **📢 Kanallar ro'yxati**: Userbot qo'shilgan barcha kanallar ro'yxati saytda chiqadi, havola yozmasdan bir bosish bilan tozalashni boshlashingiz mumkin.
5. **🌐 Til tanlash**: Veb-panel interfeysini o'zbekcha, inglizcha va ruscha tillarga bir soniyada o'zgartirish mumkin.

---

## 💬 Telegram Komandalari 📌
Skript ishga tushganda nazorat chatida quyidagi komandalar ishlaydi:
* `.help` — Komandalar ro'yxati va tavsifini ko'rsatish.
* `.ping` — Ping tezligi va tizimning ish vaqtini (uptime) ko'rsatish.
* `.lang <uz|en|ru>` — Tizimning ishchi tilini o'zgartirish.
* `.add bots <kanal_id>` — 20 ta botni kanalga qo'shib, admin qilish.
* `.start <kanal_id>` — Maqsadli kanalni belgilash.
* `.start blok` — Bloklashni boshlash.
* `.stop` — Bloklashni to'xtatish.

---
Ishingizga omad tilaymiz! 🚀🔥
