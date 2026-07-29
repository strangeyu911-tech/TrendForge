"""Prompt 版本管理 — CRUD、生命周期、生产版本查询"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from models import Prompt
from .renderer import render

# 场景模板缺失时的回退顺序（保证多视角变体等不崩溃）
_DEFAULT_SCENES = ("deep_dive", "default")


class PromptManager:
    """Prompt 版本管理：不可变快照、生命周期、渲染"""

    async def create(
        self, session: AsyncSession, *,
        prompt_id: str, agent: str, scene: str, language: str = "zh",
        template: str, variables: list[str] | None = None,
        changelog: str = "", parent_version: str = "", author: str = "system",
        version: str | None = None, status: str = "draft",
    ) -> Prompt:
        # 自动版本号：该 prompt_id+language 下版本数 +1
        if version is None:
            existing = await session.execute(
                select(Prompt).where(
                    and_(Prompt.prompt_id == prompt_id, Prompt.language == language)
                )
            )
            n = len(existing.scalars().all())
            version = f"v1.{n}.0"
        p = Prompt(
            prompt_id=prompt_id, version=version, agent=agent, scene=scene,
            language=language, status=status, template=template,
            variables=variables or [], changelog=changelog,
            parent_version=parent_version, author=author,
        )
        session.add(p)
        await session.flush()
        return p

    async def get(self, session: AsyncSession, prompt_id: str, version: str) -> Prompt | None:
        return await session.get(Prompt, (prompt_id, version))

    async def list_versions(self, session: AsyncSession, prompt_id: str, language: str | None = None) -> list[Prompt]:
        stmt = select(Prompt).where(Prompt.prompt_id == prompt_id)
        if language:
            stmt = stmt.where(Prompt.language == language)
        stmt = stmt.order_by(Prompt.created_at.desc())
        res = await session.execute(stmt)
        return list(res.scalars().all())

    async def get_production(self, session: AsyncSession, agent: str, scene: str, language: str = "zh") -> Prompt | None:
        """获取当前生产版本。找不到指定语言时回退 zh，再回退任意语言（多语言健壮性）"""
        for lang in [language, "zh", None]:
            stmt = select(Prompt).where(and_(
                Prompt.agent == agent, Prompt.scene == scene, Prompt.status == "production",
            ))
            if lang is not None:
                stmt = stmt.where(Prompt.language == lang)
            res = await session.execute(stmt)
            p = res.scalars().first()
            if p:
                return p
        return None

    async def promote(self, session: AsyncSession, prompt_id: str, version: str) -> Prompt:
        """升版为 production，旧 production 归档"""
        # 归档旧 production
        old = await session.execute(select(Prompt).where(and_(
            Prompt.prompt_id == prompt_id, Prompt.status == "production",
        )))
        for o in old.scalars().all():
            o.status = "archived"
        # 升新版
        p = await session.get(Prompt, (prompt_id, version))
        if p is None:
            raise ValueError(f"Prompt {prompt_id} {version} 不存在")
        p.status = "production"
        p.approved_at = datetime.utcnow()
        await session.flush()
        return p

    async def render(self, session: AsyncSession, prompt_id: str, version: str, variables: dict) -> str:
        """加载并渲染指定版本 Prompt"""
        p = await session.get(Prompt, (prompt_id, version))
        if p is None:
            raise ValueError(f"Prompt {prompt_id} {version} 不存在")
        return render(p.template, variables)

    async def render_production(
        self, session: AsyncSession, agent: str, scene: str, language: str, variables: dict,
    ) -> tuple[str, str]:
        """渲染生产版本，返回 (渲染后文本, 版本号)。
        指定场景模板缺失时回退到默认场景（deep_dive/default），避免多视角变体因缺模板崩溃。"""
        p = await self.get_production(session, agent, scene, language)
        if p is None:
            for fb in _DEFAULT_SCENES:
                if fb != scene:
                    p = await self.get_production(session, agent, fb, language)
                    if p:
                        break
        if p is None:
            raise ValueError(f"无生产版本: {agent}/{scene}/{language}")
        return render(p.template, variables), p.version

    async def update_eval_score(self, session: AsyncSession, prompt_id: str, version: str, score: float,
                                metrics: dict | None = None) -> Prompt | None:
        """回流效果指标到 Prompt.eval_score（数据反馈闭环 → Prompt 生命周期）

        score: 综合效果分（如 CTR/阅读率加权），metrics: 明细指标
        """
        p = await session.get(Prompt, (prompt_id, version))
        if p is None:
            return None
        p.eval_score = round(score, 4)
        if metrics:
            existing_tags = list(p.tags or [])
            p.tags = existing_tags + [f"{k}={v}" for k, v in metrics.items()]
        await session.flush()
        return p


# 默认 Prompt 模板（首次启动 seed）
DEFAULT_TEMPLATES = {
    "planner_topic": {
        "agent": "planner", "scene": "topic", "language": "zh",
        "template": """你是资深热点选题策划。基于以下热点信号，输出 JSON。

策略：{{ strategy | tojson }}
信号源：{{ signals | tojson }}

要求：
1. 去重（标题语义相似>0.85视为重复）
2. 按热度打分(0-10)，考虑增速、跨源出现次数、时效性
3. 过滤敏感话题
4. 每话题给 3 个差异化角度

输出 JSON：
{"topics":[{"topic_id":"","title":"","summary":"","category":"","heat_score":0.0,"suggested_angles":["","",""],"target_languages":["zh"],"priority":"P0"}]}""",
        "variables": ["signals", "strategy"],
    },
    "writer_deep_dive": {
        "agent": "writer", "scene": "deep_dive", "language": "zh",
        "template": """你是资深{{ topic.category }}领域新闻编辑，为【{{ country }}】的{{ constraints.target_audience | default("读者") }}撰稿。

# 任务
基于证据与大纲，撰写一篇有深度的 {{ content_style | default(template_type) }} 稿件，调性：{{ constraints.tone | default("objective") }}。
不仅转述证据，还要给出分析、判断与影响解读。

# 大纲（按此结构成文）
{% for sec in outline %}
## {{ sec.section }}
要点：{{ sec.points | join("、") }}
引用证据：{{ sec.evidence_ids | join(", ") }}
{% endfor %}

# 约束
- 字数 {{ constraints.min_words }}~{{ constraints.max_words }} 字（中文按字符计）；严禁凑字数，但必须写透
- 必须引用证据 ID，格式 [ev_xxx]；每个核心论断都要带引用
- 禁止编造未在证据中出现的事实；所有数字必须带证据引用
- 适配目标国家文化与表达习惯
- 输出 JSON

# 深度要求（重要）
1. 严格按大纲分节，每节 2-4 段；每段先陈述事实（带引用），再展开分析。
2. 分析维度至少覆盖：事件含义、对行业/用户的影响、潜在风险或争议、与其它趋势的关联。
3. 避免堆砌罗列；要有编辑视角的判断与解读，体现"为什么这件事重要"。
4. summary 风格可更紧凑，但仍需给出 1-2 句洞察；deep_dive 务必充分展开。

# 证据
{% for ev in evidences %}
[{{ ev.evidence_id }}] ({{ ev.source_name }}, {{ ev.published_at }}, 可信度{{ ev.credibility }})
{{ ev.content }}
{% endfor %}

# 选题
{{ topic.title }}
角度建议：{{ topic.suggested_angles | join("、") }}

# 输出 Schema
{"article":{"title":"","summary":"","body":[{"type":"paragraph","text":"","citations":["ev_xxx"]}],"tags":[""],"word_count":0,"language":"{{ constraints.country | default("zh") }}"}}""",
        "variables": ["topic", "evidences", "constraints", "template_type", "outline", "content_style", "country"],
    },
    "reviewer_check": {
        "agent": "reviewer", "scene": "check", "language": "zh",
        "template": """你是严格的内容审核编辑。审核以下稿件。

# 稿件
{{ article | tojson }}

# 证据
{{ evidences | tojson }}

# 审核要求
1. 事实核查：逐条校验引用是否与证据一致
2. 合规扫描：敏感词、政治红线
3. 质量打分(1-5)：可读性、客观性、完整性、时效性
4. 裁决：pass / revise / reject

# 输出 JSON
{"verdict":"pass","quality_scores":{"readability":4.0,"objectivity":4.0,"completeness":4.0,"timeliness":4.0,"overall":4.0},"fact_check":{"checked_claims":0,"consistent":0,"inconsistent":0,"details":[]},"compliance":{"sensitive_hits":[],"copyright_risk":"low","politics_risk":"none"},"revision_suggestions":[],"bad_case_flag":false}""",
        "variables": ["article", "evidences"],
    },
}


async def seed_default_prompts(session: AsyncSession):
    """初始化默认 Prompt 模板（如果不存在）"""
    pm = PromptManager()
    for pid, tpl in DEFAULT_TEMPLATES.items():
        existing = await session.execute(
            select(Prompt).where(and_(Prompt.prompt_id == pid, Prompt.language == tpl["language"]))
        )
        if existing.scalars().first():
            continue
        await pm.create(
            session,
            prompt_id=pid, agent=tpl["agent"], scene=tpl["scene"], language=tpl["language"],
            template=tpl["template"], variables=tpl["variables"],
            changelog="初始版本", author="system", version="v1.0.0", status="production",
        )
