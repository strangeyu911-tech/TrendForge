"""异步数据库引擎与会话管理"""
from __future__ import annotations
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine,
)
from sqlalchemy.orm import DeclarativeBase
from config import settings


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    # SQLite 并发写时等待而非立即报 locked（API 服务 + 每日调度器同时写库场景）
    connect_args={"timeout": 30, "check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session():
    """获取数据库会话的上下文管理器"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入用"""
    async with async_session() as session:
        yield session


async def init_db():
    """创建所有表 + 轻量迁移（给已有表补新列）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


# 已有表需要补的列（列名 → SQL 定义）。create_all 只建新表，不补旧表的新列。
_MIGRATE_COLUMNS = {
    "news_documents": [
        ("summary", "TEXT DEFAULT ''"),
        ("full_text", "TEXT DEFAULT ''"),
        ("author", "VARCHAR(128) DEFAULT ''"),
        ("country", "VARCHAR(8) DEFAULT 'US'"),
        ("credibility_level", "INTEGER DEFAULT 2"),
        ("hash", "VARCHAR(64) DEFAULT ''"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "news_chunks": [
        ("title", "VARCHAR(512) DEFAULT ''"),
        ("category", "VARCHAR(32) DEFAULT ''"),
        ("country", "VARCHAR(8) DEFAULT ''"),
        ("language", "VARCHAR(8) DEFAULT ''"),
        ("source_name", "VARCHAR(64) DEFAULT ''"),
        ("source_url", "VARCHAR(1024) DEFAULT ''"),
        ("publish_time", "DATETIME"),
        ("credibility", "INTEGER DEFAULT 2"),
        ("section_path", "VARCHAR(256) DEFAULT ''"),
    ],
    # 平台化升级：全球化/分发/决策日志字段
    "contents": [
        ("country", "VARCHAR(8) DEFAULT 'US'"),
        ("target_audience", "VARCHAR(64) DEFAULT ''"),
        ("platform", "VARCHAR(32) DEFAULT ''"),
        ("content_style", "VARCHAR(32) DEFAULT 'deep_dive'"),
        ("outline", "TEXT DEFAULT '[]'"),
        ("distribution_plan", "TEXT DEFAULT '{}'"),
        ("decision_log", "TEXT DEFAULT '{}'"),
    ],
    "content_events": [
        ("country", "VARCHAR(8) DEFAULT ''"),
        ("language", "VARCHAR(8) DEFAULT ''"),
        ("platform", "VARCHAR(32) DEFAULT ''"),
        ("finish_rate", "FLOAT DEFAULT 0.0"),
        ("like_count", "INTEGER DEFAULT 0"),
        ("share_count", "INTEGER DEFAULT 0"),
        ("negative_feedback", "INTEGER DEFAULT 0"),
    ],
    "tasks": [
        ("decision_log", "TEXT DEFAULT '{}'"),
    ],
}


async def _migrate(conn):
    """对已有表补缺失列 + 回填 hash + 建唯一索引"""
    from sqlalchemy import text
    for table, cols in _MIGRATE_COLUMNS.items():
        # 取已有列
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {r[1] for r in rows}
        for col, ddl in cols:
            if col not in existing:
                try:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass  # 列已存在或其他冲突，忽略
    # 回填 news_documents.hash（旧数据无 hash）
    try:
        await conn.execute(text("UPDATE news_documents SET hash = '' WHERE hash IS NULL"))
        rows = await conn.execute(text("SELECT doc_id, url FROM news_documents WHERE hash = '' OR hash IS NULL"))
        import hashlib
        for doc_id, url in rows:
            h = hashlib.sha256((url or "").encode()).hexdigest()
            await conn.execute(text("UPDATE news_documents SET hash = :h WHERE doc_id = :d"), {"h": h, "d": doc_id})
    except Exception:
        pass
    # 建索引（IF NOT EXISTS，hash 唯一）
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS ix_news_documents_country ON news_documents(country)",
        "CREATE INDEX IF NOT EXISTS ix_news_documents_hash ON news_documents(hash)",
        "CREATE INDEX IF NOT EXISTS ix_news_chunks_category ON news_chunks(category)",
        "CREATE INDEX IF NOT EXISTS ix_news_chunks_country ON news_chunks(country)",
    ]:
        try:
            await conn.execute(text(idx_sql))
        except Exception:
            pass
    # 修复 content_events.id：旧表用 BigInteger（SQLite 不 autoincrement）→ 重建为 Integer
    try:
        rows = list(await conn.execute(text("PRAGMA table_info(content_events)")))
        need_rebuild = any(r[1] == "id" and "BIG" in (r[2] or "").upper() for r in rows)
        if need_rebuild:
            await conn.execute(text("DROP TABLE IF EXISTS content_events"))
            await conn.execute(text("DROP INDEX IF EXISTS idx_events_content_type"))
            await conn.run_sync(Base.metadata.tables["content_events"].create)
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_events_content_type ON content_events(content_id, event_type)"))
    except Exception:
        pass
