"""Writer Agent：内容生成"""
from __future__ import annotations
import time
from .base import BaseAgent, TaskContext, AgentError
from llm import call_llm, extract_json
from prompts.manager import PromptManager
from config import CONFIG


class WriterAgent(BaseAgent):
    name = "writer"
    version = "2.0.1"

    def __init__(self, prompt_manager: PromptManager | None = None):
        self.pm = prompt_manager or PromptManager()

    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        t0 = time.time()
        topic = inputs.get("topic", {})
        evidences = inputs.get("evidences", [])
        template = inputs.get("template", "deep_dive")
        language = inputs.get("language", ctx.language)
        constraints = inputs.get("constraints", {
            "min_words": 400, "max_words": 1200,
            "must_cite_all_evidences": True, "tone": "objective",
        })
        prompt_version = ctx.prompt_versions.get("writer", "v2.0.1")

        try:
            # 1. 加载 Prompt 模板
            prompt_text = self.pm.render("writer", template, language, prompt_version, {
                "topic": topic, "evidences": evidences,
                "constraints": constraints, "template_type": template,
            })
            # 2. 调 LLM
            llm_resp = call_llm(prompt_text, model=CONFIG.writer_model, response_format={"type": "json_object"})
            # 3. 解析输出
            article = self._build_article(llm_resp.text, topic, evidences, language)
            # 4. 引用校验
            citations = self._validate_citations(article, evidences)
            # 5. 字数校验
            wc = article.get("word_count", 0)
            warnings = []
            if wc < constraints["min_words"]:
                warnings.append(f"word_count_low:{wc}")
            if wc > constraints["max_words"]:
                warnings.append(f"word_count_high:{wc}")

            self._record_span(ctx, "degraded" if warnings else "ok", t0, llm_resp, warnings)
            return {"article": article, "citations": citations, "prompt_version": prompt_version}
        except Exception as e:
            self._record_span(ctx, "failed", t0)
            return await self.fallback(ctx, AgentError(self.name, str(e)))

    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        """降级：用规则拼接一篇结构化稿件"""
        t0 = time.time()
        self._record_span(ctx, "degraded", t0, warnings=["rule_based_fallback"])
        topic = ctx.topic or "未命名话题"
        article = {
            "title": f"[快讯] {topic}",
            "summary": f"关于「{topic}」的简要报道。",
            "body": [{"type": "paragraph", "text": f"据多方消息，{topic}。具体细节待进一步核实。", "citations": []}],
            "tags": ["AI生成", "快讯"],
            "cover_suggestion": "",
            "word_count": 50,
            "language": ctx.language,
        }
        return {"article": article, "citations": [], "degraded": True, "reason": str(error)}

    def _build_article(self, text: str, topic: dict, evidences: list, language: str) -> dict:
        try:
            data = extract_json(text)
        except Exception:
            # 模拟模式：直接构造一篇基于证据的稿件
            return self._article_from_evidences(topic, evidences, language)

        if isinstance(data, dict) and "article" in data:
            data = data["article"]
        body = data.get("body", [])
        wc = sum(len(str(b.get("text", ""))) for b in body)
        data.setdefault("word_count", wc)
        data.setdefault("language", language)
        return data

    def _article_from_evidences(self, topic: dict, evidences: list, language: str) -> dict:
        """基于证据拼接稿件（模拟 LLM 输出）"""
        title = topic.get("title", "热点报道")
        summary = topic.get("summary", "")
        body = []
        if summary:
            body.append({"type": "paragraph", "text": summary, "citations": ["ev_001"] if evidences else []})

        # 按证据构造段落
        for ev in evidences[:5]:
            body.append({
                "type": "paragraph",
                "text": ev["content"][:200],
                "citations": [ev["evidence_id"]],
            })

        # 加标题段
        body.insert(1, {"type": "heading", "text": "详细报道"})

        wc = sum(len(str(b.get("text", ""))) for b in body)
        return {
            "title": title,
            "summary": summary or title,
            "body": body,
            "tags": [topic.get("category", "news"), "AI生成"],
            "cover_suggestion": f"关于「{title}」的科技感封面",
            "word_count": wc,
            "language": language,
        }

    def _validate_citations(self, article: dict, evidences: list) -> list[str]:
        valid_ids = {e["evidence_id"] for e in evidences}
        cited = set()
        for block in article.get("body", []):
            for c in block.get("citations", []):
                if c in valid_ids:
                    cited.add(c)
        return sorted(cited)
