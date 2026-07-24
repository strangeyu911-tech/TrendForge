"""Publisher Agent：内容发布与分发"""
from __future__ import annotations
import time
import hashlib
from datetime import datetime
from .base import BaseAgent, TaskContext, AgentError
from config import CONFIG


class PublisherAgent(BaseAgent):
    name = "publisher"
    version = "1.0.0"

    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        t0 = time.time()
        article = inputs.get("article", {})
        verdict = inputs.get("review_verdict", "pass")
        publish_config = inputs.get("publish_config", {
            "channels": ["site_feed", "weibo", "rss"],
            "gray_release": {"enabled": True, "initial_ratio": CONFIG.gray_initial_ratio},
        })

        if verdict != "pass":
            self._record_span(ctx, "failed", t0, warnings=[f"review_not_pass:{verdict}"])
            return {"publish_records": [], "status": "skipped", "reason": f"review verdict={verdict}"}

        try:
            content_id = self._gen_content_id(ctx)
            records = []
            for ch in publish_config["channels"]:
                records.append({
                    "channel": ch,
                    "content_id": content_id,
                    "url": f"https://trendforge.demo/{ch}/{content_id}",
                    "status": "published",
                    "published_at": datetime.now().isoformat(),
                })

            gray = publish_config.get("gray_release", {})
            gray_status = None
            if gray.get("enabled"):
                # 模拟灰度：初始 ratio，30 分钟后观察 CTR
                observed_ctr = 0.041  # 模拟值
                next_action = "scale_up" if observed_ctr >= CONFIG.gray_ctr_threshold else "rollback"
                gray_status = {
                    "current_ratio": gray.get("initial_ratio", CONFIG.gray_initial_ratio),
                    "next_action": next_action,
                    "observed_ctr": observed_ctr,
                    "observation_minutes": CONFIG.gray_observation_minutes,
                }

            metadata = {
                "content_id": content_id,
                "prompt_version": ctx.prompt_versions,
                "trace_id": ctx.trace_id,
                "topic": ctx.topic,
                "published_at": datetime.now().isoformat(),
            }

            self._record_span(ctx, "ok", t0)
            return {
                "publish_records": records,
                "gray_status": gray_status,
                "metadata": metadata,
                "content_id": content_id,
            }
        except Exception as e:
            self._record_span(ctx, "failed", t0)
            return await self.fallback(ctx, AgentError(self.name, str(e)))

    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        t0 = time.time()
        self._record_span(ctx, "degraded", t0, warnings=["publish_failed"])
        return {
            "publish_records": [],
            "status": "failed",
            "reason": str(error),
            "degraded": True,
        }

    def _gen_content_id(self, ctx: TaskContext) -> str:
        raw = f"{ctx.trace_id}:{ctx.topic}:{time.time()}"
        return f"c_{hashlib.md5(raw.encode()).hexdigest()[:12]}"

    def retract(self, content_id: str, channels: list[str]) -> dict:
        """撤回机制"""
        return {
            "content_id": content_id,
            "retracted_channels": channels,
            "retracted_at": datetime.now().isoformat(),
            "status": "retracted",
        }
