import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.environ["DATABASE_URL"]

# asyncpg 드라이버를 쓰도록 URL 스킴 변경
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(ASYNC_DATABASE_URL, echo=True)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
