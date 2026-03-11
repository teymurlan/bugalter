from aiogram.fsm.state import State, StatesGroup

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

class SalaryFSM(StatesGroup):
    employee_id = State()
    amount = State()
    type = State()
    comment = State()

class InventoryFSM(StatesGroup):
    item_name = State()
    quantity = State()
    price = State()

class DeleteFSM(StatesGroup):
    table_name = State()
    item_id = State()
