"""TrendForge 启动入口

用法：
    python main.py seed      # 初始化数据库 + 默认 Prompt + 真实 RSS 采集 ~300 篇
    python main.py collect   # 增量采集（拉各源最新，hash 去重）
    python main.py serve     # 启动 API 服务（含每日定时采集）
    python main.py test      # 运行测试
    python main.py           # seed + serve
"""
from __future__ import annotations
import sys
import asyncio


def run_seed():
    from seed import seed
    asyncio.run(seed(use_real="--sample" not in sys.argv))


def run_collect():
    """增量采集最新新闻"""
    from db import async_session, init_db
    from rag import update, get_vector_store

    async def _go():
        await init_db()
        async with async_session() as session:
            stats = await update(session)
        print(f"\n采集完成：新增 {stats['added']} 篇，跳过 {stats['skipped']}，失败 {stats['failed']}")
        print(f"各源：{stats['by_source']}")
        print(f"向量库 chunk 总数：{get_vector_store().count}")

    asyncio.run(_go())


def run_serve():
    import uvicorn
    from config import settings
    print(f"\n⚡ TrendForge API 启动中...")
    print(f"   地址: http://{settings.host}:{settings.port}")
    print(f"   文档: http://{settings.host}:{settings.port}/docs")
    print(f"   LLM: {'已配置' if settings.llm_api_key else '未配置（需设 TF_LLM_API_KEY 才能调真实模型）'}")
    print(f"   数据库: {settings.database_url}")
    print(f"   每日定时采集: {settings.collector_daily_hour:02d}:00")
    print()
    uvicorn.run("api.main:app", host=settings.host, port=settings.port, reload=settings.debug)


def run_test():
    sys.exit(asyncio.run(_run_pytest()))


async def _run_pytest():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"], cwd=".")
    return r.returncode


def run_simulate():
    """模拟用户行为事件（数据反馈闭环）"""
    from db import async_session, init_db
    from simulator import simulator

    async def _go():
        await init_db()
        async with async_session() as session:
            r = await simulator.simulate(session, per_content=50)
            await session.commit()
        print(f"\n模拟完成：覆盖 {r['contents']} 篇内容，生成 {r['events_generated']} 条事件")
        print(f"Prompt 效果回流：{r['prompt_backfill']}")

    asyncio.run(_go())


def run_topic():
    """端到端跑一篇内容（8 步 Workflow）"""
    from db import async_session, init_db
    from workflow.orchestrator import WorkflowOrchestrator
    from config import COUNTRY_STRATEGIES

    async def _go():
        await init_db()
        country = "CN"
        strat = COUNTRY_STRATEGIES[country]
        topic = {
            "topic_id": "topic_demo", "title": "AI 模型能力快速演进对内容生产的影响",
            "summary": "demo", "category": "tech", "country": country, "language": strat["language"],
            "target_audience": strat["target_audience"], "content_style": strat["default_style"],
            "suggested_angles": ["技术趋势", "行业影响"], "priority": "P1",
        }
        async with async_session() as session:
            r = await WorkflowOrchestrator().run_topic(session, topic)
            await session.commit()
        print(f"\n任务状态: {r.get('status')}, task_id={r.get('task_id')}")
        if r.get("final"):
            f = r["final"]
            print(f"content_id: {f.get('content_id')}")
            print(f"分发计划: {f.get('distribution_plan', {}).get('channels')}")
        print(f"决策日志: {list(r.get('steps', []) and [])}")
        for s in r.get("steps", []):
            dec = s.get("output", {}).get("_decision") or "(无)"
            print(f"  [{s['agent']}] {dec}")

    asyncio.run(_go())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "seed":
        run_seed()
    elif cmd == "collect":
        run_collect()
    elif cmd == "simulate":
        run_simulate()
    elif cmd == "run":
        run_topic()
    elif cmd == "serve":
        run_serve()
    elif cmd == "test":
        run_test()
    else:
        run_seed()
        run_serve()
