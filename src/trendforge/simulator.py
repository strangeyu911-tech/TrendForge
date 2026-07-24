"""数据反馈闭环模拟器 — 为已发布内容生成符合产品逻辑的用户行为事件

产品逻辑（演示用模拟，但符合真实产品规律）：
- 高质量内容 CTR 更高；bad_case 内容 CTR/完读显著下降
- 不同内容风格完读率不同：summary/brief 完读高，deep_dive 中等
- 不同国家有修正（日本 summary 文化完读更高，巴西偏低）
- 事件流：exposed → clicked → read → finished + like/share/negative_feedback
- 跑完后把 CTR/完读率回流到 writer Prompt.eval_score（闭环 → Prompt 生命周期）
"""
from __future__ import annotations
import random
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from models import Content, ContentEvent
from config import COUNTRY_STRATEGIES


class EventSimulator:
    async def simulate(self, session: AsyncSession, content_id: str | None = None,
                       per_content: int = 50) -> dict:
        stmt = select(Content).where(Content.published_at.isnot(None))
        if content_id:
            stmt = stmt.where(Content.content_id == content_id)
        contents = (await session.execute(stmt)).scalars().all()
        total = 0
        for c in contents:
            total += await self._simulate_one(session, c, per_content)
        await session.flush()
        # 回流 Prompt 效果分
        backfill = await self.backfill_prompt_scores(session)
        return {"contents": len(contents), "events_generated": total, "prompt_backfill": backfill}

    async def _simulate_one(self, session: AsyncSession, content: Content, n: int) -> int:
        country = content.country or "US"
        lang = content.language or "en"
        strat = COUNTRY_STRATEGIES.get(country, COUNTRY_STRATEGIES["US"])
        platforms = content.channels or strat["platforms"]
        quality = content.quality_overall or 3.5
        is_bad = content.is_bad_case
        style = content.content_style or "deep_dive"

        # 基础转化率（受质量/风格/国家影响）
        base_ctr = 0.05 + (quality - 3.5) * 0.02
        if style in ("summary", "brief", "breaking_news"):
            finish_rate = 0.70
        elif style in ("deep_dive", "analysis", "industry_analysis"):
            finish_rate = 0.45
        else:
            finish_rate = 0.55
        if country == "JP":
            finish_rate *= 1.15
        if country == "BR":
            finish_rate *= 0.90
        if is_bad:
            base_ctr *= 0.4
            finish_rate *= 0.5
        base_ctr = max(0.02, min(0.25, base_ctr))
        finish_rate = max(0.10, min(0.95, finish_rate))

        events = 0
        pub = content.published_at or (datetime.utcnow() - timedelta(hours=random.randint(1, 72)))
        for _ in range(n):
            uid = f"u_{uuid.uuid4().hex[:8]}"
            plat = random.choice(platforms) if platforms else "web_feed"
            ts = pub + timedelta(minutes=random.randint(1, 60 * 48))
            # exposed
            session.add(self._ev(content.content_id, uid, "exposed", plat, country, lang, ts))
            events += 1
            if random.random() < base_ctr:
                session.add(self._ev(content.content_id, uid, "clicked", plat, country, lang,
                                     ts + timedelta(seconds=random.randint(1, 30))))
                events += 1
                read_dur = random.randint(20, 300)
                session.add(self._ev(content.content_id, uid, "read", plat, country, lang,
                                     ts + timedelta(seconds=60), read_duration_sec=read_dur))
                events += 1
                fr = finish_rate * random.uniform(0.8, 1.0)
                if random.random() < fr:
                    session.add(self._ev(content.content_id, uid, "finished", plat, country, lang,
                                         ts + timedelta(seconds=read_dur), finish_rate=round(min(1.0, fr), 4)))
                    events += 1
                if random.random() < 0.15:
                    session.add(self._ev(content.content_id, uid, "interacted", plat, country, lang,
                                         ts + timedelta(seconds=90), action_type="like", like_count=1))
                    events += 1
                if random.random() < 0.08:
                    session.add(self._ev(content.content_id, uid, "interacted", plat, country, lang,
                                         ts + timedelta(seconds=120), action_type="share", share_count=1))
                    events += 1
                if is_bad and random.random() < 0.20:
                    session.add(self._ev(content.content_id, uid, "interacted", plat, country, lang,
                                         ts + timedelta(seconds=150), action_type="negative", negative_feedback=1))
                    events += 1
        return events

    def _ev(self, content_id, user_id, event_type, plat, country, lang, ts, **extra) -> ContentEvent:
        return ContentEvent(content_id=content_id, user_id=user_id, event_type=event_type,
                            channel=plat, country=country, language=lang, platform=plat, event_ts=ts, **extra)

    async def backfill_prompt_scores(self, session: AsyncSession) -> list[dict]:
        """把各 writer Prompt 版本的 CTR/完读率回流到 prompt.eval_score（闭环）"""
        from prompts.manager import PromptManager
        pm = PromptManager()
        since = datetime.utcnow() - timedelta(days=30)
        # 按 prompt_writer_v 聚合 CTR 与完读率
        stmt = (
            select(
                Content.prompt_writer_v.label("version"),
                func.sum(case((ContentEvent.event_type == "exposed", 1), else_=0)).label("imp"),
                func.sum(case((ContentEvent.event_type == "clicked", 1), else_=0)).label("clk"),
                func.avg(ContentEvent.finish_rate).label("avg_fr"),
            )
            .outerjoin(ContentEvent, Content.content_id == ContentEvent.content_id)
            .where(and_(Content.published_at >= since, Content.prompt_writer_v != ""))
            .group_by(Content.prompt_writer_v)
        )
        rows = (await session.execute(stmt)).all()
        out = []
        for r in rows:
            if not r.version or not r.imp:
                continue
            ctr = round(r.clk / r.imp, 4)
            fr = round(r.avg_fr or 0, 4)
            score = round(ctr * 0.6 + fr * 0.4, 4)  # 综合效果分
            await pm.update_eval_score(session, "writer_deep_dive", r.version, score,
                                       {"ctr": ctr, "finish_rate": fr})
            out.append({"version": r.version, "ctr": ctr, "finish_rate": fr, "eval_score": score})
        await session.flush()
        return out


simulator = EventSimulator()
