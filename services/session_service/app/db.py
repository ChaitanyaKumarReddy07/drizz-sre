import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://drizz:drizz@localhost:5432/drizz")
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, pool_size=10)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    from app.models.session import AppSession, SessionHealthEvent
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
