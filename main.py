import asyncio
import io
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# СЮДА ВСТАВЬ СВОЙ ТОКЕН НИЖЕ В КАВЫЧКАХ:
TOKEN = "8565247399:AAEE7PL2e6J-iHK84nuBcD3mtSSfSPYZvaA"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

CLOSE_HOUR = 17
CLOSE_MINUTE = 30

PLATOONS = ["ВТ-31", "ВТ-32", "ВТ-41", "ВТ-42"]

class Registration(StatesGroup):
    waiting_for_platoon = State()
    waiting_for_name = State()
    updating_name = State()

conn = sqlite3.connect("discipline_list.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    platoon TEXT,
    military_name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    user_id INTEGER,
    slot TEXT,
    UNIQUE(date, user_id)
)
""")
conn.commit()


def is_registration_open() -> bool:
    now = datetime.now()
    close_time = now.replace(hour=CLOSE_HOUR, minute=CLOSE_MINUTE, second=0, microsecond=0)
    return now < close_time


def get_list_text(today_str: str) -> str:
    cursor.execute("""
        SELECT u.platoon, u.military_name, e.slot 
        FROM entries e 
        JOIN users u ON e.user_id = u.user_id 
        WHERE e.date = ?
        ORDER BY u.platoon, u.military_name
    """, (today_str,))
    rows = cursor.fetchall()
    
    slots = {
        "18:30-21:30": {},
        "18:30-7:00": {},
        "19:30-21:30": {},
        "19:30-7:00": {}
    }
    
    for platoon, name, slot in rows:
        if slot in slots:
            if platoon not in slots[slot]:
                slots[slot][platoon] = []
            slots[slot][platoon].append(name)
            
    status_note = "🟢 **Запись открыта** (до 17:30)" if is_registration_open() else "🔴 **Запись закрыта**"
    
    text = f"📋 **Увольняемые на {today_str}**\n{status_note}\n\n"
    
    for slot_time, platoons_data in slots.items():
        text += f"⏰ **{slot_time}**\n"
        if platoons_data:
            for plt, names in platoons_data.items():
                text += f"*{plt}:*\n"
                text += "\n".join(f"• {name}" for name in names) + "\n"
            text += "\n"
        else:
            text += "—\n\n"
            
    return text.strip()


def get_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="18:30-21:30", callback_data="slot_1830_2130")
    builder.button(text="18:30-7:00", callback_data="slot_1830_0700")
    builder.button(text="19:30-21:30", callback_data="slot_1930_2130")
    builder.button(text="19:30-7:00", callback_data="slot_1930_0700")
    builder.button(text="❌ Выписаться", callback_data="slot_cancel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_platoon_keyboard(prefix: str = "plt_"):
    builder = InlineKeyboardBuilder()
    for plt in PLATOONS:
        builder.button(text=plt, callback_data=f"{prefix}{plt}")
    builder.adjust(2, 2)
    return builder.as_markup()


@dp.message(Command("new_list"))
async def cmd_new_list(message: types.Message):
    today = datetime.now().strftime("%Y-%m-%d")
    
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM entries WHERE date < ?", (three_days_ago,))
    conn.commit()
    
    await message.answer(get_list_text(today), reply_markup=get_keyboard(), parse_mode="Markdown")


@dp.message(Command("change_name", "name"))
async def cmd_change_name(message: types.Message, state: FSMContext):
    await state.set_state(Registration.updating_name)
    await message.answer("Введите новое звание и ФИО (например: *С-т Лемешев Д Д*):", parse_mode="Markdown")


@dp.message(Registration.updating_name)
async def process_update_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    new_name = message.text.strip()
    
    cursor.execute("UPDATE users SET military_name = ? WHERE user_id = ?", (new_name, user_id))
    conn.commit()
    
    await state.clear()
    await message.answer(f"✅ ФИО обновлено: **{new_name}**", parse_mode="Markdown")


@dp.message(Command("change_platoon", "platoon"))
async def cmd_change_platoon(message: types.Message):
    await message.answer("Выберите ваш новый взвод:", reply_markup=get_platoon_keyboard("changeplt_"))


@dp.callback_query(F.data.startswith("changeplt_"))
async def process_change_platoon(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_platoon = callback.data.split("_")[1]
    
    cursor.execute("UPDATE users SET platoon = ? WHERE user_id = ?", (new_platoon, user_id))
    conn.commit()
    
    await callback.message.edit_text(f"✅ Взвод изменен на: **{new_platoon}**", parse_mode="Markdown")
    await callback.answer()


@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    today = datetime.now().strftime("%Y-%m-%d")
    raw_text = get_list_text(today).replace("**", "").replace("*", "")
    
    file_bytes = raw_text.encode('utf-8')
    input_file = types.BufferedInputFile(file_bytes, filename=f"Увольняемые_{today}.txt")
    
    await message.answer_document(input_file, caption=f"📄 Список увольняемых на {today}")


@dp.message(Command("remove"))
async def cmd_remove_user(message: types.Message):
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT e.user_id, u.platoon, u.military_name, e.slot 
        FROM entries e 
        JOIN users u ON e.user_id = u.user_id 
        WHERE e.date = ?
    """, (today,))
    rows = cursor.fetchall()
    
    if not rows:
        await message.answer("В списке на сегодня пока никто не записан.")
        return

    builder = InlineKeyboardBuilder()
    for uid, plt, name, slot in rows:
        builder.button(
            text=f"❌ {plt} {name} ({slot})", 
            callback_data=f"admrm_{uid}"
        )
    builder.adjust(1)
    
    await message.answer("Выберите человека для удаления из списка:", reply_markup=builder.as_markup())


@dp.callback_query(F.data.startswith("admrm_"))
async def process_admin_remove(callback: types.CallbackQuery):
    target_uid = int(callback.data.split("_")[1])
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("DELETE FROM entries WHERE date = ? AND user_id = ?", (today, target_uid))
    conn.commit()
    
    await callback.answer("Участник удален из списка.")
    await callback.message.edit_text("✅ Участник успешно удален из списка на сегодня.")


@dp.callback_query(F.data.startswith("slot_"))
async def handle_slot(callback: types.CallbackQuery, state: FSMContext):
    today = datetime.now().strftime("%Y-%m-%d")
    user_id = callback.from_user.id

    if not is_registration_open():
        await callback.answer("⏳ Запись на сегодня закрыта (после 17:30).", show_alert=True)
        return

    if callback.data == "slot_cancel":
        cursor.execute("DELETE FROM entries WHERE date = ? AND user_id = ?", (today, user_id))
        conn.commit()
        await callback.message.edit_text(get_list_text(today), reply_markup=get_keyboard(), parse_mode="Markdown")
        await callback.answer("Вы выписались.")
        return

    slot_map = {
        "slot_1830_2130": "18:30-21:30",
        "slot_1830_0700": "18:30-7:00",
        "slot_1930_2130": "19:30-21:30",
        "slot_1930_0700": "19:30-7:00",
    }
    chosen_slot = slot_map.get(callback.data)

    cursor.execute("SELECT platoon, military_name FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        await state.update_data(chosen_slot=chosen_slot, target_message_id=callback.message.message_id)
        await state.set_state(Registration.waiting_for_platoon)
        await callback.answer()
        await callback.message.answer("Выберите ваш взвод:", reply_markup=get_platoon_keyboard())
    else:
        cursor.execute(
            "INSERT INTO entries (date, user_id, slot) VALUES (?, ?, ?) "
            "ON CONFLICT(date, user_id) DO UPDATE SET slot=excluded.slot",
            (today, user_id, chosen_slot)
        )
        conn.commit()
        await callback.message.edit_text(get_list_text(today), reply_markup=get_keyboard(), parse_mode="Markdown")
        await callback.answer("Запись обновлена!")


@dp.callback_query(Registration.waiting_for_platoon, F.data.startswith("plt_"))
async def process_platoon(callback: types.CallbackQuery, state: FSMContext):
    platoon = callback.data.split("_")[1]
    await state.update_data(platoon=platoon)
    await state.set_state(Registration.waiting_for_name)
    
    await callback.message.edit_text(
        f"Взвод: **{platoon}**.\nТеперь введите звание и фамилию (например: *Ряд Лемешев Д Д*):", 
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    military_name = message.text.strip()
    today = datetime.now().strftime("%Y-%m-%d")

    data = await state.get_data()
    chosen_slot = data.get("chosen_slot")
    platoon = data.get("platoon")

    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, platoon, military_name) VALUES (?, ?, ?)", 
        (user_id, platoon, military_name)
    )
    cursor.execute(
        "INSERT INTO entries (date, user_id, slot) VALUES (?, ?, ?) "
        "ON CONFLICT(date, user_id) DO UPDATE SET slot=excluded.slot",
        (today, user_id, chosen_slot)
    )
    conn.commit()

    await state.clear()
    await message.answer("✅ Регистрация завершена. Вы внесены в список!")

    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=data.get("target_message_id"),
            text=get_list_text(today),
            reply_markup=get_keyboard(),
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
