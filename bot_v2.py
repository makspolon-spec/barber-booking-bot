import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройки берутся из переменных окружения (в коде секретов нет)
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))  # Telegram ID мастера
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Kyiv"))
REMIND_DAY_HOURS = 24  # за сколько часов слать первое напоминание

def now_local():
    return datetime.now(TZ)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SERVICES = ["Стрижка", "Борода", "Стрижка + борода"]
SLOTS = [f"{h}:00" for h in range(10, 20)]

# --- база данных ---
db = sqlite3.connect("bookings.db")
db.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    service TEXT,
    day TEXT,
    slot TEXT,
    contact TEXT,
    status TEXT DEFAULT 'new',
    remind_day INTEGER DEFAULT 0,
    remind_hour INTEGER DEFAULT 0,
    UNIQUE(day, slot)
)
""")
db.commit()

class Booking(StatesGroup):
    contact = State()

menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Записаться")],
        [KeyboardButton(text="💈 Услуги"), KeyboardButton(text="💰 Цены")],
        [KeyboardButton(text="📍 Контакты")],
    ],
    resize_keyboard=True,
)

# --- inline-клавиатуры ---
def services_kb():
    b = InlineKeyboardBuilder()
    for s in SERVICES:
        b.button(text=s, callback_data=f"svc:{s}")
    b.adjust(1)
    return b.as_markup()

def days_kb():
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        d = now_local().date() + timedelta(days=i)
        b.button(text=d.strftime("%d.%m"), callback_data=f"day:{d.isoformat()}")
    b.adjust(5)
    return b.as_markup()

def slots_kb(day):
    taken = {r[0] for r in db.execute("SELECT slot FROM bookings WHERE day=?", (day,))}
    b = InlineKeyboardBuilder()
    for s in SLOTS:
        if s not in taken:
            b.button(text=s, callback_data=f"slot:{s}")
    b.adjust(4)
    return b.as_markup()

def visit_time(day, slot):
    return datetime.strptime(f"{day} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)

# --- обработчики ---
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Выберите, что вас интересует:", reply_markup=menu)

@dp.message(Command("id"))
async def show_id(message: Message):
    await message.answer(f"Ваш ID: {message.from_user.id}")

@dp.message(F.text == "📝 Записаться")
async def book_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите услугу:", reply_markup=services_kb())

@dp.callback_query(F.data.startswith("svc:"))
async def pick_service(call: CallbackQuery, state: FSMContext):
    await state.update_data(service=call.data.split(":", 1)[1])
    await call.message.edit_text("Выберите день:", reply_markup=days_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("day:"))
async def pick_day(call: CallbackQuery, state: FSMContext):
    day = call.data.split(":", 1)[1]
    await state.update_data(day=day)
    kb = slots_kb(day)
    if not kb.inline_keyboard:
        await call.message.edit_text("На этот день мест нет, выберите другой:", reply_markup=days_kb())
    else:
        await call.message.edit_text(f"Свободное время на {day}:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("slot:"))
async def pick_slot(call: CallbackQuery, state: FSMContext):
    await state.update_data(slot=call.data.split(":", 1)[1])
    await state.set_state(Booking.contact)
    await call.message.edit_text("Напишите ваше имя и номер телефона:")
    await call.answer()

@dp.message(Booking.contact)
async def finish(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    try:
        cur = db.execute(
            "INSERT INTO bookings (user_id, service, day, slot, contact) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, data["service"], data["day"], data["slot"], message.text),
        )
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("Это время только что заняли. Начните запись заново.", reply_markup=menu)
        return
    booking_id = cur.lastrowid
    if OWNER_ID:
        text = (
            f"🔔 Новая запись!\n{data['service']}\n"
            f"{data['day']} в {data['slot']}\nКонтакт: {message.text}"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Подтвердить", callback_data=f"ok:{booking_id}")
        kb.button(text="❌ Отменить", callback_data=f"no:{booking_id}")
        kb.adjust(2)
        await bot.send_message(OWNER_ID, text, reply_markup=kb.as_markup())
    await message.answer(
        f"Заявка отправлена: {data['day']} в {data['slot']} ({data['service']}). "
        "Мастер подтвердит запись, мы пришлём сообщение.",
        reply_markup=menu,
    )

@dp.callback_query(F.data.startswith("ok:"))
async def confirm(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Нет доступа", show_alert=True)
        return
    bid = int(call.data.split(":")[1])
    row = db.execute("SELECT user_id, service, day, slot FROM bookings WHERE id=?", (bid,)).fetchone()
    if not row:
        await call.answer("Запись не найдена", show_alert=True)
        return
    # если до визита меньше суток, напоминание «за день» не нужно
    left = visit_time(row[2], row[3]) - now_local()
    skip_day = 1 if left <= timedelta(hours=24) else 0
    db.execute("UPDATE bookings SET status='confirmed', remind_day=? WHERE id=?", (skip_day, bid))
    db.commit()
    await bot.send_message(row[0], f"✅ Мастер подтвердил вашу запись: {row[2]} в {row[3]} ({row[1]}). Ждём вас!")
    await call.message.edit_text(call.message.text + "\n\n✅ Подтверждено")
    await call.answer()

@dp.callback_query(F.data.startswith("no:"))
async def decline(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Нет доступа", show_alert=True)
        return
    bid = int(call.data.split(":")[1])
    row = db.execute("SELECT user_id, service, day, slot FROM bookings WHERE id=?", (bid,)).fetchone()
    if not row:
        await call.answer("Запись не найдена", show_alert=True)
        return
    db.execute("DELETE FROM bookings WHERE id=?", (bid,))
    db.commit()
    await bot.send_message(row[0], f"❌ К сожалению, запись на {row[2]} в {row[3]} отменена. Выберите другое время через «📝 Записаться».")
    await call.message.edit_text(call.message.text + "\n\n❌ Отменено")
    await call.answer()

@dp.message(Command("bookings"))
async def list_bookings(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    rows = db.execute(
        "SELECT day, slot, service, contact, status FROM bookings WHERE day >= ? ORDER BY day, slot",
        (now_local().date().isoformat(),),
    ).fetchall()
    if not rows:
        await message.answer("Записей пока нет.")
        return
    lines = [
        f"{'✅' if st == 'confirmed' else '⏳'} {d} {s}: {sv} ({c})"
        for d, s, sv, c, st in rows
    ]
    await message.answer("📋 Ближайшие записи:\n" + "\n".join(lines))

@dp.message(F.text == "💈 Услуги")
async def services(message: Message):
    await message.answer("Наши услуги:\n• Мужская стрижка\n• Оформление бороды\n• Стрижка + борода")

@dp.message(F.text == "💰 Цены")
async def prices(message: Message):
    await message.answer("Цены:\n• Стрижка: 400 грн\n• Борода: 250 грн\n• Стрижка + борода: 600 грн")

@dp.message(F.text == "📍 Контакты")
async def contacts(message: Message):
    await message.answer("Адрес: ул. Примерная, 1\nТелефон: +380 00 000 00 00\nРаботаем: 10:00-20:00")

# --- напоминания ---
async def reminder_loop():
    while True:
        try:
            now = now_local()
            rows = db.execute(
                "SELECT id, user_id, service, day, slot, remind_day, remind_hour "
                "FROM bookings WHERE status='confirmed'"
            ).fetchall()
            for bid, uid, service, day, slot, rd, rh in rows:
                left = visit_time(day, slot) - now
                if timedelta(0) < left <= timedelta(hours=1) and not rh:
                    text = f"⏰ Напоминаем: сегодня в {slot} вас ждут ({service}). До встречи!"
                    flags = "remind_hour=1, remind_day=1"
                elif timedelta(hours=1) < left <= timedelta(hours=REMIND_DAY_HOURS) and not rd:
                    text = f"⏰ Напоминаем о записи завтра: {day} в {slot} ({service}). Ждём вас!"
                    flags = "remind_day=1"
                else:
                    continue
                try:
                    await bot.send_message(uid, text)
                except Exception as e:
                    print("Не удалось отправить напоминание:", e)
                db.execute(f"UPDATE bookings SET {flags} WHERE id=?", (bid,))
                db.commit()
        except Exception as e:
            print("Ошибка в напоминаниях:", e)
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
