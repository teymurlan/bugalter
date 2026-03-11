import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import io
import openpyxl
import tempfile

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext

from database import get_db_connection
from keyboards import (
    TZ, back_to_main_kb, main_menu_kb, finance_menu_kb, select_employee_kb
)
from states import SalaryFSM, IncomeFSM, InventoryFSM, DeleteFSM, ExpenseFSM

extra_router = Router()

# --- HANDLERS: SALARIES ---
@extra_router.callback_query(F.data == "menu_salaries")
async def menu_salaries(callback: CallbackQuery):
    await callback.message.edit_text("💰 **Зарплаты и Авансы**", parse_mode="Markdown", reply_markup=finance_menu_kb("sal"))

@extra_router.callback_query(F.data == "sal_add")
async def sal_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите сотрудника:", reply_markup=select_employee_kb("sal_emp_"))
    await state.set_state(SalaryFSM.employee_id)

@extra_router.callback_query(SalaryFSM.employee_id, F.data.startswith("sal_emp_"))
async def sal_add_emp(callback: CallbackQuery, state: FSMContext):
    emp_id = int(callback.data.split("_")[2])
    await state.update_data(employee_id=emp_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Зарплата", callback_data="saltype_Зарплата")],
        [InlineKeyboardButton(text="Аванс", callback_data="saltype_Аванс")]
    ])
    await callback.message.edit_text("Выберите тип выплаты:", reply_markup=kb)
    await state.set_state(SalaryFSM.type)

@extra_router.callback_query(SalaryFSM.type, F.data.startswith("saltype_"))
async def sal_add_type(callback: CallbackQuery, state: FSMContext):
    sal_type = callback.data.split("_")[1]
    await state.update_data(type=sal_type)
    await callback.message.edit_text("Введите сумму (только число):")
    await state.set_state(SalaryFSM.amount)

@extra_router.message(SalaryFSM.amount)
async def sal_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(amount=amount)
        await message.answer("Введите комментарий (или '-' если нет):")
        await state.set_state(SalaryFSM.comment)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@extra_router.message(SalaryFSM.comment)
async def sal_add_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text
    date_str = datetime.now(TZ).strftime("%d.%m.%Y")
    
    conn = get_db_connection()
    conn.execute('INSERT INTO salary_payments (employee_id, amount, type, comment, date) VALUES (?, ?, ?, ?, ?)', 
                 (data['employee_id'], data['amount'], data['type'], comment, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Выплата добавлена!\nТип: {data['type']}\nСумма: {data['amount']} руб.", reply_markup=back_to_main_kb())

@extra_router.callback_query(F.data == "sal_view")
async def sal_view(callback: CallbackQuery):
    conn = get_db_connection()
    sals = conn.execute('''
        SELECT s.date, e.name, s.amount, s.type 
        FROM salary_payments s JOIN employees e ON s.employee_id = e.id 
        ORDER BY s.id DESC LIMIT 10
    ''').fetchall()
    conn.close()
    
    if not sals:
        await callback.message.edit_text("Выплат пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 выплат:**\n\n"
    for s in sals:
        text += f"{s['date']} | {s['name']} | {s['type']} | {s['amount']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: INCOME ---
@extra_router.callback_query(F.data == "menu_income")
async def menu_income(callback: CallbackQuery):
    await callback.message.edit_text("📈 **Доп. Доходы**", parse_mode="Markdown", reply_markup=finance_menu_kb("inc"))

@extra_router.callback_query(F.data == "inc_add")
async def inc_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите источник дохода:")
    await state.set_state(IncomeFSM.source)

@extra_router.message(IncomeFSM.source)
async def inc_add_source(message: Message, state: FSMContext):
    await state.update_data(source=message.text)
    await message.answer("Введите сумму (только число):")
    await state.set_state(IncomeFSM.amount)

@extra_router.message(IncomeFSM.amount)
async def inc_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(amount=amount)
        await message.answer("Введите комментарий:")
        await state.set_state(IncomeFSM.comment)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@extra_router.message(IncomeFSM.comment)
async def inc_add_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text
    date_str = datetime.now(TZ).strftime("%d.%m.%Y")
    
    conn = get_db_connection()
    conn.execute('INSERT INTO income (source, amount, comment, date) VALUES (?, ?, ?, ?)', 
                 (data['source'], data['amount'], comment, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Доход добавлен!\nСумма: {data['amount']} руб.\nИсточник: {data['source']}", reply_markup=back_to_main_kb())

@extra_router.callback_query(F.data == "inc_view")
async def inc_view(callback: CallbackQuery):
    conn = get_db_connection()
    incs = conn.execute('SELECT * FROM income ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    
    if not incs:
        await callback.message.edit_text("Доходов пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 доходов:**\n\n"
    for i in incs:
        text += f"{i['date']} | {i['source']} | {i['amount']} руб. | {i['comment']}\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: INVENTORY ---
@extra_router.callback_query(F.data == "menu_inventory")
async def menu_inventory(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить на склад", callback_data="inv_add")],
        [InlineKeyboardButton(text="📋 Просмотр склада", callback_data="inv_view")],
        [InlineKeyboardButton(text="❌ Удалить со склада", callback_data="inv_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📦 **Склад (Материалы/Химия)**", parse_mode="Markdown", reply_markup=kb)

@extra_router.callback_query(F.data == "inv_add")
async def inv_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название материала:")
    await state.set_state(InventoryFSM.item_name)

@extra_router.message(InventoryFSM.item_name)
async def inv_add_name(message: Message, state: FSMContext):
    await state.update_data(item_name=message.text)
    await message.answer("Введите количество:")
    await state.set_state(InventoryFSM.quantity)

@extra_router.message(InventoryFSM.quantity)
async def inv_add_qty(message: Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        await state.update_data(quantity=qty)
        await message.answer("Введите общую стоимость (только число):")
        await state.set_state(InventoryFSM.price)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@extra_router.message(InventoryFSM.price)
async def inv_add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        data = await state.get_data()
        
        conn = get_db_connection()
        conn.execute('INSERT INTO inventory (item_name, quantity, price) VALUES (?, ?, ?)', 
                     (data['item_name'], data['quantity'], price))
        conn.commit()
        conn.close()
        
        await state.clear()
        await message.answer(f"✅ Товар добавлен на склад!\n{data['item_name']} - {data['quantity']} шт. ({price} руб.)", reply_markup=back_to_main_kb())
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@extra_router.callback_query(F.data == "inv_view")
async def inv_view(callback: CallbackQuery):
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM inventory ORDER BY item_name').fetchall()
    conn.close()
    
    if not items:
        await callback.message.edit_text("Склад пуст.", reply_markup=back_to_main_kb())
        return
        
    text = "📦 **Остатки на складе:**\n\n"
    for i in items:
        text += f"▪️ {i['item_name']} | {i['quantity']} шт. | {i['price']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: STATISTICS ---
@extra_router.callback_query(F.data == "menu_statistics")
async def menu_statistics(callback: CallbackQuery):
    conn = get_db_connection()
    
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_profit = conn.execute("SELECT SUM(profit) FROM jobs").fetchone()[0] or 0
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    total_salaries = conn.execute("SELECT SUM(amount) FROM salary_payments").fetchone()[0] or 0
    
    conn.close()
    
    text = "📊 **Общая статистика за все время:**\n\n"
    text += f"🧹 Всего заявок: {total_jobs}\n"
    text += f"💰 Общая прибыль (с заявок): {total_profit} руб.\n"
    text += f"📉 Всего расходов: {total_expenses} руб.\n"
    text += f"💸 Выплачено зарплат: {total_salaries} руб.\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- EXCEL EXPORT ---
@extra_router.callback_query(F.data == "export_excel")
async def export_excel(callback: CallbackQuery):
    await callback.message.edit_text("⏳ Генерирую Excel файл...")
    
    import openpyxl
    wb = openpyxl.Workbook()
    
    conn = get_db_connection()
    
    # Jobs sheet
    ws_jobs = wb.active
    ws_jobs.title = "Заявки"
    ws_jobs.append(["ID", "Сотрудник", "Клиент", "Адрес", "Цена", "ЗП", "Прибыль", "Дата"])
    jobs = conn.execute("SELECT j.id, e.name, j.client_name, j.address, j.price, j.employee_salary, j.profit, j.date FROM jobs j JOIN employees e ON j.employee_id = e.id").fetchall()
    for j in jobs:
        ws_jobs.append(list(j))
        
    # Expenses sheet
    ws_exp = wb.create_sheet("Расходы")
    ws_exp.append(["ID", "Категория", "Сумма", "Комментарий", "Дата"])
    exps = conn.execute("SELECT * FROM expenses").fetchall()
    for e in exps:
        ws_exp.append([e['id'], e['category'], e['amount'], e['comment'], e['date']])
        
    conn.close()
    
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        wb.save(tmp.name)
        tmp_path = tmp.name
        
    from aiogram.types import FSInputFile
    doc = FSInputFile(tmp_path, filename=f"Отчет_{datetime.now(TZ).strftime('%d_%m_%Y')}.xlsx")
    await callback.message.answer_document(doc, reply_markup=back_to_main_kb())
    await callback.message.delete()
    os.remove(tmp_path)

# --- CATCH ALL & CANCEL ---
@extra_router.callback_query(F.data.in_(["job_del", "exp_del", "inc_del", "sal_del", "inv_del", "emp_del"]))
async def delete_start(callback: CallbackQuery, state: FSMContext):
    table_map = {
        "job_del": "jobs",
        "exp_del": "expenses",
        "inc_del": "income",
        "sal_del": "salary_payments",
        "inv_del": "inventory",
        "emp_del": "employees"
    }
    table_name = table_map[callback.data]
    await state.update_data(table_name=table_name)
    
    conn = get_db_connection()
    items = conn.execute(f'SELECT * FROM {table_name} ORDER BY id DESC LIMIT 5').fetchall()
    conn.close()
    
    if not items:
        await callback.message.edit_text("Нет записей для удаления.", reply_markup=back_to_main_kb())
        return
        
    text = "🗑 **Введите ID записи, которую хотите удалить:**\n\n_Последние 5 записей:_\n"
    for i in items:
        if table_name == "jobs":
            text += f"ID: {i['id']} | {i['date']} | {i['price']} руб.\n"
        elif table_name == "expenses":
            text += f"ID: {i['id']} | {i['category']} | {i['amount']} руб.\n"
        elif table_name == "income":
            text += f"ID: {i['id']} | {i['source']} | {i['amount']} руб.\n"
        elif table_name == "salary_payments":
            text += f"ID: {i['id']} | {i['type']} | {i['amount']} руб.\n"
        elif table_name == "inventory":
            text += f"ID: {i['id']} | {i['item_name']} | {i['quantity']} шт.\n"
        elif table_name == "employees":
            text += f"ID: {i['id']} | {i['name']} | {i['role']}\n"
            
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())
    await state.set_state(DeleteFSM.item_id)

@extra_router.message(DeleteFSM.item_id)
async def delete_confirm(message: Message, state: FSMContext):
    try:
        item_id = int(message.text)
        data = await state.get_data()
        table_name = data['table_name']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (item_id,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        await state.clear()
        if deleted > 0:
            await message.answer(f"✅ Запись с ID {item_id} успешно удалена!", reply_markup=back_to_main_kb())
        else:
            await message.answer(f"⚠️ Запись с ID {item_id} не найдена.", reply_markup=back_to_main_kb())
    except (ValueError, TypeError):
        await message.answer("Пожалуйста, введите корректный числовой ID.")

@extra_router.message()
async def unknown_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        if message.text:
            await process_quick_add(message.text, message)
        else:
            await message.answer("🤔 Я не понимаю это сообщение. Пожалуйста, используйте кнопки меню.", reply_markup=main_menu_kb())

async def process_quick_add(text: str, message: Message):
    text_lower = text.lower()
    conn = get_db_connection()
    employees = conn.execute("SELECT id, name FROM employees").fetchall()
    
    # 1. Find numbers
    numbers = [int(n) for n in re.findall(r'\b\d+\b', text)]
    price = 0
    salary = 0
    
    if numbers:
        large_numbers = [n for n in numbers if n >= 100]
        if large_numbers:
            price = large_numbers[0]
            if len(large_numbers) > 1:
                salary = large_numbers[1]
        else:
            price = numbers[0]
            if len(numbers) > 1:
                salary = numbers[1]
                
    # 2. Find employee
    emp_id = None
    emp_name_found = ""
    for emp in employees:
        emp_name = emp['name'].lower()
        if re.search(rf'\b{re.escape(emp_name)}\b', text_lower):
            emp_id = emp['id']
            emp_name_found = emp['name']
            break
            
    if not emp_id:
        conn.close()
        await message.answer(f"Текст: '{text}'\n\n⚠️ Не удалось найти сотрудника в тексте. Пожалуйста, добавьте заявку через меню.", reply_markup=main_menu_kb())
        return
        
    # 3. Extract address
    address = text_lower
    if price > 0:
        address = re.sub(rf'\b{price}\b', '', address, count=1)
    if salary > 0:
        address = re.sub(rf'\b{salary}\b', '', address, count=1)
    address = re.sub(rf'\b{re.escape(emp_name_found.lower())}\b', '', address, count=1)
    
    # Clean up extra spaces and punctuation
    address = " ".join(address.split()).strip(' ,.-').title()
    if not address:
        address = "Не указан"
        
    profit = price - salary
    date_str = datetime.now(TZ).strftime("%d.%m.%Y")
    
    conn.execute('''
        INSERT INTO jobs (employee_id, client_name, address, price, employee_salary, profit, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (emp_id, "Быстрое добавление", address, price, salary, profit, date_str))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ **Заявка быстро добавлена!**\n\nСотрудник: {emp_name_found}\nАдрес: {address}\nЦена: {price} руб.\nЗарплата: {salary} руб.", parse_mode="Markdown", reply_markup=back_to_main_kb())

@extra_router.callback_query()
async def unknown_callback(callback: CallbackQuery):
    await callback.answer("Эта кнопка устарела или действие не найдено.", show_alert=True)
