"""本地复现 run-pipeline 以定位 500 根因（使用 venv + GLM key，跑真实链路）。"""
import asyncio, sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "trendforge"))
os.chdir(os.path.join(os.path.dirname(__file__), "src", "trendforge"))
from db import async_session, init_db
from workflow.orchestrator import WorkflowOrchestrator

async def main():
    await init_db()
    async with async_session() as session:
        orch = WorkflowOrchestrator()
        try:
            res = await orch.run_pipeline(session, [], {"country": "CN", "max_topics": 1, "variants_per_topic": 2, "categories": ["tech"]})
            print("OK result keys:", list(res.keys()))
            print("dedup:", res.get("dedup"))
            print("results:", len(res.get("results", [])))
        except Exception:
            traceback.print_exc()
        finally:
            await session.commit()

if __name__ == "__main__":
    asyncio.run(main())
