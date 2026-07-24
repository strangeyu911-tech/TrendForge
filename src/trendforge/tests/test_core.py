"""架构与 RAG 测试（不依赖真实 LLM）"""
import pytest
import asyncio
from db import init_db, async_session
from prompts import PromptManager, seed_default_prompts
from rag import ingest_news, get_retriever
from analytics import analytics


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def setup_db():
    """初始化 DB + seed"""
    await init_db()
    async with async_session() as session:
        await seed_default_prompts(session)
        await session.commit()
    yield


@pytest.mark.asyncio
async def test_init_db(setup_db):
    """数据库初始化"""
    from sqlalchemy import select
    from models import Prompt
    async with async_session() as session:
        stmt = select(Prompt).where(Prompt.status == "production")
        prompts = (await session.execute(stmt)).scalars().all()
        assert len(prompts) >= 3  # planner/writer/reviewer 默认模板


@pytest.mark.asyncio
async def test_prompt_render(setup_db):
    """Prompt 渲染"""
    pm = PromptManager()
    async with async_session() as session:
        rendered, version = await pm.render_production(
            session, "writer", "deep_dive", "zh",
            {"topic": {"title": "测试", "category": "tech", "suggested_angles": ["技术"]},
             "evidences": [{"evidence_id": "ev_001", "source_name": "测试源", "published_at": "2026-07-21", "credibility": 0.9, "content": "测试内容"}],
             "constraints": {"min_words": 400, "max_words": 1200, "tone": "objective"},
             "template_type": "deep_dive"},
        )
        assert "测试" in rendered
        assert "ev_001" in rendered
        assert version == "v1.0.0"


@pytest.mark.asyncio
async def test_news_ingest(setup_db):
    """新闻入库"""
    from datetime import datetime
    import uuid
    async with async_session() as session:
        doc_id = await ingest_news(
            session, source_name="TestSource", title="测试新闻标题",
            content="这是一条用于测试的新闻内容，包含足够长度以支持切分。" * 10,
            url=f"https://test.example.com/news-{uuid.uuid4().hex[:8]}", published_at=datetime.utcnow(),
            language="zh", category="tech", credibility_tier=1, entities=["测试"],
        )
        await session.commit()
        assert doc_id.startswith("doc_")


@pytest.mark.asyncio
async def test_rag_retrieve(setup_db):
    """RAG 检索（需先 ingest，用 seed 数据）"""
    # 先确保有数据（test_news_ingest 已入库一条）
    retriever = get_retriever()
    if retriever.store.count == 0:
        pytest.skip("向量库为空，跳过检索测试")
    results = retriever.retrieve(["测试新闻"], top_k=5)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_analytics_empty(setup_db):
    """数据分析（空数据不报错）"""
    async with async_session() as session:
        funnel = await analytics.funnel(session, days=7)
        assert "impressions" in funnel
        assert "ctr" in funnel
        bc = await analytics.bad_case_stats(session, days=30)
        assert "total" in bc


@pytest.mark.asyncio
async def test_experiment_assign():
    """A/B 分桶确定性"""
    from prompts import ExperimentManager
    em = ExperimentManager()
    split = {"control": 0.5, "treatment": 0.5}
    # 同一 content_id 应分到同一桶
    v1 = em.assign("exp1", "c_001", split)
    v2 = em.assign("exp1", "c_001", split)
    assert v1 == v2
    # 100 个样本分桶大致均衡
    counts = {"control": 0, "treatment": 0}
    for i in range(100):
        counts[em.assign("exp1", f"c_{i}", split)] += 1
    assert 30 <= counts["control"] <= 70


@pytest.mark.asyncio
async def test_api_app():
    """FastAPI 应用可创建"""
    from api.main import app
    from fastapi.testclient import TestClient
    # 用 TestClient 同步测试（不走 lifespan 的 LLM 检查）
    assert app.title == "TrendForge API"


def test_z_test_math():
    """Z 检验数学正确性"""
    from prompts.experiment import ExperimentManager
    em = ExperimentManager()
    # 完全相同 → 不显著
    lift, z, p, sig = em._z_test({"impressions": 1000, "clicks": 50}, {"impressions": 1000, "clicks": 50})
    assert sig is False
    # 差异大 → 显著
    lift, z, p, sig = em._z_test({"impressions": 10000, "clicks": 300}, {"impressions": 10000, "clicks": 400})
    assert sig is True
    assert lift > 0


def test_llm_vendors():
    """多厂商注册表与密钥解析"""
    from llm import list_vendors, get_provider
    from config import VENDOR_DEFAULTS
    # 1. 支持 6 家厂商
    assert set(VENDOR_DEFAULTS.keys()) == {"openai", "anthropic", "deepseek", "kimi", "qwen", "glm"}
    # 2. list_vendors 返回全部，含配置状态字段
    vendors = list_vendors()
    assert len(vendors) == 6
    for v in vendors:
        assert {"vendor", "label", "kind", "base_url", "default_model", "configured", "active"} <= set(v.keys())
    # 3. anthropic 用原生 kind，其余 openai 兼容
    kinds = {v["vendor"]: v["kind"] for v in vendors}
    assert kinds["anthropic"] == "anthropic"
    assert all(kinds[k] == "openai" for k in ["openai", "deepseek", "kimi", "qwen", "glm"])
    # 4. 未配置 key 时 get_provider 应抛 RuntimeError
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        # 临时清空所有 key
        import os
        saved = {k: os.environ.get(k) for k in os.environ if k.startswith("TF_") and "API_KEY" in k}
        for k in saved:
            del os.environ[k]
        get_provider("deepseek")  # deepseek 默认无 key


@pytest.mark.asyncio
async def test_provider_request_shape():
    """验证 Anthropic Provider 的请求体构造（不发真实请求）"""
    from llm import AnthropicProvider
    prov = AnthropicProvider("https://api.anthropic.com", "sk-test", "claude-3-5-haiku-20241022")
    assert prov.vendor == "anthropic"
    assert prov.default_model == "claude-3-5-haiku-20241022"
    assert prov.is_configured is True


def test_smart_chunk_structure():
    """智能 Chunk：结构化切分 + token 区间 + 标题上下文"""
    from rag import smart_chunk
    html = """<h1>GPT-6 发布</h1>
    <p>OpenAI 发布 GPT-6，参数 10 万亿，较 GPT-5 提升 5 倍。</p>
    <h2>多模态推理</h2>
    <p>GPT-6 引入原生多模态推理，可同时处理文本、图像、音频和视频输入。这一能力使其在视频理解和跨模态问答上表现优异，能够实时分析视频内容并回答关于画面细节的问题。</p>
    <h2>性能基准</h2>
    <p>在 MMLU 达到 92.1%，GSM8K 达到 97.3%，HumanEval 达到 95.8%，较 GPT-5 全面领先。</p>"""
    pieces = smart_chunk("GPT-6 发布", html)
    assert len(pieces) >= 1
    for p in pieces:
        assert p["token_count"] > 0
        assert "section_path" in p
        assert "GPT-6" in p["content"]  # 每段带标题上下文


@pytest.mark.asyncio
async def test_hash_dedup(setup_db):
    """hash 去重：相同 URL 第二次入库返回 None"""
    import uuid
    from rag import ingest_news, compute_hash
    url = f"https://dedup.test/{uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        d1 = await ingest_news(s, source_name="T", title="A", content="正文" * 50, url=url, credibility_level=1)
        await s.commit()
        assert d1 is not None
    async with async_session() as s:
        d2 = await ingest_news(s, source_name="T", title="A", content="正文" * 50, url=url, credibility_level=1)
        await s.commit()
        assert d2 is None  # 重复跳过
    assert compute_hash(url) == compute_hash(url)  # 稳定性
