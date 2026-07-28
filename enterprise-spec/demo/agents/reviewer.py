"""Reviewer Agent：质量审核与事实核查"""
from __future__ import annotations
import time
import re
from .base import BaseAgent, TaskContext, AgentError
from llm import call_llm
from config import CONFIG

# 敏感词示例（实际应从词库加载）
SENSITIVE_WORDS = ["震惊", "惊呆", "必看", "内部消息", "据传"]


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    version = "1.3.0"

    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        t0 = time.time()
        topic = inputs.get("topic", {})
        evidences = inputs.get("evidences", [])
        article = inputs.get("article", {})
        policy = inputs.get("review_policy", {
            "min_quality_score": 3.5,
            "fact_check_strict": True,
            "compliance_rules": ["sensitive_words"],
        })

        try:
            # 1. 事实核查
            fact_check = self._fact_check(article, evidences)
            # 2. 合规扫描
            compliance = self._compliance_scan(article, policy)
            # 3. 质量打分
            quality_scores = self._quality_score(article, evidences, topic)
            # 4. 裁决
            verdict, suggestions, bad_case = self._decide(
                fact_check, compliance, quality_scores, policy
            )

            llm_resp = call_llm("review scoring", model=CONFIG.reviewer_model)  # 占位
            self._record_span(ctx, "ok", t0, llm_resp)

            return {
                "verdict": verdict,
                "quality_scores": quality_scores,
                "fact_check": fact_check,
                "compliance": compliance,
                "revision_suggestions": suggestions,
                "bad_case_flag": bad_case,
            }
        except Exception as e:
            self._record_span(ctx, "failed", t0)
            return await self.fallback(ctx, AgentError(self.name, str(e)))

    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        """合规审核失败时强制保守 reject"""
        t0 = time.time()
        self._record_span(ctx, "degraded", t0, warnings=["compliance_failed_force_reject"])
        return {
            "verdict": "reject",
            "quality_scores": {"readability": 0, "objectivity": 0, "completeness": 0, "timeliness": 0, "overall": 0},
            "fact_check": {"checked_claims": 0, "consistent": 0, "inconsistent": 0, "details": []},
            "compliance": {"sensitive_hits": ["review_engine_failed"], "copyright_risk": "unknown", "politics_risk": "unknown"},
            "revision_suggestions": [{"section": "all", "issue": "审核引擎失败", "fix": "转人工审核"}],
            "bad_case_flag": True,
            "degraded": True,
        }

    def _fact_check(self, article: dict, evidences: list) -> dict:
        """校验每个引用是否真实存在 + 段落是否有未引用断言"""
        ev_map = {e["evidence_id"]: e for e in evidences}
        consistent, inconsistent, details = 0, 0, []
        for block in article.get("body", []):
            if block.get("type") != "paragraph":
                continue
            citations = block.get("citations", [])
            text = block.get("text", "")
            if not citations and len(text) > 30:
                # 有内容但无引用 → 标记可疑
                inconsistent += 1
                details.append({"section": text[:30], "status": "no_citation", "reason": "段落无引用"})
                continue
            for cid in citations:
                if cid not in ev_map:
                    inconsistent += 1
                    details.append({"section": text[:30], "evidence_id": cid, "status": "invalid_citation", "reason": "引用 ID 不存在"})
                else:
                    consistent += 1
        return {
            "checked_claims": consistent + inconsistent,
            "consistent": consistent,
            "inconsistent": inconsistent,
            "details": details,
        }

    def _compliance_scan(self, article: dict, policy: dict) -> dict:
        full_text = article.get("title", "") + " " + article.get("summary", "")
        for b in article.get("body", []):
            full_text += " " + b.get("text", "")
        hits = [w for w in SENSITIVE_WORDS if w in full_text]
        return {
            "sensitive_hits": hits,
            "copyright_risk": "low",
            "politics_risk": "none" if not hits else "review",
        }

    def _quality_score(self, article: dict, evidences: list, topic: dict) -> dict:
        # 规则评分（Demo 版）
        wc = article.get("word_count", 0)
        readability = 4.0 if 300 <= wc <= 1200 else 3.0
        # 客观性：引用数 / 段落数
        paragraphs = [b for b in article.get("body", []) if b.get("type") == "paragraph"]
        cited_paragraphs = sum(1 for p in paragraphs if p.get("citations"))
        objectivity = round(2.0 + 2.5 * (cited_paragraphs / max(len(paragraphs), 1)), 1)
        objectivity = min(objectivity, 5.0)
        completeness = 4.0 if len(paragraphs) >= 3 else 3.0
        timeliness = 4.5  # 热点场景默认时效性高
        overall = round((readability + objectivity + completeness + timeliness) / 4, 2)
        return {
            "readability": readability, "objectivity": objectivity,
            "completeness": completeness, "timeliness": timeliness, "overall": overall,
        }

    def _decide(self, fact_check, compliance, quality, policy) -> tuple[str, list, bool]:
        suggestions = []
        # 合规命中 → reject
        if compliance["sensitive_hits"]:
            suggestions.append({"section": "title/body", "issue": "命中敏感词", "fix": f"移除：{compliance['sensitive_hits']}"})
            return "reject", suggestions, True
        # 事实不一致 → revise
        if fact_check["inconsistent"] > 0:
            suggestions.append({"section": "body", "issue": f"{fact_check['inconsistent']} 处引用问题", "fix": "补充或修正引用"})
            return "revise", suggestions, False
        # 质量不达标 → revise
        if quality["overall"] < policy.get("min_quality_score", 3.5):
            suggestions.append({"section": "all", "issue": f"质量分 {quality['overall']} 低于阈值", "fix": "优化结构与引用"})
            return "revise", suggestions, False
        return "pass", [], False
