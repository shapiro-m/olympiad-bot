import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import logging

# ВКЛЮЧАЕМ ЖУРНАЛ
logging.basicConfig(level=logging.INFO)

# ЗАГРУЖАЕМ ТОКЕН
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ ТОКЕН НЕ НАЙДЕН!")

# СОЗДАЁМ БОТА
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# БАЗА ДАННЫХ
DB_PATH = "olympiads.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS olymps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            reg_date TEXT, 
            exam_date TEXT,
            category TEXT,
            description TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER, 
            olymp_id INTEGER, 
            PRIMARY KEY (user_id, olymp_id)
        )
    """)
    conn.commit()
    conn.close()
    print(f"✅ База данных создана")

async def send_reminder(user_id: int, title: str, text: str):
    try:
        await bot.send_message(user_id, f"🔔 <b>{title}</b>\n\n{text}", parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не отправилось напоминание: {e}")

async def send_day_before(user_id: int, olymp_name: str, event_type: str):
    try:
        await bot.send_message(
            user_id, 
            f"⏰ <b>ЗАВТРА!</b>\n\n{event_type} олимпиады <b>{olymp_name}</b> уже завтра!",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Не отправилось напоминание за день: {e}")

def load_reminders_into_scheduler():
    scheduler.remove_all_jobs()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.user_id, o.name, o.reg_date, o.exam_date 
        FROM subscriptions s 
        JOIN olymps o ON s.olymp_id = o.id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    now = datetime.now()
    for user_id, name, reg_str, exam_str in rows:
        reg_dt = datetime.strptime(reg_str, "%Y-%m-%d %H:%M")
        exam_dt = datetime.strptime(exam_str, "%Y-%m-%d %H:%M")
        
        if reg_dt > now:
            scheduler.add_job(
                send_reminder, 
                'date', 
                run_date=reg_dt, 
                args=[user_id, "ВРЕМЯ РЕГИСТРАЦИИ!", f"Открылась регистрация на олимпиаду: {name}"]
            )
            day_before_reg = reg_dt - timedelta(days=1)
            if day_before_reg > now:
                scheduler.add_job(
                    send_day_before, 
                    'date', 
                    run_date=day_before_reg, 
                    args=[user_id, name, "Регистрация"]
                )
        
        if exam_dt > now:
            scheduler.add_job(
                send_reminder, 
                'date', 
                run_date=exam_dt, 
                args=[user_id, "НАЧАЛСЯ ТУР!", f"Прямо сейчас стартует олимпиада: {name}"]
            )
            day_before_exam = exam_dt - timedelta(days=1)
            if day_before_exam > now:
                scheduler.add_job(
                    send_day_before, 
                    'date', 
                    run_date=day_before_exam, 
                    args=[user_id, name, "Тур"]
                )

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.reply(
        "👋 Привет! Я твой олимпиадный помощник!\n\n"
        "➕ <b>Как добавить олимпиаду:</b>\n"
        "`/add Название | ГГГГ-ММ-ДД ЧЧ:ММ | ГГГГ-ММ-ДД ЧЧ:ММ | Категория | Описание`\n\n"
        "📅 Список всех олимпиад: /list\n"
        "🔍 Посмотреть одну олимпиаду: /view ID\n"
        "🗑 Удалить олимпиаду: /delete ID\n"
        "❓ Помощь: /help",
        parse_mode="HTML"
    )

@dp.message(Command("add"))
async def cmd_add(message: Message):
    try:
        parts = message.text.split("/add ")[1].split("|")
        name = parts[0].strip()
        reg_date = parts[1].strip()
        exam_date = parts[2].strip()
        category = parts[3].strip() if len(parts) > 3 else "Другое"
        description = parts[4].strip() if len(parts) > 4 else ""
        
        datetime.strptime(reg_date, "%Y-%m-%d %H:%M")
        datetime.strptime(exam_date, "%Y-%m-%d %H:%M")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO olymps (name, reg_date, exam_date, category, description) VALUES (?, ?, ?, ?, ?)", 
            (name, reg_date, exam_date, category, description)
        )
        conn.commit()
        conn.close()
        
        load_reminders_into_scheduler()
        await message.reply(f"✅ Олимпиада <b>{name}</b> успешно добавлена!", parse_mode="HTML")
    except Exception as e:
        await message.reply(
            f"❌ Ошибка! Пиши вот так:\n"
            "`/add Название | 2026-08-15 14:00 | 2026-08-20 10:00 | Математика | Описание`",
            parse_mode="HTML"
        )

@dp.message(Command("list"))
async def cmd_list(message: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, category FROM olymps ORDER BY name")
    olymps = cursor.fetchall()
    cursor.execute("SELECT olymp_id FROM subscriptions WHERE user_id = ?", (message.chat.id,))
    user_subs = [r[0] for r in cursor.fetchall()]
    conn.close()
    
    if not olymps:
        await message.reply("📭 Список олимпиад пуст. Добавь первую через /add!")
        return

    keyboard_buttons = []
    for o_id, name, category in olymps:
        status = "✅" if o_id in user_subs else "❌"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{status} {name} ({category})", 
                callback_data=f"toggle_{o_id}"
            )
        ])
    
    await message.reply(
        "📅 <b>Твои олимпиады:</b>\n✅ - подписан, ❌ - не подписан",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_subscription(callback: CallbackQuery):
    olymp_id = int(callback.data.split("_")[1])
    user_id = callback.message.chat.id
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM subscriptions WHERE user_id = ? AND olymp_id = ?", (user_id, olymp_id))
    if cursor.fetchone():
        cursor.execute("DELETE FROM subscriptions WHERE user_id = ? AND olymp_id = ?", (user_id, olymp_id))
        txt = "❌ Подписка отменена"
    else:
        cursor.execute("INSERT INTO subscriptions (user_id, olymp_id) VALUES (?, ?)", (user_id, olymp_id))
        txt = "✅ Вы подписались!"
    
    conn.commit()
    
    cursor.execute("SELECT id, name, category FROM olymps ORDER BY name")
    olymps = cursor.fetchall()
    cursor.execute("SELECT olymp_id FROM subscriptions WHERE user_id = ?", (user_id,))
    user_subs = [r[0] for r in cursor.fetchall()]
    conn.close()
    
    keyboard_buttons = []
    for o_id, name, category in olymps:
        status = "✅" if o_id in user_subs else "❌"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{status} {name} ({category})", 
                callback_data=f"toggle_{o_id}"
            )
        ])
    
    load_reminders_into_scheduler()
    await callback.answer(txt)
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))

@dp.message(Command("view"))
async def cmd_view(message: Message):
    try:
        olymp_id = int(message.text.split()[1])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name, reg_date, exam_date, category, description FROM olymps WHERE id = ?", (olymp_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            name, reg_date, exam_date, category, description = result
            text = f"📚 <b>{name}</b>\n\n"
            text += f"📂 Категория: {category}\n"
            text += f"📅 Регистрация: {reg_date}\n"
            text += f"🏁 Тур: {exam_date}\n"
            if description:
                text += f"\n📝 Описание: {description}\n"
            
            await message.reply(text, parse_mode="HTML")
        else:
            await message.reply("❌ Олимпиада не найдена")
    except:
        await message.reply("❌ Используй: `/view ID`", parse_mode="HTML")

@dp.message(Command("delete"))
async def cmd_delete(message: Message):
    try:
        olymp_id = int(message.text.split()[1])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM olymps WHERE id = ?", (olymp_id,))
        result = cursor.fetchone()
        if not result:
            await message.reply("❌ Олимпиада не найдена")
            conn.close()
            return
        
        name = result[0]
        
        cursor.execute("DELETE FROM subscriptions WHERE olymp_id = ?", (olymp_id,))
        cursor.execute("DELETE FROM olymps WHERE id = ?", (olymp_id,))
        conn.commit()
        conn.close()
        
        load_reminders_into_scheduler()
        await message.reply(f"✅ Олимпиада <b>{name}</b> удалена!", parse_mode="HTML")
    except:
        await message.reply("❌ Используй: `/delete ID`", parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
🤖 <b>Я - бот-напоминалка для олимпиад!</b>

<b>📚 Команды:</b>

/add Название | ГГГГ-ММ-ДД ЧЧ:ММ | ГГГГ-ММ-ДД ЧЧ:ММ | Категория | Описание
    ➕ Добавить новую олимпиаду

/list
    📋 Показать все олимпиады

/view ID
    🔍 Посмотреть детали олимпиады

/delete ID
    🗑 Удалить олимпиаду

/start
    👋 Начать работу с ботом

<b>⏰ Напоминания:</b>
• В день регистрации
• За день до регистрации
• В день тура
• За день до тура
"""
    await message.reply(help_text, parse_mode="HTML")

async def main():
    init_db()
    load_reminders_into_scheduler()
    scheduler.start()
    print("🤖 БОТ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())









