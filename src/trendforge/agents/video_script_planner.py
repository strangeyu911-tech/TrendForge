"""VideoScriptPlanner Agent — 把已生成的图文内容适配为多平台短视频脚本。

这是「多元内容形态」能力（图文 → 短视频 / 混剪脚本），是 JD 明确要求的形态之一。
设计取舍：不进 8 步主链路（主链路拓扑固定为有意设计），而是作为内容库的「衍生形态生成器」
独立服务——一篇已发布图文，可一键派生出抖音 / TikTok / Reuters Shorts 等多平台短视频脚本，
正对应岗位描述里「结合消费场景设计图文、短视频、混剪、摘要等多元内容形态」。

复用项目既有能力：
- PromptManager.render_production（Prompt 版本化 + 效果回流体系）
- get_llm（多厂商抽象 + 免费模型限流退避 / 同厂商兜底）
- 规则兜底（LLM 不可用时仍产出可用脚本，保证控制台永远可演示）

脚本以结构化 JSON 落库（video_scripts 表，content_id+platform 唯一），命中即秒开、不重复耗额度。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from config import settings, VIDEO_PLATFORMS, COUNTRY_STRATEGIES
from llm import get_llm, extract_json
from models import VideoScript
from prompts import PromptManager


def _video_model() -> str:
    """选模型：video_model → writer_model → 厂商默认"""
    return settings.video_model or settings.writer_model or settings.llm_model or ""


def _platform_preset(platform: str) -> dict:
    return dict(VIDEO_PLATFORMS.get(platform) or VIDEO_PLATFORMS["douyin"])


def _country_note(country: str) -> str:
    s = COUNTRY_STRATEGIES.get(country)
    if not s:
        return "未指定国家策略"
    return (
        f"国家={country}；受众={s.get('target_audience')}；调性={s.get('tone')}；"
        f"默认风格={s.get('default_style')}；语言={s.get('language')}"
    )


def _assemble_body_text(body: list[dict]) -> str:
    """把 Content.body（[{type,text}]）压成纯文本，供 LLM 读取要点"""
    if not body:
        return ""
    lines = []
    for b in body:
        if not isinstance(b, dict):
            continue
        t = b.get("text") or b.get("title") or ""
        if b.get("type") == "heading":
            t = "## " + t
        if t:
            lines.append(t)
    return "\n".join(lines)


def _build_script(raw: str, platform: str, preset: dict, language: str, title: str) -> dict:
    """解析 LLM 输出为结构化脚本，缺失字段用预设补齐"""
    try:
        data = extract_json(raw)
        if isinstance(data, dict) and ("scenes" in data or "hook" in data):
            data = data
        elif isinstance(data, list) and data:
            data = data[0]
        else:
            data = {}
    except Exception:
        data = {}
    scenes = data.get("scenes") or []
    if not isinstance(scenes, list):
        scenes = []
    # 补全 scene 字段
    norm_scenes = []
    for i, sc in enumerate(scenes, 1):
        if not isinstance(sc, dict):
            continue
        norm_scenes.append({
            "idx": sc.get("idx") or i,
            "visual": sc.get("visual") or "",
            "narration": sc.get("narration") or sc.get("text") or "",
            "caption": sc.get("caption") or "",
            "duration_sec": int(sc.get("duration_sec") or 8),
            "bgm": sc.get("bgm") or "",
        })
    hook = data.get("hook") or {}
    if not isinstance(hook, dict):
        hook = {}
    return {
        "title": (data.get("title") or title)[:40],
        "platform": platform,
        "platform_label": data.get("platform_label") or preset.get("label") or platform,
        "duration_sec": int(data.get("duration_sec") or preset.get("duration", 45)),
        "aspect": data.get("aspect") or preset.get("aspect", "9:16"),
        "tone": data.get("tone") or preset.get("tone", ""),
        "hook": {
            "text": hook.get("text") or (data.get("hook_text") or ""),
            "type": hook.get("type") or "question",
        },
        "cover_text": data.get("cover_text") or "",
        "scenes": norm_scenes,
        "cta": data.get("cta") or "关注看懂 AI 内容供给引擎",
        "hashtags": data.get("hashtags") or [],
        "estimated_retention": float(data.get("estimated_retention") or 0.6),
        "notes": data.get("notes") or "",
    }


def _rule_fallback(title: str, summary: str, body_text: str, platform: str, preset: dict, language: str) -> dict:
    """LLM 不可用（如免费模型限流）时的规则兜底脚本，保证控制台永远可演示"""
    first_line = (body_text or summary or title).strip().split("\n")[0][:80]
    return {
        "title": (title or "热点速览")[:40],
        "platform": platform,
        "platform_label": preset.get("label") or platform,
        "duration_sec": preset.get("duration", 45),
        "aspect": preset.get("aspect", "9:16"),
        "tone": preset.get("tone", ""),
        "hook": {"text": f"（{preset.get('label', '短视频')}）{title or '今天这条热点'}，背后藏着什么？", "type": "question"},
        "cover_text": (title or "热点")[:12],
        "scenes": [
            {"idx": 1, "visual": "主持人/新闻画面开场，抛冲突", "narration": (title or "今日热点") + "，先别划走。",
             "caption": (title or "今日热点")[:20], "duration_sec": 8, "bgm": "轻快节奏"},
            {"idx": 2, "visual": "关键数据/画面切入", "narration": first_line or "核心事实如下。",
             "caption": (first_line or "核心事实")[:24], "duration_sec": 12, "bgm": "紧张鼓点"},
            {"idx": 3, "visual": "结尾总结 + CTA 画面", "narration": "关注我，看清 AI 内容供给的下一站。",
             "caption": "关注看后续", "duration_sec": 10, "bgm": "收尾音效"},
        ],
        "cta": "关注看后续 · 评论区聊聊你的看法",
        "hashtags": ["#AI", "#热点", f"#{platform}"],
        "estimated_retention": 0.55,
        "notes": "规则兜底脚本（LLM 暂不可用），建议模型恢复后重新生成以获得贴合平台的改编。",
    }


async def generate_video_script(
    session: Any,
    *,
    content_id: str,
    title: str,
    summary: str,
    body: list[dict],
    tags: list,
    country: str,
    language: str,
    platform: str,
    force: bool = False,
) -> dict:
    """生成（或命中缓存）某内容的某平台短视频脚本。

    返回结构含脚本字段 + cached / is_fallback / prompt_version / warnings，便于前端区分展示。
    """
    preset = _platform_preset(platform)
    # 1) 命中已生成缓存（同内容+平台，除非强制重生成）
    existing = (await session.execute(
        select(VideoScript).where(
            VideoScript.content_id == content_id, VideoScript.platform == platform
        )
    )).scalars().first()
    if existing and not force:
        s = dict(existing.script_json or {})
        s.update({"cached": True, "is_fallback": existing.is_fallback,
                  "prompt_version": existing.prompt_version, "platform": platform})
        return s

    body_text = _assemble_body_text(body)
    pm = PromptManager()
    warnings = []
    try:
        rendered, version = await pm.render_production(
            session, "video_script_planner", "video_script", language,
            {
                "title": title, "summary": summary or "", "body_text": body_text[:4000],
                "tags": tags or [], "platform": platform,
                "platform_preset": json.dumps(preset, ensure_ascii=False),
                "country_note": _country_note(country), "language": language,
            },
        )
        llm = get_llm(settings.llm_vendor)
        resp = await llm.chat(rendered, model=_video_model(), json_mode=True, temperature=0.8, max_tokens=1500)
        script = _build_script(resp.text, platform, preset, language, title)
        prompt_version = version
        is_fallback = False
    except Exception as e:  # 限流 / 任何 LLM 异常 → 规则兜底，绝不裸失败
        script = _rule_fallback(title, summary, body_text, platform, preset, language)
        prompt_version = "rule-based"
        is_fallback = True
        warnings.append(f"fallback:{type(e).__name__}:{e}")

    # 2) 落库（upsert content_id+platform）
    row = existing or VideoScript(content_id=content_id, platform=platform)
    row.language = language
    row.country = country
    row.script_json = script
    row.prompt_version = prompt_version
    row.is_fallback = is_fallback
    session.add(row)
    await session.flush()
    return {
        **script,
        "cached": False,
        "is_fallback": is_fallback,
        "prompt_version": prompt_version,
        "warnings": warnings or None,
        "platform": platform,
    }


async def list_video_scripts(session: Any, content_id: str, platform: str = "") -> list[dict]:
    """列出某内容已生成的脚本（按平台）"""
    stmt = select(VideoScript).where(VideoScript.content_id == content_id)
    if platform:
        stmt = stmt.where(VideoScript.platform == platform)
    stmt = stmt.order_by(VideoScript.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [{
        "platform": r.platform, "script": r.script_json,
        "is_fallback": r.is_fallback, "prompt_version": r.prompt_version,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]
