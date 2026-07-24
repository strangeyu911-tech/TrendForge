"""Writer Agent — 内容生成（真实 LLM，强制引用）"""
from __future__ import annotations
from config import settings
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class WriterAgent(BaseAgent):
    name = "writer"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        topic = inputs.get("topic", ctx.topic)
        evidences = inputs.get("evidences", [])
        outline = inputs.get("outline", [])
        content_style = inputs.get("content_style", ctx.content_style)
        template_type = inputs.get("template", content_style)
        constraints = inputs.get("constraints", {
            "min_words": 400, "max_words": 1200,
            "must_cite_all_evidences": True, "tone": "objective",
            "content_style": content_style, "country": ctx.country,
            "target_audience": ctx.target_audience,
        })
        # 渲染 Prompt（生产版本，注入大纲与全球化策略）
        rendered, version = await ctx.pm.render_production(
            ctx.session, "writer", template_type, ctx.language,
            {"topic": topic, "evidences": evidences, "constraints": constraints,
             "template_type": template_type, "outline": outline,
             "content_style": content_style, "country": ctx.country},
        )
        ctx.prompt_versions["writer"] = version
        # 调 LLM
        resp = await ctx.llm.chat(rendered, model=settings.writer_model, json_mode=True, temperature=0.7)
        article = self._build(resp.text, topic, evidences, ctx.language)
        citations = self._validate_citations(article, evidences)
        wc = article.get("word_count", 0)
        warnings = []
        if wc < constraints["min_words"]:
            warnings.append(f"word_count_low:{wc}")
        if wc > constraints["max_words"]:
            warnings.append(f"word_count_high:{wc}")
        if constraints.get("must_cite_all_evidences") and len(citations) < len(evidences):
            warnings.append(f"citation_coverage:{len(citations)}/{len(evidences)}")
        return {
            "article": article, "citations": citations,
            "prompt_version": version, "_llm_resp": resp,
            "_warnings": warnings or None,
            "_decision": {"reason": f"按风格={content_style}、国家={ctx.country}生成，引用{len(citations)}/{len(evidences)}条证据，字数={wc}",
                          "details": {"content_style": content_style, "cited": len(citations), "word_count": wc}},
        }

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        """降级：规则拼接结构化稿件"""
        topic = ctx.topic
        evidences = ctx.topic.get("_evidences", [])
        body = []
        if topic.get("summary"):
            body.append({"type": "paragraph", "text": topic["summary"], "citations": ["ev_001"] if evidences else []})
        for ev in evidences[:3]:
            body.append({"type": "paragraph", "text": ev.get("content", "")[:200], "citations": [ev.get("evidence_id", "")]})
        wc = sum(len(b.get("text", "")) for b in body)
        article = {
            "title": f"[快讯] {topic.get('title', '热点')}", "summary": topic.get("summary", ""),
            "body": body, "tags": [topic.get("category", "news")], "word_count": wc, "language": ctx.language,
        }
        return {"article": article, "citations": [], "_warnings": [f"rule_based:{error}"]}

    def _build(self, text: str, topic: dict, evidences: list, language: str) -> dict:
        try:
            data = extract_json(text)
            if isinstance(data, dict) and "article" in data:
                data = data["article"]
        except Exception:
            # LLM 输出非 JSON，基于证据兜底
            data = {
                "title": topic.get("title", "热点报道"),
                "summary": topic.get("summary", ""),
                "body": [{"type": "paragraph", "text": e["content"][:200], "citations": [e["evidence_id"]]} for e in evidences[:5]],
                "tags": [topic.get("category", "news")], "language": language,
            }
        body = data.get("body", [])
        data["word_count"] = data.get("word_count") or sum(len(str(b.get("text", ""))) for b in body)
        data.setdefault("language", language)
        data.setdefault("tags", [topic.get("category", "news")])
        return data

    def _validate_citations(self, article: dict, evidences: list) -> list[str]:
        valid = {e["evidence_id"] for e in evidences}
        cited = set()
        for b in article.get("body", []):
            for c in b.get("citations", []):
                if c in valid:
                    cited.add(c)
        return sorted(cited)
