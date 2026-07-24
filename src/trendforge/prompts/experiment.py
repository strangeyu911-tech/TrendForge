"""A/B 实验 — 创建、分桶、显著性检验"""
from __future__ import annotations
import hashlib
import math
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from models import PromptExperiment, ExperimentAssignment, Content, ContentEvent


class ExperimentManager:
    """A/B 实验管理：分桶、查询、显著性检验"""

    async def create(
        self, session: AsyncSession, *,
        experiment_id: str, agent: str, scene: str,
        control_version: str, treatment_version: str,
        traffic_split: dict | None = None,
        target_metrics: list[str] | None = None,
        min_sample_size: int = 1000,
    ) -> PromptExperiment:
        exp = PromptExperiment(
            experiment_id=experiment_id, agent=agent, scene=scene,
            control_version=control_version, treatment_version=treatment_version,
            traffic_split=traffic_split or {"control": 0.5, "treatment": 0.5},
            target_metrics=target_metrics or ["ctr"],
            min_sample_size=min_sample_size,
        )
        session.add(exp)
        await session.flush()
        return exp

    def assign(self, experiment_id: str, content_id: str, traffic_split: dict) -> str:
        """基于 content_id 哈希分桶（确定性）"""
        h = int(hashlib.md5(f"{experiment_id}:{content_id}".encode()).hexdigest()[:8], 16) % 100
        cum = 0
        for variant, ratio in traffic_split.items():
            cum += int(ratio * 100)
            if h < cum:
                return variant
        return list(traffic_split.keys())[-1]

    async def assign_and_record(
        self, session: AsyncSession, experiment_id: str, content_id: str,
    ) -> str:
        exp = await session.get(PromptExperiment, experiment_id)
        if exp is None:
            raise ValueError(f"实验 {experiment_id} 不存在")
        existing = await session.get(ExperimentAssignment, (content_id, experiment_id))
        if existing:
            return existing.variant
        variant = self.assign(experiment_id, content_id, exp.traffic_split)
        session.add(ExperimentAssignment(
            content_id=content_id, experiment_id=experiment_id, variant=variant,
        ))
        await session.flush()
        return variant

    async def report(
        self, session: AsyncSession, experiment_id: str,
    ) -> dict:
        """生成 A/B 实验报告（CTR 指标 + Z 检验）"""
        exp = await session.get(PromptExperiment, experiment_id)
        if exp is None:
            raise ValueError(f"实验 {experiment_id} 不存在")

        # 取对照组/实验组的 content_id
        stmt = select(ExperimentAssignment).where(ExperimentAssignment.experiment_id == experiment_id)
        assigns = (await session.execute(stmt)).scalars().all()
        groups: dict[str, list[str]] = {"control": [], "treatment": []}
        for a in assigns:
            groups.setdefault(a.variant, []).append(a.content_id)

        # 计算每组 CTR
        stats = {}
        for variant, cids in groups.items():
            if not cids:
                stats[variant] = {"n": 0, "impressions": 0, "clicks": 0, "ctr": 0.0}
                continue
            ev_stmt = select(ContentEvent).where(
                and_(ContentEvent.content_id.in_(cids), ContentEvent.event_type.in_(["exposed", "clicked"]))
            )
            events = (await session.execute(ev_stmt)).scalars().all()
            imp = sum(1 for e in events if e.event_type == "exposed")
            clk = sum(1 for e in events if e.event_type == "clicked")
            stats[variant] = {
                "n": len(cids), "impressions": imp, "clicks": clk,
                "ctr": round(clk / imp, 4) if imp else 0.0,
            }

        # Z 检验
        c = stats.get("control", {})
        t = stats.get("treatment", {})
        lift, z, p, sig = self._z_test(c, t)
        version_map = {"control": exp.control_version, "treatment": exp.treatment_version}
        return {
            "experiment_id": experiment_id,
            "control": {**c, "version": exp.control_version},
            "treatment": {**t, "version": exp.treatment_version},
            "lift_pct": round(lift * 100, 2),
            "z_score": round(z, 4),
            "p_value": round(p, 4),
            "significant": sig,
            "conclusion": self._conclude(c, t, sig, version_map),
        }

    @staticmethod
    def _z_test(c: dict, t: dict) -> tuple[float, float, float, bool]:
        """两比例 Z 检验"""
        n1, x1 = c.get("impressions", 0), c.get("clicks", 0)
        n2, x2 = t.get("impressions", 0), t.get("clicks", 0)
        if n1 == 0 or n2 == 0:
            return 0.0, 0.0, 1.0, False
        p1, p2 = x1 / n1, x2 / n2
        p_pool = (x1 + x2) / (n1 + n2)
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        if se == 0:
            return 0.0, 0.0, 1.0, False
        z = (p2 - p1) / se
        # 双侧 p-value（标准正态）
        p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        lift = (p2 - p1) / p1 if p1 else 0.0
        return lift, z, p_value, p_value < 0.05

    @staticmethod
    def _conclude(c: dict, t: dict, sig: bool, version_map: dict) -> str:
        if not sig:
            return "无显著差异，建议延长实验"
        if t.get("ctr", 0) > c.get("ctr", 0):
            return f"treatment({version_map['treatment']}) 胜出，建议升版"
        return f"control({version_map['control']}) 胜出，终止实验"

    async def conclude(self, session: AsyncSession, experiment_id: str, winner: str | None = None) -> None:
        exp = await session.get(PromptExperiment, experiment_id)
        if exp:
            exp.status = "concluded"
            exp.end_at = datetime.utcnow()
            if winner:
                exp.result = {"winner": winner}
            await session.flush()
