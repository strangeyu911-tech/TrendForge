"""种子数据 — 初始化数据库 + 默认 Prompt + 真实新闻采集

用法：
    python seed.py              # 建库 + Prompt + 真实 RSS 采集 ~300 篇
    python seed.py --sample     # 仅写入旧示例数据（离线兜底，不联网）
"""
from __future__ import annotations
import asyncio
import sys
from datetime import datetime, timedelta
from db import init_db, async_session
from prompts import seed_default_prompts
from rag import ingest_news, collect_initial, get_vector_store


# ===== 离线兜底示例数据（网络不可用时用）=====
SAMPLE_NEWS = [
    {"source_name": "OpenAI Blog", "source_type": "official",
     "title": "OpenAI 发布 GPT-6：多模态推理与 10 万亿参数",
     "full_text": "OpenAI 于 2026 年 7 月 21 日正式发布 GPT-6。新模型参数量达到 10 万亿，较 GPT-5 提升约 5 倍。\n\n## 多模态推理\n\nGPT-6 引入原生多模态推理能力，可同时处理文本、图像、音频和视频输入。\n\n## 性能基准\n\nOpenAI CEO 表示，GPT-6 在 MMLU、GSM8K 等基准测试中均创下单项新高。模型将于下周通过 API 向开发者开放。",
     "url": "https://openai.com/blog/gpt6", "language": "en", "country": "US",
     "category": "tech", "credibility_level": 1, "entities": ["OpenAI", "GPT-6", "多模态"]},
    {"source_name": "Reuters", "source_type": "official_media",
     "title": "OpenAI launches GPT-6 with 10 trillion parameters",
     "full_text": "OpenAI launched GPT-6 on July 21, 2026, with 10 trillion parameters, a 5x increase over GPT-5.\n\nThe new model features native multimodal reasoning and achieves state-of-the-art results on MMLU and GSM8K benchmarks. CEO announced the API will be available to developers next week.",
     "url": "https://reuters.com/tech/openai-gpt6-launch", "language": "en", "country": "US",
     "category": "tech", "credibility_level": 1, "entities": ["OpenAI", "GPT-6"]},
    {"source_name": "Federal Reserve", "source_type": "official",
     "title": "美联储 7 月议息会议：维持利率不变",
     "full_text": "美联储 7 月议息会议结束，决定维持联邦基金利率目标区间在 5.25%-5.50% 不变。\n\n## 声明要点\n\n声明指出通胀仍高于目标，但点阵图显示年内可能降息一次。\n\n## 市场反应\n\n市场预期 9 月降息概率升至 70%。",
     "url": "https://federalreserve.gov/monetarypolicy/2026-07.htm", "language": "en", "country": "US",
     "category": "finance", "credibility_level": 1, "entities": ["美联储", "利率", "降息"]},
]


async def seed_sample():
    """离线兜底：仅写入示例数据"""
    print("[seed] 写入离线示例数据...")
    async with async_session() as session:
        now = datetime.utcnow()
        for i, news in enumerate(SAMPLE_NEWS):
            news["published_at"] = now - timedelta(hours=i * 2)
            news["source_id"] = f"{news['source_name']}_{i}"
            try:
                doc_id = await ingest_news(session, **news)
                if doc_id:
                    print(f"  ✓ {news['source_name']}: {news['title'][:30]}... → {doc_id}")
            except Exception as e:
                print(f"  ✗ {news['source_name']}: {e}")
        await session.commit()
    print(f"[seed] 离线示例完成。向量库 chunk 数: {get_vector_store().count}")


async def seed(use_real: bool = True):
    """初始化数据库 + 默认 Prompt +（可选）真实 RSS 采集"""
    print("[seed] 初始化数据库（含迁移）...")
    await init_db()
    async with async_session() as session:
        print("[seed] 写入默认 Prompt 模板...")
        await seed_default_prompts(session)
        await session.commit()

    if use_real:
        print("\n[seed] 启动真实 RSS 采集（首次初始化 ~300 篇）...")
        try:
            async with async_session() as session:
                stats = await collect_initial(session, target=300)
            print(f"\n[seed] 采集完成：新增 {stats['added']} 篇，跳过 {stats['skipped']}，失败 {stats['failed']}")
            print(f"[seed] 各源入库：{stats['by_source']}")
            if stats["added"] == 0:
                print("[seed] ⚠ 真实采集 0 篇（网络受限？），回退离线示例数据")
                await seed_sample()
        except Exception as e:
            print(f"[seed] ⚠ 真实采集异常：{e}，回退离线示例数据")
            await seed_sample()
    else:
        await seed_sample()

    print(f"\n[seed] 全部完成。向量库 chunk 数: {get_vector_store().count}")


if __name__ == "__main__":
    use_real = "--sample" not in sys.argv
    asyncio.run(seed(use_real=use_real))
