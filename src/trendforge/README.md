# TrendForge — 生产级实现

> AI Native 全球热点内容生产系统的**真实可运行实现**（非模拟版）。基于设计文档落地，技术栈：FastAPI + SQLAlchemy + ChromaDB + OpenAI 兼容 LLM。

## 与 demo/ 的区别

| 维度 | demo/（模拟版） | src/trendforge/（生产实现） |
|------|----------------|--------------------------|
| LLM | 模拟器 | 真实 OpenAI 兼容调用（GPT/通义/Moonshot/DeepSeek） |
| 向量库 | TF-IDF 内存 | ChromaDB 持久化 |
| 数据库 | 内存 | SQLite（可切 PostgreSQL） |
| Prompt | JSON 文件 | DB 版本管理 + 生命周期 |
| API | 无 | FastAPI REST + Swagger 文档 |
| 持久化 | 无 | 全链路 DB 持久化 + Trace |

## 快速开始

### 1. 安装依赖

```bash
cd src/trendforge
python -m venv .venv && .venv/Scripts/activate   # Windows
# 或 source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. 配置 LLM（必填，才能调真实模型）

```bash
cp .env.example .env
# 编辑 .env，填入 TF_LLM_API_KEY
```

支持 OpenAI / 通义千问 / Moonshot / DeepSeek，配置方式见 `.env.example`。

> 不配 LLM 也能跑 RAG / 数据分析 / Prompt 管理 / API 文档，仅内容生产接口需 LLM。

### 3. 初始化数据

```bash
python main.py seed      # 建表 + 默认 Prompt + 8 篇示例新闻入库
```

### 4. 启动服务

```bash
python main.py serve
# API: http://localhost:8000
# Swagger 文档: http://localhost:8000/docs
```

### 5. 运行测试

```bash
python main.py test      # 8 项测试（不依赖 LLM）
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/content/run-topic` | 单话题端到端生产（需 LLM） |
| POST | `/api/content/run-pipeline` | 完整流水线（需 LLM） |
| GET | `/api/content/{id}` | 查看生产的内容 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}/trace` | 任务全链路 Trace |
| POST | `/api/rag/ingest` | 新闻入库 |
| GET | `/api/rag/search?q=` | 知识库检索 |
| GET | `/api/rag/stats` | 知识库统计 |
| POST | `/api/prompts` | 创建 Prompt 版本 |
| GET | `/api/prompts/{id}` | Prompt 版本列表 |
| POST | `/api/prompts/{id}/{ver}/promote` | 升版为 production |
| POST | `/api/experiments` | 创建 A/B 实验 |
| GET | `/api/experiments/{id}/report` | A/B 实验报告（含 Z 检验） |
| GET | `/api/analytics/funnel` | 漏斗分析 |
| GET | `/api/analytics/ctr-by-category` | 分品类 CTR |
| GET | `/api/analytics/prompt-effect` | Prompt 版本效果 |
| GET | `/api/analytics/bad-cases` | Bad Case 统计 |
| GET | `/api/analytics/production` | 生产效率 |
| GET | `/api/analytics/cost` | 成本统计 |

## 项目结构

```
src/trendforge/
├── config.py              # 配置（环境变量）
├── db.py                  # 异步数据库引擎
├── models.py              # SQLAlchemy 模型（10 张表）
├── schemas.py             # Pydantic 数据契约
├── llm.py                 # LLM Provider（OpenAI 兼容，真实调用）
├── seed.py                # 种子数据初始化
├── main.py                # 启动入口（seed/serve/test）
├── rag/                   # RAG 知识库
│   ├── vectorstore.py     #   Chroma 向量库
│   ├── embeddings.py      #   Embedding 服务
│   ├── retriever.py       #   混合检索 + RRF + 时间衰减
│   └── ingestor.py        #   新闻入库（切分+向量化）
├── prompts/               # Prompt 工程
│   ├── manager.py         #   版本管理 + 生命周期
│   ├── renderer.py        #   Jinja2 渲染
│   └── experiment.py      #   A/B 实验 + Z 检验
├── agents/                # 5 个 Agent（真实 LLM）
│   ├── base.py            #   BaseAgent + RunContext + 重试 + Span
│   ├── planner.py         #   Planner 选题
│   ├── researcher.py      #   Research 检索
│   ├── writer.py          #   Writer 生成
│   ├── reviewer.py        #   Reviewer 审核
│   └── publisher.py       #   Publisher 发布
├── workflow/
│   └── orchestrator.py    # DAG 编排 + 状态机 + 回退
├── analytics/
│   └── metrics.py         # SQL 数据分析
├── api/
│   └── main.py            # FastAPI 应用（18 个接口）
└── tests/
    └── test_core.py       # 8 项测试
```

## 验证状态

- ✅ 8 项单元测试全通过（DB / Prompt 渲染 / 新闻入库 / RAG 检索 / 分析 / A/B 分桶 / FastAPI / Z 检验）
- ✅ API 服务启动正常，18 个接口可用
- ✅ RAG 检索准确（"GPT-6" 召回 OpenAI Blog / Reuters 相关新闻）
- ✅ 8 篇示例新闻入库，14 个 chunk
- ✅ 默认 3 个 Prompt 模板（planner/writer/reviewer）seed 为 production

## 真实调用示例

配置 `TF_LLM_API_KEY` 后：

```bash
# 生产一篇 GPT-6 报道
curl -X POST http://localhost:8000/api/content/run-topic \
  -H "Content-Type: application/json" \
  -d '{"title":"OpenAI 发布 GPT-6","summary":"10万亿参数","category":"tech","angles":["技术解析","行业影响"]}'

# 查看任务 Trace
curl http://localhost:8000/api/tasks/{task_id}/trace
```

端到端流程：Research(RAG检索) → Writer(LLM生成,强制引用) → Reviewer(事实核查+合规) → pass → Publisher(灰度发布)。
Reviewer 不通过则回退 Writer（≤2次），合规命中强制 reject + Bad Case 记录。
