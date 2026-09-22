from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)


AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    # Import models để register tables.
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )


async def close_db() -> None:
    await engine.dispose()