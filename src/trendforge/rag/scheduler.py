"""每日 RSS 增量采集调度器 — APScheduler 后台任务"""
from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import settings

_scheduler: AsyncIOScheduler | None = None


async def _daily_update_job():
    """每日定时增量采集"""
    from db import async_session
    from .collector import update
    try:
        async with async_session() as session:
            stats = await update(session)
            print(f"[scheduler] 每日增量采集完成: {stats}")
    except Exception as e:
        print(f"[scheduler] 每日采集失败: {e}")


def start_scheduler():
    """启动后台调度（每天 collector_daily_hour 点增量采集）"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _daily_update_job,
        CronTrigger(hour=settings.collector_daily_hour, minute=0),
        id="daily_rss_update",
        replace_existing=True,
    )
    _scheduler.start()
    print(f"[scheduler] 已启动，每日 {settings.collector_daily_hour:02d}:00 增量采集")
    return _scheduler


async def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
