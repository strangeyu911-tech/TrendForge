"""数据分析 — CTR、阅读率、Prompt 效果、漏斗、Bad Case 统计"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from models import Content, ContentEvent, BadCase


class Analytics:
    """SQL 数据分析查询"""

    async def funnel(self, session: AsyncSession, days: int = 7) -> dict:
        """漏斗分析：曝光→点击→阅读→完读"""
        since = datetime.utcnow() - timedelta(days=days)
        stmt = select(ContentEvent.event_type, func.count()).where(
            ContentEvent.event_ts >= since
        ).group_by(ContentEvent.event_type)
        rows = (await session.execute(stmt)).all()
        counts = {r[0]: r[1] for r in rows}
        imp = counts.get("exposed", 0)
        clk = counts.get("clicked", 0)
        reads = counts.get("read", 0)
        fin = counts.get("finished", 0)
        return {
            "impressions": imp, "clicks": clk, "reads": reads, "finishes": fin,
            "ctr": round(clk / imp, 4) if imp else 0.0,
            "read_rate": round(reads / clk, 4) if clk else 0.0,
            "finish_rate": round(fin / reads, 4) if reads else 0.0,
        }

    async def ctr_by_category(self, session: AsyncSession, days: int = 7) -> list[dict]:
        """分品类 CTR"""
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                Content.category,
                func.count(func.distinct(ContentEvent.content_id)).label("articles"),
                func.sum(case((ContentEvent.event_type == "exposed", 1), else_=0)).label("imp"),
                func.sum(case((ContentEvent.event_type == "clicked", 1), else_=0)).label("clk"),
            )
            .join(Content, Content.content_id == ContentEvent.content_id)
            .where(ContentEvent.event_ts >= since)
            .group_by(Content.category)
        )
        rows = (await session.execute(stmt)).all()
        return [{
            "category": r.category, "articles": r.articles,
            "impressions": r.imp, "clicks": r.clk,
            "ctr": round(r.clk / r.imp, 4) if r.imp else 0.0,
        } for r in rows]

    async def prompt_effect(self, session: AsyncSession, days: int = 14) -> list[dict]:
        """各 Prompt 版本效果对比"""
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                Content.prompt_writer_v.label("version"),
                func.count().label("articles"),
                func.avg(Content.quality_overall).label("quality"),
                func.avg(Content.fact_consistency).label("fact"),
                func.sum(case((Content.is_bad_case, 1), else_=0)).label("bad"),
                func.sum(ContentEvent.id).label("ev"),  # 占位
            )
            .outerjoin(ContentEvent, Content.content_id == ContentEvent.content_id)
            .where(Content.published_at >= since)
            .group_by(Content.prompt_writer_v)
        )
        rows = (await session.execute(stmt)).all()
        # 单独算 CTR（需 join events）
        result = []
        for r in rows:
            if not r.version:
                continue
            ctr = await self._ctr_for_version(session, r.version, since)
            bad_rate = round(r.bad / r.articles, 4) if r.articles else 0.0
            result.append({
                "prompt_version": r.version, "articles": r.articles,
                "avg_quality": round(r.quality or 0, 2),
                "avg_fact_consistency": round(r.fact or 0, 4),
                "bad_case_rate": bad_rate, "ctr": ctr,
            })
        return result

    async def _ctr_for_version(self, session: AsyncSession, version: str, since: datetime) -> float:
        stmt = (
            select(
                func.sum(case((ContentEvent.event_type == "exposed", 1), else_=0)).label("imp"),
                func.sum(case((ContentEvent.event_type == "clicked", 1), else_=0)).label("clk"),
            )
            .join(Content, Content.content_id == ContentEvent.content_id)
            .where(and_(Content.prompt_writer_v == version, ContentEvent.event_ts >= since))
        )
        r = (await session.execute(stmt)).first()
        return round(r.clk / r.imp, 4) if r and r.imp else 0.0

    async def bad_case_stats(self, session: AsyncSession, days: int = 30) -> dict:
        """Bad Case 统计"""
        since = datetime.utcnow() - timedelta(days=days)
        # 按一级分类
        stmt = select(BadCase.category_l1, func.count()).where(
            BadCase.created_at >= since
        ).group_by(BadCase.category_l1)
        rows = (await session.execute(stmt)).all()
        by_category = {r[0]: r[1] for r in rows}
        total = sum(by_category.values())
        # 按状态
        stmt2 = select(BadCase.status, func.count()).where(BadCase.created_at >= since).group_by(BadCase.status)
        rows2 = (await session.execute(stmt2)).all()
        by_status = {r[0]: r[1] for r in rows2}
        # 严重度
        stmt3 = select(BadCase.severity, func.count()).where(BadCase.created_at >= since).group_by(BadCase.severity)
        rows3 = (await session.execute(stmt3)).all()
        by_severity = {r[0]: r[1] for r in rows3}
        return {
            "total": total, "by_category": by_category,
            "by_status": by_status, "by_severity": by_severity,
            "critical_rate": round(by_severity.get("critical", 0) / total, 4) if total else 0.0,
        }

    async def production_stats(self, session: AsyncSession, days: int = 7) -> dict:
        """生产效率统计"""
        since = datetime.utcnow() - timedelta(days=days)
        stmt = select(
            func.count().label("total"),
            func.avg(Content.review_rounds).label("avg_rounds"),
            func.avg(Content.word_count).label("avg_wc"),
            func.sum(case((Content.is_bad_case, 1), else_=0)).label("bad"),
        ).where(Content.published_at >= since)
        r = (await session.execute(stmt)).first()
        return {
            "total_articles": r.total, "avg_review_rounds": round(r.avg_rounds or 0, 2),
            "avg_word_count": int(r.avg_wc or 0),
            "bad_case_count": r.bad,
            "bad_case_rate": round(r.bad / r.total, 4) if r.total else 0.0,
        }

    async def cost_stats(self, session: AsyncSession, days: int = 7) -> dict:
        """成本统计（从 Task 表聚合）"""
        from models import Task
        since = datetime.utcnow() - timedelta(days=days)
        stmt = select(
            func.count().label("tasks"),
            func.avg(Task.total_cost_cny).label("avg_cost"),
            func.sum(Task.total_cost_cny).label("total_cost"),
            func.avg(Task.total_duration_ms).label("avg_dur"),
        ).where(and_(Task.created_at >= since, Task.status == "succeeded"))
        r = (await session.execute(stmt)).first()
        return {
            "tasks": r.tasks, "total_cost": round(r.total_cost or 0, 2),
            "avg_cost_per_task": round(r.avg_cost or 0, 4),
            "avg_duration_sec": round((r.avg_dur or 0) / 1000, 1),
        }

    # ---- 平台化升级：按国家/语言/平台的全球化效果分析 ----
    async def performance_by_country(self, session: AsyncSession, days: int = 7) -> list[dict]:
        """不同国家的 CTR / 阅读完成率 / 互动 / 负反馈"""
        return await self._performance_by(session, ContentEvent.country, days)

    async def performance_by_language(self, session: AsyncSession, days: int = 7) -> list[dict]:
        """不同语言的阅读完成率"""
        return await self._performance_by(session, ContentEvent.language, days)

    async def performance_by_platform(self, session: AsyncSession, days: int = 7) -> list[dict]:
        """不同分发平台的效果"""
        return await self._performance_by(session, ContentEvent.platform, days)

    async def _performance_by(self, session: AsyncSession, group_col, days: int) -> list[dict]:
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                group_col.label("dim"),
                func.sum(case((ContentEvent.event_type == "exposed", 1), else_=0)).label("imp"),
                func.sum(case((ContentEvent.event_type == "clicked", 1), else_=0)).label("clk"),
                func.sum(case((ContentEvent.event_type == "finished", 1), else_=0)).label("fin"),
                func.avg(ContentEvent.finish_rate).label("avg_fr"),
                func.sum(ContentEvent.like_count).label("likes"),
                func.sum(ContentEvent.share_count).label("shares"),
                func.sum(ContentEvent.negative_feedback).label("neg"),
            )
            .where(ContentEvent.event_ts >= since)
            .group_by(group_col)
        )
        rows = (await session.execute(stmt)).all()
        return [{
            "dim": r.dim or "unknown", "impressions": r.imp, "clicks": r.clk,
            "ctr": round(r.clk / r.imp, 4) if r.imp else 0.0,
            "finish_rate": round(r.avg_fr or 0, 4),
            "likes": r.likes or 0, "shares": r.shares or 0, "negative_feedback": r.neg or 0,
        } for r in rows]

    async def prompt_roi(self, session: AsyncSession, days: int = 14) -> list[dict]:
        """Prompt 版本 ROI：质量/事实一致性/CTR/单篇成本"""
        from models import Task
        since = datetime.utcnow() - timedelta(days=days)
        base = await self.prompt_effect(session, days)
        out = []
        for r in base:
            v = r["prompt_version"]
            # 该版本平均单篇成本
            cstmt = select(func.avg(Task.total_cost_cny)).where(
                and_(Task.status == "succeeded", Task.created_at >= since))
            avg_cost = (await session.execute(cstmt)).scalar() or 0.0
            out.append({**r, "avg_cost_per_article": round(avg_cost, 4),
                        "roi": round(r["avg_quality"] / (avg_cost or 0.001), 2)})
        return out


analytics = Analytics()
