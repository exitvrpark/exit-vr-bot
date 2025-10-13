import os, asyncio, aiosqlite
from datetime import datetime
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("7997746340:AAFn0_Yy7vd-n5oMM9Cjl_Jg9HBbxgx2X8A")
CHANNEL_USERNAME = os.getenv("@exit_vr")
ADMIN_IDS = {1290147421}


DB = "exit_vr.sqlite"
ASK_NAME, ASK_AGE, ASK_PHONE = range(3)

# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            chat_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            phone TEXT,
            points INTEGER DEFAULT 0,
            subscribed INTEGER DEFAULT 0,
            got_signup_bonus INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        await db.commit()

async def get_user(chat_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,))
        return await cur.fetchone()

async def upsert_user(chat_id, **fields):
    keys = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    values = list(fields.values())
    async with aiosqlite.connect(DB) as db:
        # insert or update
        exist = await db.execute("SELECT chat_id FROM users WHERE chat_id=?", (chat_id,))
        if await exist.fetchone():
            sets = ", ".join(f"{k}=?" for k in fields)
            await db.execute(f"UPDATE users SET {sets} WHERE chat_id=?", (*values, chat_id))
        else:
            await db.execute(
                f"INSERT INTO users(chat_id,{keys},created_at) VALUES (?,?,?,?)".replace("?,?,?,?", "?," + ",".join("?"*len(fields)) + ",?"),
                (chat_id, *values, datetime.utcnow().isoformat())
            )
        await db.commit()

async def add_points(chat_id, amount):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET points = COALESCE(points,0) + ? WHERE chat_id=?",(amount,chat_id))
        await db.commit()

# ---------- Utils ----------
def is_admin(user_id:int)->bool:
    return user_id in ADMIN_IDS

async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id:int)->bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member","administrator","creator")
    except Exception:
        # если канал приватный — используйте chat_id канала
        return False

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await init_db()
    chat_id = update.effective_chat.id
    user = await get_user(chat_id)
    if user:
        await update.message.reply_text("С возвращением в EXIT VR! Напишите /профиль или /баланс.")
        return ConversationHandler.END
    await update.message.reply_text("Привет! Давай познакомимся. Как тебя зовут?")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()[:64]
    await update.message.reply_text("Сколько тебе лет?")
    return ASK_AGE

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text.strip())
    except:
        return await update.message.reply_text("Нужна цифра. Сколько лет?")
    context.user_data["age"] = age
    kb = [[KeyboardButton("Отправить номер телефона", request_contact=True)]]
    await update.message.reply_text(
        "Остался номер телефона (для брони и бонусов):",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    await upsert_user(update.effective_chat.id,
                      name=context.user_data["name"],
                      age=context.user_data["age"],
                      phone=phone)
    await update.message.reply_text("Спасибо! Теперь подпишись на наш канал, чтобы получить 1000 бонусов:\n" + CHANNEL_USERNAME,
                                    reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Когда подпишешься — набери команду /проверка")
    return ConversationHandler.END

async def check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user(chat_id)
    if not user:
        return await update.message.reply_text("Сначала /start для регистрации.")
    subscribed = await check_subscription(context, chat_id)
    if not subscribed:
        return await update.message.reply_text("Похоже, ты ещё не подписан. Подпишись и повтори /проверка.")
    # отметить подписку
    await upsert_user(chat_id, subscribed=1)
    # бонус 1000 — один раз
    got_bonus = user[6] if user else 0
    if not got_bonus:
        await add_points(chat_id, 1000)
        await upsert_user(chat_id, got_signup_bonus=1)
        await update.message.reply_text("Готово! +1000 бонусов за подписку 🎉\nКоманда /баланс покажет сумму.")
    else:
        await update.message.reply_text("Подписка подтверждена! Бонус уже начисляли ранее.")
        
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user(chat_id)
    if not user:
        return await update.message.reply_text("Сначала /start.")
    points = user[4] or 0
    await update.message.reply_text(f"Твой баланс: {points} бонусов (1 бонус = 1 ₽).")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_chat.id)
    if not user:
        return await update.message.reply_text("Сначала /start.")
    _, chat_id, name, age, phone, points, subscribed, got_bonus, created_at = (
        None, user[0], user[1], user[2], user[3], user[4], user[5], user[6], user[7]
    )
    sub = "да" if subscribed else "нет"
    await update.message.reply_text(
        f"Профиль:\nИмя: {name}\nВозраст: {age}\nТелефон: {phone}\nПодписка: {sub}\nБонусы: {points}\nС нами с: {created_at}"
    )

# ----- Admin: начислить/списать/рассылка -----
async def addpoints_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /начислить <chat_id> <сумма>")
    chat_id = int(context.args[0]); amount = int(context.args[1])
    await add_points(chat_id, amount)
    await update.message.reply_text(f"Начислил {amount} бонусов пользователю {chat_id}.")

async def deduct_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /списать <chat_id> <сумма>")
    chat_id = int(context.args[0]); amount = int(context.args[1])
    await add_points(chat_id, -amount)
    await update.message.reply_text(f"Списал {amount} бонусов у пользователя {chat_id}.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = " ".join(context.args).strip()
    if not text:
        return await update.message.reply_text("Формат: /broadcast Текст рассылки")
    # пройтись по всем пользователям
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT chat_id FROM users")
        rows = await cur.fetchall()
    sent = 0
    for (cid,) in rows:
        try:
            await context.bot.send_message(cid, text)
            sent += 1
        except: pass
    await update.message.reply_text(f"Рассылка отправлена {sent} пользователям.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    reg = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AGE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_PHONE:[MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), ask_phone)],
        },
        fallbacks=[]
    )
    app.add_handler(reg)
    app.add_handler(CommandHandler("проверка", check_sub))
    app.add_handler(CommandHandler("баланс", balance))
    app.add_handler(CommandHandler("профиль", profile))

    # admin
    app.add_handler(CommandHandler("начислить", addpoints_cmd))
    app.add_handler(CommandHandler("списать", deduct_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.run_polling()

if __name__ == "__main__":
    asyncio.run(init_db())
    main()
