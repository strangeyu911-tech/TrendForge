"""TrendForge Demo 单元测试"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pytest  # noqa: F401  可选，仅在 pytest 环境下使用
except ImportError:
    pytest = None

from rag import NewsKnowledgeBase
from prompts import PromptManager
from agents import TaskContext, PlannerAgent, ResearchAgent, WriterAgent, ReviewerAgent, PublisherAgent
from workflow import WorkflowOrchestrator
from analytics import MetricsCollector


def test_rag_retrieve():
    kb = NewsKnowledgeBase()
    assert kb.total_docs > 0
    results = kb.retrieve(["GPT-6 发布 参数"], top_k=5)
    assert len(results) > 0
    assert results[0]["score"] > 0
    # GPT-6 相关文档应排在前面
    assert "GPT-6" in results[0]["content"] or "gpt-6" in results[0]["content"].lower()


def test_prompt_manager_versions():
    pm = PromptManager()
    versions = pm.get_versions("writer", "deep_dive")
    assert "v2.0.1" in versions
    latest = pm.get_latest("writer", "deep_dive")
    assert latest == "v2.0.1"


def test_prompt_render():
    pm = PromptManager()
    rendered = pm.render("writer", "deep_dive", "zh", "v2.0.1", {
        "topic": {"title": "测试话题", "suggested_angles": ["角度1"]},
        "evidences": [{"evidence_id": "ev_001", "source_name": "测试源", "published_at": "2026-07-21", "credibility": 0.9, "content": "测试内容"}],
        "constraints": {"min_words": 400, "max_words": 1200},
        "template_type": "deep_dive",
    })
    assert "测试话题" in rendered
    assert "ev_001" in rendered


def test_ab_assignment():
    pm = PromptManager()
    pm.create_experiment("exp1", "writer", "deep_dive", "v1.0.0", "v2.0.1")
    assignments = {"control": 0, "treatment": 0}
    for i in range(100):
        v = pm.assign("exp1", f"c_{i}")
        assignments[v] += 1
    # 50/50 分桶，允许 ±20% 误差
    assert 30 <= assignments["control"] <= 70
    assert 30 <= assignments["treatment"] <= 70


def test_planner_agent():
    async def run():
        ctx = TaskContext(task_id="t1", trace_id="tr1")
        agent = PlannerAgent()
        out = await agent.run(ctx, {"signals": [], "strategy": {"max_topics": 3}})
        assert "topics" in out
        assert len(out["topics"]) > 0  # 内置 demo 话题
    asyncio.run(run())


def test_research_agent():
    async def run():
        kb = NewsKnowledgeBase()
        ctx = TaskContext(task_id="t1", trace_id="tr1")
        agent = ResearchAgent(kb)
        out = await agent.run(ctx, {"topic": {"title": "GPT-6", "suggested_angles": ["技术"]}})
        assert "evidences" in out
        assert len(out["evidences"]) > 0
    asyncio.run(run())


def test_end_to_end():
    async def run():
        orch = WorkflowOrchestrator()
        topic = {
            "topic_id": "t1", "title": "GPT-6 发布",
            "summary": "测试", "category": "tech",
            "suggested_angles": ["技术"], "target_languages": ["zh"], "priority": "P0",
        }
        result = await orch.run_topic(topic)
        ctx = result["ctx"]
        assert ctx.status in ("succeeded", "human_pending", "aborted")
        assert len(ctx.spans) >= 3  # 至少 research + writer + reviewer
    asyncio.run(run())


def test_metrics():
    mc = MetricsCollector()
    cids = [f"c_{i}" for i in range(10)]
    for i, cid in enumerate(cids):
        mc.record_publish(cid, "v1.0.0" if i < 5 else "v2.0.1", "tech", "2026-07-21")
    mc.simulate_events(cids, days=3)
    funnel = mc.funnel_analysis()
    assert funnel["impressions"] > 0
    assert funnel["clicks"] > 0
    pe = mc.prompt_effect_analysis()
    assert len(pe) == 2  # 两个版本
    ab = mc.ab_test_report("v1.0.0", "v2.0.1")
    assert "conclusion" in ab


if __name__ == "__main__":
    # 不依赖 pytest 也能跑
    test_rag_retrieve(); print("✓ test_rag_retrieve")
    test_prompt_manager_versions(); print("✓ test_prompt_manager_versions")
    test_prompt_render(); print("✓ test_prompt_render")
    test_ab_assignment(); print("✓ test_ab_assignment")
    test_planner_agent(); print("✓ test_planner_agent")
    test_research_agent(); print("✓ test_research_agent")
    test_end_to_end(); print("✓ test_end_to_end")
    test_metrics(); print("✓ test_metrics")
    print("\n所有测试通过 ✅")
