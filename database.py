import os
import enum
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum as SQLEnum, BigInteger, func
from sqlalchemy.future import select

# PostgreSQL connection (fallback to SQLite for local testing if needed)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./erp.db")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# --- DATABASE MODELS ---
class Role(enum.Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"

class OrderStatus(enum.Enum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class TxCategory(enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"
    SALARY = "salary"
    ADVANCE = "advance"
    PURCHASE = "purchase"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True, nullable=True)
    role = Column(SQLEnum(Role), default=Role.EMPLOYEE)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    invite_code = Column(String, unique=True, nullable=True)

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String)
    clean_type = Column(String)
    price = Column(Float)
    date = Column(DateTime, nullable=True)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.NEW)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float)
    category = Column(SQLEnum(TxCategory))
    date = Column(DateTime, default=datetime.utcnow)
    comment = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

# --- TABLE CREATION ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- CRUD: EMPLOYEES ---
async def get_user(tg_id: int):
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(User).where(User.tg_id == tg_id))).scalars().first()

async def get_user_by_name(name: str):
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(User).where(User.name.ilike(f"%{name}%")))).scalars().first()

async def create_admin(tg_id: int):
    async with AsyncSessionLocal() as session:
        admin = (await session.execute(select(User).where(User.role == Role.ADMIN))).scalars().first()
        if not admin:
            new_admin = User(tg_id=tg_id, role=Role.ADMIN, name="Руководитель")
            session.add(new_admin)
            await session.commit()
            return new_admin
        return None

async def create_invite(name: str):
    code = str(uuid.uuid4())[:8]
    async with AsyncSessionLocal() as session:
        session.add(User(name=name, invite_code=code, role=Role.EMPLOYEE))
        await session.commit()
        return code

async def register_user(invite_code: str, tg_id: int):
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.invite_code == invite_code))).scalars().first()
        if user and not user.tg_id:
            user.tg_id = tg_id
            user.invite_code = None
            await session.commit()
            return user
        return None

async def get_all_employees():
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(User).where(User.role == Role.EMPLOYEE))).scalars().all()

# --- CRUD: FINANCES ---
async def add_transaction(amount: float, category: str, comment: str, user_id: int = None, date: datetime = None):
    async with AsyncSessionLocal() as session:
        tx = Transaction(amount=amount, category=TxCategory(category), comment=comment, user_id=user_id, date=date or datetime.utcnow())
        session.add(tx)
        if user_id and category in ["salary", "advance"]:
            user = await session.get(User, user_id)
            if user: user.balance -= amount
        await session.commit()
        return tx

async def get_stats(period="day"):
    async with AsyncSessionLocal() as session:
        today = datetime.utcnow().date()
        inc_q = select(func.sum(Transaction.amount)).where(Transaction.category == TxCategory.INCOME)
        exp_q = select(func.sum(Transaction.amount)).where(Transaction.category.in_([TxCategory.EXPENSE, TxCategory.PURCHASE, TxCategory.SALARY, TxCategory.ADVANCE]))
        
        if period == "day":
            inc_q = inc_q.where(func.date(Transaction.date) == today)
            exp_q = exp_q.where(func.date(Transaction.date) == today)
            
        inc = (await session.execute(inc_q)).scalar() or 0.0
        exp = (await session.execute(exp_q)).scalar() or 0.0
        return {"income": inc, "expense": exp, "profit": inc - exp}

# --- CRUD: ORDERS ---
async def create_order(address: str, price: float, clean_type: str, date: datetime = None, assigned_to: int = None):
    async with AsyncSessionLocal() as session:
        order = Order(address=address, price=price, clean_type=clean_type, date=date, assigned_to=assigned_to)
        session.add(order)
        await session.commit()
        return order

async def get_orders(user_id: int = None):
    async with AsyncSessionLocal() as session:
        q = select(Order)
        if user_id: q = q.where(Order.assigned_to == user_id)
        return (await session.execute(q)).scalars().all()

# --- CRUD: CLIENTS ---
async def create_client(name: str, phone: str, address: str):
    async with AsyncSessionLocal() as session:
        client = Client(name=name, phone=phone, address=address)
        session.add(client)
        await session.commit()
        return client

async def get_clients():
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(Client))).scalars().all()