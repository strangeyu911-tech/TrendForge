"""Topic Selector Agent — 结合国家策略选题（8步 Workflow 第2步）

输入: {trends, country, max_topics?}
输出: {topics: [{topic_id, title, summary, category, country, language, target_audience, content_style, suggested_angles, why}]}
职责: 从趋势中结合国家内容策略选出最适合目标受众的话题
决策日志: 为什么为该国受众选这些话题
"""
from __future__ import annotations
import hashlib
import re
from difflib import SequenceMatcher
from config import COUNTRY_STRATEGIES
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


def _norm_title(s: str) -> str:
    """归一化标题：去空白与标点，保留字母数字与 CJK 字符"""
    s = (s or "").lower()
    s = re.sub(r"[\s\W_]+", "", s)
    return s


def _similarity(a: str, b: str) -> float:
    """标题相似度：字符/bigram Jaccard 与序列比取较大值（对中英文均有效）"""
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    def toks(s):
        return set(s) | {s[i:i + 2] for i in range(len(s) - 1)}
    A, B = toks(a), toks(b)
    union = len(A | B)
    jac = len(A & B) / union if union else 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    return max(jac, seq)


def _too_similar(title: str, published: list[str], thr: float = 0.62) -> bool:
    """与任一已发布标题相似度超过阈值即视为重复"""
    return any(_similarity(title, p) >= thr for p in published)


class TopicSelectorAgent(BaseAgent):
    name = "topic_selector"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        trends = inputs.get("trends", [])
        country = inputs.get("country", ctx.country)
        strat = COUNTRY_STRATEGIES.get(country, COUNTRY_STRATEGIES["US"])
        max_topics = inputs.get("max_topics", 5)
        published = inputs.get("published_titles") or []

        dedup_hint = ""
        if published:
            sample = "、".join(published[:15])
            dedup_hint = (
                f"\n【重要】以下话题已被发布过，请尽量避免重复选题"
                f"（可换角度或从其它趋势切入）：{sample}\n"
            )

        prompt = (
            f"你是内容选题官。从以下热点趋势中为【{country}/{strat['label']}】受众选出 {max_topics} 个最适合的话题。\n"
            f"目标受众: {strat['target_audience']}；偏好风格: {strat['content_styles']}；调性: {strat['tone']}\n"
            f"趋势: {trends}{dedup_hint}"
            f"输出 JSON: {{\"topics\": [{{\"title\": str, \"summary\": str, \"category\": str, \"content_style\": str, \"suggested_angles\": [str], \"why\": str}}]}}"
        )
        resp = await ctx.llm.chat(prompt, json_mode=True, temperature=0.4)
        topics = self._parse(resp.text, trends, country, strat, max_topics)
        # ---- P0: 对已发布话题去重（避免重复生产）----
        non_dup = [t for t in topics if not _too_similar(t["title"], published)]
        repeats = [t for t in topics if _too_similar(t["title"], published)]
        need = max_topics - len(non_dup)
        filled: list[dict] = []
        if need > 0 and repeats:
            # 重复项里挑"最不相似"的兜底补位，保证仍有产出
            repeats.sort(key=lambda t: -min(_similarity(t["title"], p) for p in published))
            filled = repeats[:need]
        topics = (non_dup + filled)[:max_topics]
        dedup_stats = {
            "published_count": len(published),
            "candidate_count": len(non_dup) + len(repeats),
            "filtered_repeats": len(repeats) - len(filled),
            "kept": len(topics),
        }
        return {"topics": topics, "_llm_resp": resp, "_dedup": dedup_stats,
                "_decision": {"reason": f"为{country}({strat['target_audience']})选出{len(topics)}个话题，调性={strat['tone']}",
                               "details": {"country_strategy": strat["default_style"], "audience": strat["target_audience"],
                                            "dedup": dedup_stats}}}

    def _parse(self, text: str, trends: list, country: str, strat: dict, max_topics: int) -> list[dict]:
        try:
            data = extract_json(text)
            ts = data.get("topics", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            ts = []
        if not ts and trends:
            ts = [{"title": t["title"], "summary": t.get("why", ""), "category": t.get("category", "tech"),
                   "content_style": strat["default_style"], "suggested_angles": ["综合报道"], "why": t.get("why", "")}
                  for t in trends[:max_topics]]
        out = []
        for t in ts[:max_topics]:
            key = hashlib.md5(t.get("title", "").encode()).hexdigest()[:8]
            out.append({
                "topic_id": f"topic_{key}", "title": t.get("title", ""), "summary": t.get("summary", ""),
                "category": t.get("category", "tech"), "country": country, "language": strat["language"],
                "target_audience": strat["target_audience"],
                "content_style": t.get("content_style", strat["default_style"]),
                "suggested_angles": t.get("suggested_angles", []), "heat_score": 7.0,
                "priority": "P1", "why": t.get("why", ""),
            })
        return out

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"topics": [], "_warnings": [f"topic_select_failed:{error}"]}
