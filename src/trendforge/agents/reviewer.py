"""Reviewer Agent — 质量审核与事实核查（真实 LLM + 规则合规）"""
from __future__ import annotations
from config import settings
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        topic = inputs.get("topic", ctx.topic)
        evidences = inputs.get("evidences", [])
        article = inputs.get("article", {})
        policy = inputs.get("review_policy", {"min_quality_score": 3.5, "fact_check_strict": True})
        # 1. 规则合规扫描（必须先做，LLM 失败也保底）
        compliance = self._compliance_scan(article)
        # 2. LLM 审核
        rendered, version = await ctx.pm.render_production(
            ctx.session, "reviewer", "check", ctx.language,
            {"article": article, "evidences": evidences},
        )
        ctx.prompt_versions["reviewer"] = version
        resp = await ctx.llm.chat(rendered, model=settings.reviewer_model, json_mode=True, temperature=0.1)
        result = self._parse(resp.text, article, evidences)
        # 用规则合规覆盖 LLM 合规结果（规则更可信）
        result["compliance"] = compliance
        # 裁决：合规命中强制 reject
        if compliance["sensitive_hits"]:
            result["verdict"] = "reject"
            result["bad_case_flag"] = True
            result["revision_suggestions"].append({
                "section": "title/body", "issue": "命中敏感词",
                "fix": f"移除：{compliance['sensitive_hits']}",
            })
        elif result["fact_check"]["inconsistent"] > 0:
            result["verdict"] = "revise"
        elif result["quality_scores"]["overall"] < policy.get("min_quality_score", 3.5):
            result["verdict"] = "revise"
        verdict = result["verdict"]
        return {**result, "prompt_version": version, "_llm_resp": resp,
                "_decision": {"reason": f"裁决={verdict}，质量={result['quality_scores']['overall']}，事实不一致={result['fact_check']['inconsistent']}，合规命中={len(compliance['sensitive_hits'])}",
                              "details": {"verdict": verdict, "quality": result["quality_scores"]["overall"],
                                          "fact_inconsistent": result["fact_check"]["inconsistent"],
                                          "sensitive_hits": compliance["sensitive_hits"]}}}

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        """合规审核失败 → 强制保守 reject + 人工"""
        return {
            "verdict": "reject", "bad_case_flag": True,
            "quality_scores": {"readability": 0, "objectivity": 0, "completeness": 0, "timeliness": 0, "overall": 0},
            "fact_check": {"checked_claims": 0, "consistent": 0, "inconsistent": 0, "details": []},
            "compliance": {"sensitive_hits": ["review_engine_failed"], "copyright_risk": "unknown", "politics_risk": "unknown"},
            "revision_suggestions": [{"section": "all", "issue": "审核引擎失败", "fix": "转人工审核"}],
            "_warnings": [f"force_reject:{error}"],
        }

    def _compliance_scan(self, article: dict) -> dict:
        full = (article.get("title", "") + " " + article.get("summary", ""))
        for b in article.get("body", []):
            full += " " + b.get("text", "")
        hits = [w for w in settings.sensitive_words if w in full]
        return {"sensitive_hits": hits, "copyright_risk": "low", "politics_risk": "review" if hits else "none"}

    def _parse(self, text: str, article: dict, evidences: list) -> dict:
        defaults = {
            "verdict": "revise",
            "quality_scores": {"readability": 3.5, "objectivity": 3.5, "completeness": 3.5, "timeliness": 4.0, "overall": 3.6},
            "fact_check": {"checked_claims": 0, "consistent": 0, "inconsistent": 0, "details": []},
            "compliance": {"sensitive_hits": [], "copyright_risk": "low", "politics_risk": "none"},
            "revision_suggestions": [], "bad_case_flag": False,
        }
        try:
            data = extract_json(text)
            if isinstance(data, dict):
                defaults.update({k: v for k, v in data.items() if v is not None})
        except Exception:
            pass
        # 规则补充事实核查
        fc = self._rule_fact_check(article, evidences)
        if fc["inconsistent"] > defaults["fact_check"]["inconsistent"]:
            defaults["fact_check"] = fc
        return defaults

    def _rule_fact_check(self, article: dict, evidences: list) -> dict:
        ev_map = {e["evidence_id"]: e for e in evidences}
        consistent, inconsistent, details = 0, 0, []
        for b in article.get("body", []):
            if b.get("type") != "paragraph":
                continue
            citations = b.get("citations", [])
            text = b.get("text", "")
            if not citations and len(text) > 30:
                inconsistent += 1
                details.append({"section": text[:30], "status": "no_citation", "reason": "段落无引用"})
                continue
            for cid in citations:
                if cid not in ev_map:
                    inconsistent += 1
                    details.append({"section": text[:30], "evidence_id": cid, "status": "invalid_citation", "reason": "引用不存在"})
                else:
                    consistent += 1
        return {"checked_claims": consistent + inconsistent, "consistent": consistent, "inconsistent": inconsistent, "details": details}
