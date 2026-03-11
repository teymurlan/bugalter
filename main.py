import asyncio
import logging
import os
from datetime import datetime, timedelta
import pytz
import io

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Voice recognition
import speech_recognition as sr
from pydub import AudioSegment

# Setup logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.warning("BOT_TOKEN is not set. Please set it in your environment variables.")
    # Fallback for testing purposes if needed, but should raise error in production
    # raise ValueError("No BOT_TOKEN provided")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Timezone
TZ = pytz.timezone('Europe/Moscow')

# --- DATABASE SETUP ---
from database import init_db, get_db_connection

init_db()

# --- KEYBOARDS ---
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Панель", callback_data="menu_panel"), InlineKeyboardButton(text="🧹 Заявки", callback_data="menu_jobs")],
        [InlineKeyboardButton(text="👥 Сотрудники", callback_data="menu_employees"), InlineKeyboardButton(text="💰 Зарплаты", callback_data="menu_salaries")],
        [InlineKeyboardButton(text="📉 Расходы", callback_data="menu_expenses"), InlineKeyboardButton(text="📈 Доходы", callback_data="menu_income")],
        [InlineKeyboardButton(text="📦 Склад", callback_data="menu_inventory"), InlineKeyboardButton(text="📑 Отчет", callback_data="menu_reports")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu_statistics")]
    ])

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])

def jobs_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить заявку", callback_data="job_add")],
        [InlineKeyboardButton(text="📋 Просмотр заявок", callback_data="job_view")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def employees_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить сотрудника", callback_data="emp_add")],
        [InlineKeyboardButton(text="📋 Просмотр списка", callback_data="emp_view")],
        [InlineKeyboardButton(text="📈 Статистика сотрудника", callback_data="emp_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def finance_menu_kb(type_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data=f"{type_name}_add")],
        [InlineKeyboardButton(text="📋 Просмотр", callback_data=f"{type_name}_view")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def select_employee_kb(prefix="sel_emp_"):
    conn = get_db_connection()
    employees = conn.execute("SELECT id, name FROM employees").fetchall()
    conn.close()
    kb = []
    for emp in employees:
        kb.append([InlineKeyboardButton(text=emp['name'], callback_data=f"{prefix}{emp['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def date_kb(prefix="date_"):
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).strftime("%d.%m.%Y")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Сегодня ({today})", callback_data=f"{prefix}{today}")],
        [InlineKeyboardButton(text=f"Завтра ({tomorrow})", callback_data=f"{prefix}{tomorrow}")],
        [InlineKeyboardButton(text="Ввести вручную", callback_data=f"{prefix}manual")]
    ])

# --- STATES ---
class JobFSM(StatesGroup):
    employee_id = State()
    client_name = State()
    address = State()
    price = State()
    employee_salary = State()
    date = State()

class EmployeeFSM(StatesGroup):
    name = State()
    phone = State()
    role = State()

class ExpenseFSM(StatesGroup):
    category = State()
    amount = State()
    comment = State()

class IncomeFSM(StatesGroup):
    source = State()
    amount = State()
    comment = State()

# --- HANDLERS: MAIN MENU ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Добро пожаловать в систему управления клининговой компанией!\nВыберите раздел:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("📊 Главное меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "menu_panel")
async def menu_panel(callback: CallbackQuery):
    conn = get_db_connection()
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    jobs_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE date = ?", (today,)).fetchone()[0]
    profit_today = conn.execute("SELECT SUM(profit) FROM jobs WHERE date = ?", (today,)).fetchone()[0] or 0
    conn.close()
    
    text = f"📊 **Панель управления**\n\nСегодня ({today}):\n🧹 Заявок: {jobs_today}\n💰 Прибыль: {profit_today} руб."
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: JOBS ---
@router.callback_query(F.data == "menu_jobs")
async def menu_jobs(callback: CallbackQuery):
    await callback.message.edit_text("🧹 **Управление заявками**", parse_mode="Markdown", reply_markup=jobs_menu_kb())

@router.callback_query(F.data == "job_add")
async def job_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите сотрудника для заявки:", reply_markup=select_employee_kb())
    await state.set_state(JobFSM.employee_id)

@router.callback_query(JobFSM.employee_id, F.data.startswith("sel_emp_"))
async def job_add_emp(callback: CallbackQuery, state: FSMContext):
    emp_id = int(callback.data.split("_")[2])
    await state.update_data(employee_id=emp_id)
    await callback.message.edit_text("Введите имя клиента (или телефон):")
    await state.set_state(JobFSM.client_name)

@router.message(JobFSM.client_name)
async def job_add_client(message: Message, state: FSMContext):
    await state.update_data(client_name=message.text)
    await message.answer("Введите адрес объекта:")
    await state.set_state(JobFSM.address)

@router.message(JobFSM.address)
async def job_add_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Введите цену заказа (только число):")
    await state.set_state(JobFSM.price)

@router.message(JobFSM.price)
async def job_add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        await state.update_data(price=price)
        await message.answer("Введите зарплату сотрудника за этот заказ (только число):")
        await state.set_state(JobFSM.employee_salary)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.message(JobFSM.employee_salary)
async def job_add_salary(message: Message, state: FSMContext):
    try:
        salary = float(message.text.replace(",", "."))
        await state.update_data(employee_salary=salary)
        await message.answer("Выберите дату заявки:", reply_markup=date_kb("jobdate_"))
        await state.set_state(JobFSM.date)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.callback_query(JobFSM.date, F.data.startswith("jobdate_"))
async def job_add_date_cb(callback: CallbackQuery, state: FSMContext):
    date_val = callback.data.split("_")[1]
    if date_val == "manual":
        await callback.message.edit_text("Введите дату в формате ДД.ММ.ГГГГ:")
        return
    await process_job_save(callback.message, state, date_val)

@router.message(JobFSM.date)
async def job_add_date_manual(message: Message, state: FSMContext):
    await process_job_save(message, state, message.text)

async def process_job_save(message: Message, state: FSMContext, date_str: str):
    data = await state.get_data()
    profit = data['price'] - data['employee_salary']
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO jobs (employee_id, client_name, address, price, employee_salary, profit, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (data['employee_id'], data['client_name'], data['address'], data['price'], data['employee_salary'], profit, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    text = f"✅ Заявка успешно добавлена!\n\nКлиент: {data['client_name']}\nАдрес: {data['address']}\nЦена: {data['price']}\nЗП: {data['employee_salary']}\nПрибыль: {profit}\nДата: {date_str}"
    
    if isinstance(message, Message):
        await message.answer(text, reply_markup=back_to_main_kb())
    else:
        await message.edit_text(text, reply_markup=back_to_main_kb())

@router.callback_query(F.data == "job_view")
async def job_view(callback: CallbackQuery):
    conn = get_db_connection()
    jobs = conn.execute('''
        SELECT j.id, e.name as emp_name, j.client_name, j.price, j.date 
        FROM jobs j JOIN employees e ON j.employee_id = e.id 
        ORDER BY j.id DESC LIMIT 10
    ''').fetchall()
    conn.close()
    
    if not jobs:
        await callback.message.edit_text("Заявок пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 заявок:**\n\n"
    for j in jobs:
        text += f"ID: {j['id']} | {j['date']} | {j['emp_name']} | {j['client_name']} | {j['price']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: EMPLOYEES ---
@router.callback_query(F.data == "menu_employees")
async def menu_employees(callback: CallbackQuery):
    await callback.message.edit_text("👥 **Сотрудники**", parse_mode="Markdown", reply_markup=employees_menu_kb())

@router.callback_query(F.data == "emp_add")
async def emp_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ФИО сотрудника:")
    await state.set_state(EmployeeFSM.name)

@router.message(EmployeeFSM.name)
async def emp_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите телефон сотрудника:")
    await state.set_state(EmployeeFSM.phone)

@router.message(EmployeeFSM.phone)
async def emp_add_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Введите должность (например, Клинер):")
    await state.set_state(EmployeeFSM.role)

@router.message(EmployeeFSM.role)
async def emp_add_role(message: Message, state: FSMContext):
    data = await state.get_data()
    role = message.text
    
    conn = get_db_connection()
    conn.execute('INSERT INTO employees (name, phone, role) VALUES (?, ?, ?)', (data['name'], data['phone'], role))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Сотрудник {data['name']} добавлен!", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "emp_view")
async def emp_view(callback: CallbackQuery):
    conn = get_db_connection()
    emps = conn.execute('SELECT * FROM employees').fetchall()
    conn.close()
    
    if not emps:
        await callback.message.edit_text("Сотрудников пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Список сотрудников:**\n\n"
    for e in emps:
        text += f"ID: {e['id']} | {e['name']} | {e['phone']} | {e['role']}\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: EXPENSES ---
@router.callback_query(F.data == "menu_expenses")
async def menu_expenses(callback: CallbackQuery):
    await callback.message.edit_text("📉 **Расходы**", parse_mode="Markdown", reply_markup=finance_menu_kb("exp"))

@router.callback_query(F.data == "exp_add")
async def exp_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите категорию расхода (например, Химия, Бензин):")
    await state.set_state(ExpenseFSM.category)

@router.message(ExpenseFSM.category)
async def exp_add_cat(message: Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("Введите сумму (только число):")
    await state.set_state(ExpenseFSM.amount)

@router.message(ExpenseFSM.amount)
async def exp_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(amount=amount)
        await message.answer("Введите комментарий:")
        await state.set_state(ExpenseFSM.comment)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.message(ExpenseFSM.comment)
async def exp_add_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text
    date_str = datetime.now(TZ).strftime("%d.%m.%Y")
    
    conn = get_db_connection()
    conn.execute('INSERT INTO expenses (category, amount, comment, date) VALUES (?, ?, ?, ?)', 
                 (data['category'], data['amount'], comment, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Расход добавлен!\nСумма: {data['amount']} руб.\nКатегория: {data['category']}", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "exp_view")
async def exp_view(callback: CallbackQuery):
    conn = get_db_connection()
    exps = conn.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    
    if not exps:
        await callback.message.edit_text("Расходов пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 расходов:**\n\n"
    for e in exps:
        text += f"{e['date']} | {e['category']} | {e['amount']} руб. | {e['comment']}\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: REPORTS & STATISTICS ---
@router.callback_query(F.data == "menu_reports")
async def menu_reports(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Месячный отчет", callback_data="rep_month")],
        [InlineKeyboardButton(text="🏆 Топ сотрудник", callback_data="rep_top_emp")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📑 **Отчеты**", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "rep_month")
async def rep_month(callback: CallbackQuery):
    current_month = datetime.now(TZ).strftime(".%m.%Y")
    conn = get_db_connection()
    
    # Income from jobs
    jobs_income = conn.execute("SELECT SUM(price) FROM jobs WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    jobs_profit = conn.execute("SELECT SUM(profit) FROM jobs WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    # Other income
    other_income = conn.execute("SELECT SUM(amount) FROM income WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    # Expenses
    expenses = conn.execute("SELECT SUM(amount) FROM expenses WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    conn.close()
    
    total_income = jobs_income + other_income
    net_profit = jobs_profit + other_income - expenses
    
    text = f"📅 **Отчет за текущий месяц ({current_month})**\n\n"
    text += f"📈 Оборот (заявки): {jobs_income} руб.\n"
    text += f"📈 Доп. доходы: {other_income} руб.\n"
    text += f"📉 Расходы: {expenses} руб.\n"
    text += f"💰 **Чистая прибыль: {net_profit} руб.**"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "rep_top_emp")
async def rep_top_emp(callback: CallbackQuery):
    current_month = datetime.now(TZ).strftime(".%m.%Y")
    conn = get_db_connection()
    
    top_emps = conn.execute('''
        SELECT e.name, COUNT(j.id) as job_count, SUM(j.price) as total_brought
        FROM jobs j
        JOIN employees e ON j.employee_id = e.id
        WHERE j.date LIKE ?
        GROUP BY e.id
        ORDER BY total_brought DESC
        LIMIT 5
    ''', (f"%{current_month}",)).fetchall()
    
    conn.close()
    
    if not top_emps:
        await callback.message.edit_text("Нет данных за этот месяц.", reply_markup=back_to_main_kb())
        return
        
    text = f"🏆 **Топ сотрудников за месяц ({current_month})**\n\n"
    for i, emp in enumerate(top_emps, 1):
        text += f"{i}. {emp['name']} — {emp['job_count']} заявок, принес {emp['total_brought']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- VOICE RECOGNITION ---
@router.message(F.voice)
async def handle_voice(message: Message):
    msg = await message.answer("⏳ Обработка голосового сообщения...")
    try:
        # Download voice
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        voice_io = io.BytesIO()
        await bot.download_file(file_path, voice_io)
        voice_io.seek(0)
        
        # Convert ogg to wav
        audio = AudioSegment.from_file(voice_io, format="ogg")
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        # Recognize
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать заявку", callback_data="job_add")],
            [InlineKeyboardButton(text="📉 Добавить расход", callback_data="exp_add")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")]
        ])
        await msg.edit_text(f"🎙 **Распознанный текст:**\n_{text}_\n\nЧто вы хотите сделать с этой информацией?", parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logging.error(f"Voice recognition error: {e}")
        await msg.edit_text("❌ Не удалось распознать голосовое сообщение. Убедитесь, что установлен ffmpeg.", reply_markup=back_to_main_kb())

# --- MAIN RUNNER ---
async def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable is missing.")
        return
    print("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
