"""
TrendForge Demo 主入口
======================
AI Native 全球热点内容生产系统 - 可运行 Demo

用法：
    python main.py              # 运行完整流水线
    python main.py --single     # 单话题端到端
    python main.py --ab         # A/B 实验演示
    python main.py --dashboard  # 生成数据看板数据

环境变量（可选，启用真实 LLM）：
    OPENAI_API_KEY=sk-xxx
    USE_REAL_LLM=true
    OPENAI_BASE_URL=https://api.openai.com/v1
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 让 `python main.py` 可直接运行（把 demo 目录加入 path）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CONFIG
from rag import NewsKnowledgeBase
from prompts import PromptManager
from agents import TaskContext
from workflow import WorkflowOrchestrator
from analytics import MetricsCollector


def configure_from_env():
    if os.getenv("USE_REAL_LLM", "").lower() == "true":
        CONFIG.use_real_llm = True
        CONFIG.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        CONFIG.openai_base_url = os.getenv("OPENAI_BASE_URL", CONFIG.openai_base_url)
        print(f"[config] 启用真实 LLM: {CONFIG.openai_base_url}")
    else:
        print("[config] 使用模拟 LLM 模式（无需 API key，可直接运行）")


async def demo_single_topic():
    """单话题端到端演示"""
    print("\n" + "=" * 70)
    print(" Demo 1: 单话题端到端内容生产")
    print("=" * 70)

    kb = NewsKnowledgeBase()
    print(f"\n[RAG] 知识库状态: {kb.stats()}")

    orchestrator = WorkflowOrchestrator(kb=kb)

    topic = {
        "topic_id": "topic_demo_gpt6",
        "title": "OpenAI 发布 GPT-6：10 万亿参数与多模态推理突破",
        "summary": "OpenAI 于今日发布 GPT-6，参数量较 GPT-5 提升 5 倍，新增原生多模态推理能力。",
        "category": "tech",
        "heat_score": 9.5,
        "suggested_angles": ["技术架构解析", "对行业格局的影响", "与竞品对比"],
        "target_languages": ["zh"],
        "priority": "P0",
    }

    print(f"\n[topic] {topic['title']}")
    result = await orchestrator.run_topic(topic)

    ctx = result["ctx"]
    print(f"\n[trace] trace_id={ctx.trace_id}")
    print(f"[trace] 状态: {ctx.status}")
    print(f"[trace] 总耗时: {ctx.total_duration_ms} ms")
    print(f"[trace] 总成本: ¥{ctx.total_cost_cny}")
    print(f"[trace] 审核轮次: {ctx.review_rounds}")
    print(f"[trace] Span 数: {len(ctx.spans)}")
    for s in ctx.spans:
        print(f"   - {s.agent:12s} | {s.status:8s} | {s.duration_ms:5d}ms | tokens={s.tokens_in}/{s.tokens_out} | ¥{s.cost_cny} | warnings={s.warnings}")

    if result.get("final"):
        final = result["final"]
        print(f"\n[final] {final.get('status')}")
        if final.get("content_id"):
            print(f"[final] content_id: {final['content_id']}")
            for r in final.get("publish_records", []):
                print(f"   - [{r['channel']}] {r['url']}")
            if final.get("gray_status"):
                gs = final["gray_status"]
                print(f"[gray] 当前比例: {gs['current_ratio']} | 观察 CTR: {gs['observed_ctr']} | 下一步: {gs['next_action']}")

    # 输出生产的内容
    for step in result["steps"]:
        if step["agent"] == "writer" and step.get("output", {}).get("article"):
            article = step["output"]["article"]
            print(f"\n[article] 标题: {article.get('title')}")
            print(f"[article] 摘要: {article.get('summary')}")
            print(f"[article] 字数: {article.get('word_count')}")
            print(f"[article] 标签: {article.get('tags')}")
            print(f"[article] 引用: {step['output'].get('citations')}")

    return result


async def demo_full_pipeline():
    """完整流水线演示（多话题并行）"""
    print("\n" + "=" * 70)
    print(" Demo 2: 完整流水线（热点发现 → 选题 → 生产 → 发布）")
    print("=" * 70)

    signals = [
        {
            "source": "weibo_hot",
            "items": [
                {"title": "OpenAI 发布 GPT-6", "heat": 9.8e6, "url": "https://..."},
                {"title": "美联储维持利率不变", "heat": 8.5e6, "url": "https://..."},
            ],
        },
        {
            "source": "twitter_trend",
            "items": [
                {"title": "GPT-6 multimodal", "heat": 2.1e6, "url": "https://..."},
            ],
        },
    ]
    strategy = {"categories": ["tech", "finance"], "languages": ["zh"], "max_topics": 3}

    orchestrator = WorkflowOrchestrator()
    print(f"\n[signals] 接入 {len(signals)} 个信号源, {sum(len(s['items']) for s in signals)} 条信号")
    result = await orchestrator.run_pipeline(signals=signals, strategy=strategy)

    print(f"\n[planner] 识别 {result['topics_count']} 个选题")
    for r in result["results"]:
        if "final" in r:
            print(f"  - [{r['final'].get('status')}] {r.get('topic', {}).get('title', '')[:40]}")
        elif "error" in r:
            print(f"  - [error] {r['error']}")

    print(f"\n[bad_cases] 共 {len(result['bad_cases'])} 个 Bad Case")
    return result


async def demo_ab_experiment():
    """A/B 实验演示"""
    print("\n" + "=" * 70)
    print(" Demo 3: Prompt A/B 实验 + 数据分析")
    print("=" * 70)

    pm = PromptManager()
    # 创建实验：writer deep_dive v1.0.0 vs v2.0.1
    exp = pm.create_experiment(
        exp_id="exp_writer_v2_vs_v1",
        agent="writer", scene="deep_dive",
        control="v1.0.0", treatment="v2.0.1",
        split={"control": 0.5, "treatment": 0.5},
    )
    print(f"\n[experiment] 创建实验 {exp['experiment_id']}")
    print(f"  control:   {exp['control']}")
    print(f"  treatment: {exp['treatment']}")

    # 模拟 20 篇内容分桶
    content_ids = [f"c_{uuid.uuid4().hex[:8]}" for _ in range(20)]
    for cid in content_ids:
        variant = pm.assign(exp["experiment_id"], cid)
        # 模拟发布元数据
        version = pm.get_variant_version(exp["experiment_id"], variant)

    print(f"\n[assignment] 分桶结果:")
    print(f"  control:   {len(exp['assignments']['control'])} 篇")
    print(f"  treatment: {len(exp['assignments']['treatment'])} 篇")

    # 数据分析
    mc = MetricsCollector()
    # 模拟发布数据
    import random
    for cid in content_ids:
        variant = pm.assign(exp["experiment_id"], cid)
        version = pm.get_variant_version(exp["experiment_id"], variant)
        # treatment 假设 CTR 更高
        mc.record_publish(cid, version, random.choice(["tech", "finance"]), datetime.now().isoformat())
    mc.simulate_events(content_ids, days=7)

    funnel = mc.funnel_analysis()
    print(f"\n[funnel] 漏斗分析（7日）:")
    print(f"  曝光: {funnel['impressions']:,}")
    print(f"  点击: {funnel['clicks']:,} (CTR={funnel['ctr']})")
    print(f"  阅读: {funnel['reads']:,} (阅读率={funnel['read_rate']})")
    print(f"  完读: {funnel['finishes']:,} (完读率={funnel['finish_rate']})")

    prompt_effect = mc.prompt_effect_analysis()
    print(f"\n[prompt_effect] Prompt 版本效果:")
    for p in prompt_effect:
        print(f"  {p['prompt_version']:12s} | imp={p['impressions']:6d} | ctr={p['ctr']} | read_rate={p['read_rate']} | finish_rate={p['finish_rate']}")

    ab = mc.ab_test_report(control="v1.0.0", treatment="v2.0.1")
    print(f"\n[ab_test] A/B 实验报告:")
    print(f"  control   {ab['control']['version']}: n={ab['control']['n']}, ctr={ab['control']['ctr']}")
    print(f"  treatment {ab['treatment']['version']}: n={ab['treatment']['n']}, ctr={ab['treatment']['ctr']}")
    print(f"  提升: {ab['lift_pct']}% | z={ab['z_score']} | p={ab['p_value']} | 显著={ab['significant']}")
    print(f"  结论: {ab['conclusion']}")

    if ab["significant"] and ab["treatment"]["ctr"] > ab["control"]["ctr"]:
        pm.conclude(exp["experiment_id"], winner="treatment", metrics=ab)
        print(f"\n[decision] treatment 胜出，v2.0.1 升版 production ✅")

    return ab


async def demo_bad_case():
    """Bad Case 闭环演示"""
    print("\n" + "=" * 70)
    print(" Demo 4: Bad Case 闭环")
    print("=" * 70)

    orchestrator = WorkflowOrchestrator()
    # 构造一个会触发 reject 的"标题党"话题
    topic = {
        "topic_id": "topic_badcase",
        "title": "震惊！某公司重大消息",
        "summary": "测试 Bad Case",
        "category": "tech",
        "suggested_angles": ["分析"],
        "target_languages": ["zh"],
        "priority": "P0",
    }
    result = await orchestrator.run_topic(topic)
    print(f"\n[bad_case] 触发 {len(orchestrator.bad_cases)} 个 Bad Case")
    for bc in orchestrator.bad_cases:
        print(f"  - id={bc['bad_case_id']}")
        print(f"    verdict={bc['verdict']}")
        print(f"    compliance={bc['compliance']}")
        print(f"    suggestions={bc['suggestions']}")
    return result


async def main():
    configure_from_env()

    await demo_single_topic()
    await demo_full_pipeline()
    await demo_ab_experiment()
    await demo_bad_case()

    print("\n" + "=" * 70)
    print(" 所有 Demo 运行完成 ✅")
    print("=" * 70)
    print("\n更多文档见 ../docs/")
    print("数据看板见 ../dashboard/index.html")
    print("架构图见 ../architecture/index.html")


if __name__ == "__main__":
    asyncio.run(main())
