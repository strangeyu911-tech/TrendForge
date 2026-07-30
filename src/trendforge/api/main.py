"""FastAPI 应用 — REST API 服务"""
from __future__ import annotations
import hashlib
import json
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path

from db import init_db, get_db
from prompts import PromptManager, seed_default_prompts, ExperimentManager
from rag import ingest_news, get_retriever, get_vector_store, collect_initial, update, source_status, start_scheduler, stop_scheduler
from workflow import WorkflowOrchestrator
from analytics import analytics
from llm import list_vendors, test_vendor
from schemas import (
    RunTopicRequest, RunPipelineRequest, PromptCreateRequest,
    ExperimentCreateRequest, NewsIngestRequest,
)
from config import settings

# 流水线后台任务注册表（单进程内存态；Render 免费层为单实例，轮询请求由同一进程处理）
PIPELINE_JOBS: dict[str, dict] = {}
PIPELINE_TASKS: set = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建表 + 迁移 + seed 默认 Prompt + 启动每日采集调度
    await init_db()
    from db import async_session
    async with async_session() as session:
        await seed_default_prompts(session)
        await session.commit()
    start_scheduler()
    yield
    await stop_scheduler()


app = FastAPI(
    title="TrendForge API",
    description="AI Native 全球内容供给平台",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ============ 健康检查 ============
@app.get("/api/health")
async def health():
    vendors = list_vendors()
    return {
        "status": "ok", "app": settings.app_name,
        "active_vendor": settings.llm_vendor,
        "llm_configured": any(v["configured"] for v in vendors),
        "vendors_configured": [v["vendor"] for v in vendors if v["configured"]],
        "supported_vendors": [v["vendor"] for v in vendors],
    }


# ============ LLM 厂商管理 ============
@app.get("/api/llm/vendors")
async def llm_vendors():
    """列出全部支持的 LLM 厂商及配置状态（不暴露 key）"""
    return {"vendors": list_vendors(), "active": settings.llm_vendor}


@app.post("/api/llm/test")
async def llm_test(vendor: str = "", prompt: str = "请回复 ok"):
    """连通性测试：用小请求验证某厂商是否可用（vendor 留空测当前激活厂商）"""
    v = vendor or settings.llm_vendor
    return await test_vendor(v, prompt)


@app.get("/api/llm/test")
async def llm_test_get(vendor: str = "", prompt: str = "请回复 ok"):
    """连通性测试（GET 版，方便浏览器直接访问）"""
    v = vendor or settings.llm_vendor
    return await test_vendor(v, prompt)


# ============ 内容生产 ============
@app.post("/api/content/run-topic")
async def run_topic(req: RunTopicRequest, session: AsyncSession = Depends(get_db)):
    """单话题端到端生产"""
    topic = {
        "topic_id": f"topic_api_{req.title[:8]}",
        "title": req.title, "summary": req.summary, "category": req.category,
        "suggested_angles": req.angles or ["技术解析", "行业影响"],
        "target_languages": [req.language], "priority": req.priority,
        "language": req.language, "country": req.country,
    }
    orch = WorkflowOrchestrator()
    result = await orch.run_topic(session, topic)
    await session.commit()
    return result


@app.post("/api/content/run-pipeline")
async def run_pipeline(req: RunPipelineRequest, session: AsyncSession = Depends(get_db)):
    """完整流水线：信号 → 选题 → 生产。

    工程化加固（应对免费模型限流 + 刷新安全）：
    1) 结果缓存：相同请求签名命中缓存则秒开，不重复消耗 LLM 额度（Demo 可重复查看）；
    2) 后台任务 + 轮询：冷生成 / 强制重生成时立即返回 job_id，流水线在后台脱离请求运行，
       前端轮询状态——刷新页面或断连都不会中断生成、也不会丢失进度；
    3) 降级兜底：生成失败（如 429 限流）但有缓存时，返回缓存结果而非 500；
    4) 友好错误：无任何缓存可用时返回结构化错误（非 500），前端引导查看已生成内容。
    """
    strategy = {"categories": req.categories, "country": req.country, "max_topics": req.max_topics,
                 "variants_per_topic": max(1, int(req.variants_per_topic))}
    cache_key = _pipeline_cache_key(req)
    ttl_hours = int(os.getenv("TF_PIPELINE_CACHE_TTL_HOURS", "24"))

    # 命中未过期缓存 → 秒开（除非强制重新生成）
    if not req.force:
        cached = await _load_pipeline_cache(session, cache_key, ttl_hours)
        if cached is not None:
            cached["cached"] = True
            return cached

    # 冷生成 / 强制重生成：提交后台任务并立即返回 job_id（前端据此轮询，刷新安全）
    job_id = uuid.uuid4().hex
    task = asyncio.create_task(
        _run_pipeline_job(job_id, req.signals, strategy, cache_key, ttl_hours)
    )
    PIPELINE_TASKS.add(task)
    task.add_done_callback(PIPELINE_TASKS.discard)
    return {"job_id": job_id, "status": "running", "cached": False}


async def _run_pipeline_job(job_id: str, signals, strategy: dict, cache_key: str, ttl_hours: int):
    """后台执行流水线（脱离 HTTP 请求生命周期，刷新/断连不中断）。"""
    from db import async_session
    PIPELINE_JOBS[job_id] = {"status": "running", "cached": False}
    session = async_session()
    try:
        orch = WorkflowOrchestrator()
        result = await orch.run_pipeline(session, signals, strategy)
        await session.commit()
        await _save_pipeline_cache(session, cache_key, result)
        await session.commit()  # 同时落库 Content 与 pipeline_cache
        result["cached"] = False
        PIPELINE_JOBS[job_id] = {"status": "succeeded", "result": result, "cached": False}
    except Exception as e:
        # 生成失败：尝试降级返回缓存（即使略过期），保证 Demo 不 500
        try:
            fallback = await _load_pipeline_cache(session, cache_key, ttl_hours, allow_stale=True)
        except Exception:
            fallback = None
        if fallback is not None:
            fallback["cached"] = True
            fallback["served_from_cache_due_to_error"] = True
            fallback["error"] = str(e)
            PIPELINE_JOBS[job_id] = {"status": "succeeded", "result": fallback,
                                     "cached": True, "served_from_cache_due_to_error": True}
        else:
            PIPELINE_JOBS[job_id] = {"status": "failed", "ok": False, "error": str(e),
                "tip": "免费模型当前限流或生成失败，可稍后重试；或查看已生成内容 /contents 直接演示成品。"}
    finally:
        await session.close()


@app.get("/api/content/pipeline-job/{job_id}")
async def get_pipeline_job(job_id: str):
    """轮询流水线后台任务状态（refresh-safe）。"""
    job = PIPELINE_JOBS.get(job_id)
    if job is None:
        return {"status": "not_found"}
    return job


def _pipeline_cache_key(req: RunPipelineRequest) -> str:
    """归一化请求 → 签名。仅取确定性字段，使同参数重复点击命中同一缓存。"""
    payload = {
        "signals": [{"source": s.source,
                     "items": [i.title for i in s.items]} for s in req.signals],
        "max_topics": req.max_topics,
        "categories": sorted(req.categories),
        "variants_per_topic": req.variants_per_topic,
        "country": req.country,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _load_pipeline_cache(session, key: str, ttl_hours: int, allow_stale: bool = False):
    from models import PipelineCache
    row = await session.get(PipelineCache, key)
    if not row:
        return None
    if not allow_stale and (datetime.utcnow() - row.updated_at) > timedelta(hours=ttl_hours):
        return None
    try:
        return json.loads(row.result_json)
    except Exception:
        return None


async def _save_pipeline_cache(session, key: str, result: dict):
    from models import PipelineCache
    raw = json.dumps(result, ensure_ascii=False, default=str)
    row = await session.get(PipelineCache, key)
    if row:
        row.result_json = raw
        row.hits = (row.hits or 0) + 1
        row.updated_at = datetime.utcnow()
    else:
        session.add(PipelineCache(req_hash=key, result_json=raw, hits=1))
    await session.flush()


@app.get("/api/content/{content_id}")
async def get_content(content_id: str, session: AsyncSession = Depends(get_db)):
    from models import Content
    c = await session.get(Content, content_id)
    if not c:
        raise HTTPException(404, "内容不存在")
    return {
        "content_id": c.content_id, "title": c.title, "summary": c.summary,
        "body": c.body, "tags": c.tags, "category": c.category,
        "word_count": c.word_count, "prompt_writer_v": c.prompt_writer_v,
        "quality_overall": c.quality_overall, "fact_consistency": c.fact_consistency,
        "review_verdict": c.review_verdict, "is_bad_case": c.is_bad_case,
        "published_at": c.published_at.isoformat() if c.published_at else None,
    }


# ============ 任务查询 ============
@app.get("/api/tasks")
async def list_tasks(limit: int = Query(20, le=100), session: AsyncSession = Depends(get_db)):
    from models import Task
    stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [{
        "task_id": t.task_id, "trace_id": t.trace_id, "topic_title": t.topic_title,
        "status": t.status, "review_rounds": t.review_rounds,
        "total_duration_ms": t.total_duration_ms, "total_cost_cny": t.total_cost_cny,
        "created_at": t.created_at.isoformat(),
    } for t in rows]


@app.get("/api/tasks/{task_id}/trace")
async def get_trace(task_id: str, session: AsyncSession = Depends(get_db)):
    from models import Task, TaskSpan
    t = await session.get(Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    spans = (await session.execute(select(TaskSpan).where(TaskSpan.task_id == task_id))).scalars().all()
    return {
        "task_id": t.task_id, "trace_id": t.trace_id, "status": t.status,
        "total_duration_ms": t.total_duration_ms, "total_cost_cny": t.total_cost_cny,
        "spans": [{
            "agent": s.agent, "status": s.status, "model": s.model,
            "tokens_in": s.tokens_in, "tokens_out": s.tokens_out,
            "cost_cny": s.cost_cny, "duration_ms": s.duration_ms, "warnings": s.warnings,
        } for s in spans],
    }


# ============ RAG 知识库 ============
@app.post("/api/rag/ingest")
async def ingest(req: NewsIngestRequest, session: AsyncSession = Depends(get_db)):
    """入库新闻"""
    doc_id = await ingest_news(
        session, source_name=req.source_name, title=req.title, content=req.content,
        url=req.url, published_at=req.published_at, language=req.language,
        category=req.category, credibility_tier=req.credibility_tier, entities=req.entities,
    )
    await session.commit()
    return {"doc_id": doc_id, "status": "indexed"}


@app.get("/api/rag/search")
async def search(
    q: str = Query(...),
    top_k: int = Query(10, le=50),
    country: str | None = Query(None, description="国家，如 US/GB"),
    language: str | None = Query(None, description="语言，如 en/zh"),
    category: str | None = Query(None, description="分类 tech/finance/world"),
    credibility_level_max: int | None = Query(None, description="可信等级上限 1-3"),
    time_window_hours: int | None = Query(None, description="时间窗口（小时）"),
    session: AsyncSession = Depends(get_db),
):
    """语义检索知识库 — 支持国家/语言/分类/可信度/时间多维过滤"""
    retriever = get_retriever()
    filters = {}
    if country: filters["country"] = country
    if language: filters["language"] = language
    if category: filters["category"] = category
    if credibility_level_max: filters["credibility_level_max"] = credibility_level_max
    if time_window_hours: filters["time_window_hours"] = time_window_hours
    results = retriever.retrieve([q], top_k=top_k, filters=filters or None)
    return {"query": q, "filters": filters, "count": len(results), "results": [{
        "content": r["content"][:240], "title": r.get("title", ""),
        "source_name": r.get("source_name", ""), "source_url": r.get("source_url", ""),
        "score": round(r.get("final_score", 0), 4), "published_at": r.get("published_at", ""),
        "country": r.get("country", ""), "language": r.get("language", ""),
        "category": r.get("category", ""), "credibility_level": r.get("credibility_level", 0),
        "section_path": r.get("section_path", ""),
    } for r in results]}


@app.get("/api/rag/sources")
async def rag_sources():
    """列出已配置的可信新闻源"""
    return {"sources": await source_status(), "count": len(await source_status())}


@app.post("/api/rag/collect")
async def rag_collect(mode: str = Query("update", description="update=增量 / initial=首次~300篇"), session: AsyncSession = Depends(get_db)):
    """手动触发 RSS 采集"""
    if mode == "initial":
        stats = await collect_initial(session, target=settings.collector_initial_target)
    else:
        stats = await update(session)
    await session.commit()
    return stats


@app.get("/api/rag/stats")
async def rag_stats(session: AsyncSession = Depends(get_db)):
    """知识库统计：文档数 / chunk 数 / 按源·分类·国家分布"""
    from models import NewsDocument
    from sqlalchemy import func
    total_docs = (await session.execute(select(func.count(NewsDocument.doc_id)))).scalar() or 0
    by_source = {r[0]: r[1] for r in (await session.execute(select(NewsDocument.source_name, func.count()).group_by(NewsDocument.source_name))).all()}
    by_category = {r[0]: r[1] for r in (await session.execute(select(NewsDocument.category, func.count()).group_by(NewsDocument.category))).all()}
    by_country = {r[0]: r[1] for r in (await session.execute(select(NewsDocument.country, func.count()).group_by(NewsDocument.country))).all()}
    return {
        "total_documents": total_docs,
        "total_chunks": get_vector_store().count,
        "by_source": by_source,
        "by_category": by_category,
        "by_country": by_country,
    }


# ============ Prompt 管理 ============
@app.post("/api/prompts")
async def create_prompt(req: PromptCreateRequest, session: AsyncSession = Depends(get_db)):
    pm = PromptManager()
    p = await pm.create(
        session, prompt_id=req.prompt_id, agent=req.agent, scene=req.scene,
        language=req.language, template=req.template, variables=req.variables,
        changelog=req.changelog, parent_version=req.parent_version, author=req.author,
    )
    await session.commit()
    return {"prompt_id": p.prompt_id, "version": p.version, "status": p.status}


@app.get("/api/prompts/{prompt_id}")
async def list_prompts(prompt_id: str, language: str = "zh", session: AsyncSession = Depends(get_db)):
    pm = PromptManager()
    versions = await pm.list_versions(session, prompt_id, language)
    return [{"version": v.version, "status": v.status, "agent": v.agent, "scene": v.scene,
             "changelog": v.changelog, "created_at": v.created_at.isoformat(),
             "eval_score": v.eval_score} for v in versions]


@app.post("/api/prompts/{prompt_id}/{version}/promote")
async def promote_prompt(prompt_id: str, version: str, session: AsyncSession = Depends(get_db)):
    pm = PromptManager()
    p = await pm.promote(session, prompt_id, version)
    await session.commit()
    return {"prompt_id": p.prompt_id, "version": p.version, "status": p.status}


# ============ A/B 实验 ============
@app.post("/api/experiments")
async def create_experiment(req: ExperimentCreateRequest, session: AsyncSession = Depends(get_db)):
    em = ExperimentManager()
    exp = await em.create(
        session, experiment_id=req.experiment_id, agent=req.agent, scene=req.scene,
        control_version=req.control_version, treatment_version=req.treatment_version,
        traffic_split=req.traffic_split, target_metrics=req.target_metrics,
        min_sample_size=req.min_sample_size,
    )
    await session.commit()
    return {"experiment_id": exp.experiment_id, "status": exp.status}


@app.get("/api/experiments/{experiment_id}/report")
async def experiment_report(experiment_id: str, session: AsyncSession = Depends(get_db)):
    em = ExperimentManager()
    try:
        return await em.report(session, experiment_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/prompts")
async def list_all_prompts(session: AsyncSession = Depends(get_db)):
    """列出全部 Prompt（每个 prompt_id 取最新版本）"""
    from models import Prompt
    rows = (await session.execute(select(Prompt).order_by(Prompt.created_at.desc()))).scalars().all()
    seen = {}
    for p in rows:
        if p.prompt_id not in seen:
            seen[p.prompt_id] = p
    prompts = [{
        "prompt_id": p.prompt_id, "agent": p.agent, "scene": p.scene,
        "language": p.language, "status": p.status, "version": p.version,
        "eval_score": p.eval_score, "author": p.author, "tags": p.tags,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in seen.values()]
    return {"prompts": prompts, "count": len(prompts)}


@app.get("/api/experiments")
async def list_experiments(session: AsyncSession = Depends(get_db)):
    """列出全部 A/B 实验及其显著性报告"""
    from models import PromptExperiment
    from prompts import ExperimentManager
    rows = (await session.execute(
        select(PromptExperiment).order_by(PromptExperiment.start_at.desc())
    )).scalars().all()
    em = ExperimentManager()
    out = []
    for e in rows:
        try:
            report = await em.report(session, e.experiment_id)
        except Exception:
            report = None
        out.append({
            "experiment_id": e.experiment_id, "agent": e.agent, "scene": e.scene,
            "control_version": e.control_version, "treatment_version": e.treatment_version,
            "traffic_split": e.traffic_split, "status": e.status,
            "start_at": e.start_at.isoformat() if e.start_at else None,
            "report": report,
        })
    return {"experiments": out, "count": len(out)}


# ============ 数据分析 ============
@app.get("/api/analytics/funnel")
async def api_funnel(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.funnel(session, days)


@app.get("/api/analytics/ctr-by-category")
async def api_ctr_cat(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.ctr_by_category(session, days)


@app.get("/api/analytics/prompt-effect")
async def api_prompt_effect(days: int = Query(14), session: AsyncSession = Depends(get_db)):
    return await analytics.prompt_effect(session, days)


@app.get("/api/analytics/bad-cases")
async def api_bad_cases(days: int = Query(30), session: AsyncSession = Depends(get_db)):
    return await analytics.bad_case_stats(session, days)


@app.get("/api/bad-cases")
async def list_bad_cases(days: int = Query(90), session: AsyncSession = Depends(get_db)):
    """逐条 Bad Case 列表（关联内容标题）"""
    from datetime import datetime, timedelta
    from models import BadCase, Content
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await session.execute(
        select(BadCase).where(BadCase.created_at >= since).order_by(BadCase.created_at.desc())
    )).scalars().all()
    cids = [r.content_id for r in rows if r.content_id]
    titles = {}
    if cids:
        for c in (await session.execute(
            select(Content).where(Content.content_id.in_(cids))
        )).scalars().all():
            titles[c.content_id] = c.title
    return [{
        "id": b.bad_case_id, "content_id": b.content_id,
        "content": titles.get(b.content_id, b.content_id),
        "l1": b.category_l1, "l2": b.category_l2, "severity": b.severity,
        "status": b.status, "source": b.source, "reason": b.description,
        "assignee": b.assigned_to,
        "created": b.created_at.isoformat() if b.created_at else None,
    } for b in rows]


@app.get("/api/analytics/production")
async def api_production(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.production_stats(session, days)


@app.get("/api/analytics/cost")
async def api_cost(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.cost_stats(session, days)


@app.get("/api/analytics/cost-trend")
async def api_cost_trend(days: int = Query(12), session: AsyncSession = Depends(get_db)):
    """成本与效率时间序列（按天聚合，跨数据库方言安全）"""
    from datetime import datetime, timedelta
    from models import Task, Content
    since = datetime.utcnow() - timedelta(days=days)
    tasks = (await session.execute(
        select(Task).where(Task.created_at >= since, Task.status == "succeeded")
    )).scalars().all()
    buckets = {}
    for t in tasks:
        if not t.created_at:
            continue
        d = t.created_at.date().isoformat()
        buckets.setdefault(d, []).append(t)
    labels = sorted(buckets.keys())
    cost = [round(sum(x.total_cost_cny for x in buckets[d]) / len(buckets[d]), 4) for d in labels]
    contents = (await session.execute(
        select(Content).where(Content.published_at >= since)
    )).scalars().all()
    eff_map = {}
    for c in contents:
        if c.published_at:
            k = c.published_at.date().isoformat()
            eff_map[k] = eff_map.get(k, 0) + 1
    eff = [eff_map.get(d, 0) for d in labels]
    return {"labels": labels, "cost": cost, "eff": eff}


# ============ 内容中心（平台化）============
@app.get("/api/contents")
async def api_contents(country: str | None = None, platform: str | None = None,
                       limit: int = Query(50, le=200), session: AsyncSession = Depends(get_db)):
    from models import Content
    from sqlalchemy import select
    stmt = select(Content).where(Content.published_at.isnot(None))
    if country:
        stmt = stmt.where(Content.country == country)
    if platform:
        stmt = stmt.where(Content.platform == platform)
    stmt = stmt.order_by(Content.published_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [{"content_id": c.content_id, "title": c.title, "country": c.country,
             "language": c.language, "platform": c.platform, "content_style": c.content_style,
             "quality_overall": c.quality_overall,
             "published_at": c.published_at.isoformat() if c.published_at else None,
             "is_bad_case": c.is_bad_case} for c in rows]


@app.get("/api/contents/{content_id}/trace")
async def api_content_trace(content_id: str, session: AsyncSession = Depends(get_db)):
    """查看单篇内容的全流程决策日志与 span（可解释性）"""
    from models import Content, Task, TaskSpan
    from sqlalchemy import select
    c = await session.get(Content, content_id)
    if not c:
        raise HTTPException(404, "内容不存在")
    task = await session.get(Task, c.task_id)
    spans = (await session.execute(
        select(TaskSpan).where(TaskSpan.task_id == c.task_id).order_by(TaskSpan.id))).scalars().all()
    return {"content_id": content_id, "title": c.title, "country": c.country,
            "decision_log": c.decision_log or {}, "task_status": task.status if task else None,
            "spans": [{"agent": s.agent, "status": s.status, "model": s.model,
                       "tokens": s.tokens_in + s.tokens_out, "cost_cny": s.cost_cny,
                       "duration_ms": s.duration_ms, "warnings": s.warnings} for s in spans]}


@app.post("/api/events/simulate")
async def api_simulate(per_content: int = 50, session: AsyncSession = Depends(get_db)):
    """模拟用户行为事件（数据反馈闭环演示）"""
    from simulator import simulator
    r = await simulator.simulate(session, per_content=per_content)
    await session.commit()
    return r


# ============ 全球化效果分析 ============
@app.get("/api/analytics/by-country")
async def api_by_country(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.performance_by_country(session, days)


@app.get("/api/analytics/by-language")
async def api_by_language(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.performance_by_language(session, days)


@app.get("/api/analytics/by-platform")
async def api_by_platform(days: int = Query(7), session: AsyncSession = Depends(get_db)):
    return await analytics.performance_by_platform(session, days)


@app.get("/api/analytics/prompt-roi")
async def api_prompt_roi(days: int = Query(14), session: AsyncSession = Depends(get_db)):
    return await analytics.prompt_roi(session, days)


# ============ Demo 精简接口（4 个核心 API，给前端 Demo 用）============
@app.post("/search")
async def demo_search(req: dict, session: AsyncSession = Depends(get_db)):
    """① RAG 检索：输入关键词，返回相关新闻证据"""
    from rag import get_retriever
    query = req.get("query", "")
    if not query:
        raise HTTPException(400, "query 必填")
    filters = {}
    for k in ("country", "category", "language"):
        if req.get(k):
            filters[k] = req[k]
    filters.setdefault("credibility_level_max", 2)
    retriever = get_retriever()
    chunks = retriever.retrieve([query], top_k=req.get("top_k", 8), filters=filters)
    return {"query": query, "count": len(chunks),
            "evidences": [{"title": c.get("title", ""), "source": c.get("source_name", ""),
                           "country": c.get("country", ""), "published_at": c.get("published_at", ""),
                           "content": c.get("content", "")[:300],
                           "score": round(c.get("final_score", c.get("score", 0)), 4)} for c in chunks]}


async def _run_demo_workflow(req: dict, session: AsyncSession) -> dict:
    """共用：跑一遍 8 步 workflow"""
    from workflow.orchestrator import WorkflowOrchestrator
    from config import COUNTRY_STRATEGIES
    topic = req.get("topic", "")
    if not topic:
        raise HTTPException(400, "topic 必填")
    country = req.get("country", "US")
    strat = COUNTRY_STRATEGIES.get(country, COUNTRY_STRATEGIES["US"])
    t = {"topic_id": f"demo_{abs(hash(topic)) % 100000}", "title": topic, "summary": "",
         "category": req.get("category", "tech"), "country": country,
         "language": req.get("language", strat["language"]),
         "target_audience": strat["target_audience"],
         "content_style": req.get("content_style", strat["default_style"]),
         "suggested_angles": req.get("angles", []), "priority": "P1"}
    r = await WorkflowOrchestrator().run_topic(session, t)
    await session.commit()
    return r


@app.post("/generate")
async def demo_generate(req: dict, session: AsyncSession = Depends(get_db)):
    """② 实时生成：8步Workflow → 返回内容 + 决策日志"""
    r = await _run_demo_workflow(req, session)
    final = r.get("final", {})
    steps = [{"agent": s["agent"], "decision": (s.get("output", {}).get("_decision") or {}).get("reason", "")}
             for s in r.get("steps", [])]
    return {"status": r.get("status"), "content_id": final.get("content_id"),
            "country": req.get("country", "US"),
            "platform": (final.get("distribution_plan") or {}).get("primary_platform"),
            "steps": steps, "error": r.get("error")}


@app.post("/workflow")
async def demo_workflow(req: dict, session: AsyncSession = Depends(get_db)):
    """③ Workflow 日志：返回整个 Agent 协作过程与决策"""
    r = await _run_demo_workflow(req, session)
    steps = [{"agent": s["agent"], "round": s.get("round"),
              "decision": (s.get("output", {}).get("_decision") or {}).get("reason", ""),
              "details": (s.get("output", {}).get("_decision") or {}).get("details", {})}
             for s in r.get("steps", [])]
    return {"status": r.get("status"), "trace_id": r.get("trace_id"),
            "total_steps": len(steps), "steps": steps, "error": r.get("error")}


@app.get("/stats")
async def demo_stats(session: AsyncSession = Depends(get_db)):
    """④ 数据库统计：news/chunk/prompt/content/bad_case 数量"""
    from models import NewsDocument, NewsChunk, Content, ContentEvent, BadCase, Prompt, Task
    from sqlalchemy import select, func
    out = {}
    for cls, k in [(NewsDocument, "news_documents"), (NewsChunk, "news_chunks"),
                   (Prompt, "prompts"), (Content, "contents"), (ContentEvent, "content_events"),
                   (BadCase, "bad_cases"), (Task, "tasks")]:
        out[k] = (await session.execute(select(func.count()).select_from(cls))).scalar()
    try:
        from rag import get_vector_store
        out["vector_store"] = get_vector_store().count
    except Exception:
        out["vector_store"] = None
    return out


# ============ 根路径：API 文档引导 ============
@app.get("/", response_class=HTMLResponse)
async def root():
    return """<html><head><meta charset='utf-8'><title>TrendForge API</title>
    <style>body{font-family:system-ui;max-width:760px;margin:60px auto;padding:0 24px;color:#1f2937}
    h1{color:#6366f1}a{color:#6366f1}.card{background:#f7f8fc;padding:16px;border-radius:12px;margin:12px 0}
    code{background:#eef2ff;padding:2px 6px;border-radius:4px}.tag{display:inline-block;background:#ddd6fe;color:#5b21b6;padding:2px 8px;border-radius:999px;font-size:12px;margin:2px}</style></head>
    <body><h1>⚡ TrendForge API</h1><p>AI Native 全球内容供给平台</p>
    <div class='card'>📖 交互式文档：<a href='/docs'>/docs</a>（Swagger UI）</div>
    <div class='card'>🔍 健康检查：<a href='/api/health'>/api/health</a></div>
    <div class='card'>🤖 LLM 厂商：<a href='/api/llm/vendors'>/api/llm/vendors</a> · 测试：<a href='/api/llm/test'>/api/llm/test</a></div>
    <div class='card'>主要接口：<code>POST /api/content/run-topic</code> · <code>POST /api/rag/ingest</code> · <code>GET /api/analytics/funnel</code></div>
    <div class='card'>支持厂商：
    <span class='tag'>OpenAI</span><span class='tag'>Anthropic</span><span class='tag'>DeepSeek</span>
    <span class='tag'>Kimi</span><span class='tag'>Qwen</span><span class='tag'>GLM</span></div>
    <p style='color:#6b7280;margin-top:40px'>配置 LLM：在 .env 设置 <code>TF_LLM_VENDOR</code> 与对应 <code>TF_&lt;VENDOR&gt;_API_KEY</code></p>
    </body></html>"""
