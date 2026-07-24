# RAG 知识库设计文档

> 配套 PRD v1.0，定义 TrendForge 新闻知识库的架构、数据流、检索策略与评估体系。

---

## 1. 设计目标

| 目标 | 指标 |
|------|------|
| 时效性 | 新闻入库延迟 ≤ 5 分钟 |
| 召回质量 | nDCG@10 ≥ 0.7 |
| 可溯源性 | 100% 片段可回溯到原始 URL |
| 规模 | 支撑 1 亿+ 文档，QPS ≥ 100 |
| 成本 | 单次检索 ≤ ¥0.01 |

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     数据接入层                            │
│  RSS / API / 爬虫 / 第三方新闻源 / 社媒 trending          │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     数据处理层                            │
│  清洗 → 去重 → 切分 → 实体抽取 → 向量化 → 入库           │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     存储层                                │
│  向量库(Milvus) │ 关键词库(ES) │ 元数据库(PostgreSQL)     │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     检索层                                │
│  Query 改写 → 混合检索 → 重排 → 时间衰减 → 结果聚合       │
└──────────────────────┬──────────────────────────────────┘
                       ▼
              [Research Agent]
```

---

## 3. 数据接入层

### 3.1 新闻源清单

| 源 | 类型 | 接入方式 | 语言 | 更新频率 |
|----|------|----------|------|----------|
| 新华社 / 人民日报 | 官媒 | RSS | zh | 5 min |
| 财新 / 36氪 / 虎嗅 | 财经科技 | RSS + API | zh | 10 min |
| Reuters / AP / Bloomberg | 国际通讯社 | API（授权） | en | 5 min |
| TechCrunch / The Verge | 科技媒体 | RSS | en | 15 min |
| BBC / NYT / Guardian | 综合 | RSS | en | 15 min |
| 微博热搜 / Twitter Trend | 社媒趋势 | API | zh/en | 1 min |
| Google News | 聚合 | RSS | multi | 10 min |

### 3.2 接入规范

统一 `RawNewsItem` schema：

```json
{
  "source_id": "reuters_20260721_001",
  "source_name": "Reuters",
  "source_type": "official_media | tech_media | social_trend",
  "title": "...",
  "content": "...",
  "url": "https://reuters.com/...",
  "published_at": "2026-07-21T18:00:00Z",
  "fetched_at": "2026-07-21T18:01:00Z",
  "language": "en",
  "category": "tech",
  "entities": ["OpenAI", "GPT-6"],
  "credibility_tier": 1
}
```

**可信度分级**（credibility_tier）：

- Tier 1：官方通讯社、央媒（1.0）
- Tier 2：主流媒体、头部科技媒体（0.8）
- Tier 3：行业垂直媒体（0.6）
- Tier 4：社媒、自媒体（0.3）

---

## 4. 数据处理层

### 4.1 清洗

- 去 HTML 标签、广告、导航；
- 正文提取（Readability 算法）；
- 繁简转换、全半角统一；
- 编码统一 UTF-8。

### 4.2 去重

三层去重：

1. **URL 去重**：BloomFilter，O(1)。
2. **标题去重**：MinHash，相似度 ≥ 0.9 视为重复。
3. **正文去重**：SimHash，海明距离 ≤ 3 视为重复。

### 4.3 切分策略

采用"语义+结构"混合切分：

| 模式 | 切分粒度 | 适用 |
|------|----------|------|
| 段落切分 | 自然段 | 长篇深度报道 |
| 滑窗切分 | 256 token，overlap 50 | 短讯、快讯 |
| 标题切分 | 整篇（≤512 token） | 微博/Twitter 趋势 |

每段保留 `parent_doc_id`，支持"召回片段 → 回溯原文"。

### 4.4 实体抽取

- 使用 NER 模型抽取人名、机构、地点、产品；
- 实体入实体表，建立"实体 → 文档"倒排；
- 支持基于实体的精确过滤。

### 4.5 向量化

| 用途 | 模型 | 维度 |
|------|------|------|
| 主向量 | bge-large-zh-v1.5（中）/ bge-large-en（英） | 1024 |
| 多语言兜底 | multilingual-e5-large | 1024 |
| 重排 | bge-reranker-large | - |

向量化批量异步执行，QPS 控制避免 GPU 过载。

---

## 5. 存储层

### 5.1 向量库（Milvus）

```sql
Collection: news_chunks
Fields:
  - chunk_id (PK, varchar)
  - embedding (float_vector, 1024)
  - parent_doc_id (varchar)
  - source_url (varchar)
  - source_name (varchar)
  - published_at (int64, timestamp)
  - credibility_tier (int8)
  - language (varchar)
  - category (varchar)
  - entities (varchar, array)
Index:
  - HNSW (M=16, efConstruction=200)
  - 过滤字段建立标量索引
```

### 5.2 关键词库（Elasticsearch）

```json
{
  "index": "news_fulltext",
  "fields": {
    "title": {"type": "text", "analyzer": "ik_smart"},
    "content": {"type": "text", "analyzer": "ik_max_word"},
    "entities": {"type": "keyword"},
    "published_at": {"type": "date"}
  }
}
```

### 5.3 元数据库（PostgreSQL）

```sql
CREATE TABLE news_documents (
  doc_id          TEXT PRIMARY KEY,
  source_id       TEXT,
  source_name     TEXT,
  source_type     TEXT,
  title           TEXT,
  content         TEXT,
  url             TEXT UNIQUE,
  published_at    TIMESTAMPTZ,
  fetched_at      TIMESTAMPTZ,
  language        TEXT,
  category        TEXT,
  credibility_tier INT,
  entities        TEXT[],
  status          TEXT,  -- raw / processed / indexed
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE news_chunks (
  chunk_id        TEXT PRIMARY KEY,
  doc_id          TEXT REFERENCES news_documents(doc_id),
  chunk_index     INT,
  content         TEXT,
  token_count     INT,
  embedding_model TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chunks_doc ON news_chunks(doc_id);
CREATE INDEX idx_docs_published ON news_documents(published_at DESC);
CREATE INDEX idx_docs_url ON news_documents(url);
```

---

## 6. 检索层

### 6.1 Query 改写

Research Agent 传入 topic，RAG 服务用 LLM 改写为多个 query：

```json
{
  "original_topic": "OpenAI 发布 GPT-6",
  "rewritten_queries": [
    "OpenAI GPT-6 发布 参数 性能",
    "GPT-6 launch announcement specifications",
    "GPT-6 vs GPT-5 comparison",
    "OpenAI 2026年7月 新品发布"
  ],
  "entities_filter": ["OpenAI", "GPT-6"],
  "time_window_hours": 48
}
```

### 6.2 混合检索

并行执行三路检索，再 RRF 融合：

1. **向量检索**（Milvus）：每个 rewritten query 取 top 30。
2. **关键词检索**（ES）：BM25，每个 query 取 top 30。
3. **实体检索**：精确匹配实体，取相关文档 top 20。

**RRF 融合公式**：

```
score(d) = Σ_q Σ_rank  1 / (k + rank_q(d))     k=60
```

### 6.3 重排

对融合后 top 50 用 `bge-reranker-large` 重排，取 top 20。

### 6.4 时间衰减加权

热点场景时效性优先，对最终分加权：

```
final_score = rerank_score * time_decay(published_at)
time_decay(t) = exp(-λ * hours_ago)     λ=0.02（半衰期 ~35h）
```

可按 category 调 λ：快讯类 λ=0.05（半衰期 ~14h），深度类 λ=0.01。

### 6.5 结果聚合

```json
{
  "chunks": [
    {
      "chunk_id": "chk_001",
      "content": "...",
      "doc_id": "doc_001",
      "source_url": "...",
      "source_name": "Reuters",
      "published_at": "...",
      "credibility_tier": 1,
      "rerank_score": 0.92,
      "final_score": 0.88,
      "entities": ["OpenAI", "GPT-6"]
    }
  ],
  "stats": {
    "vector_hits": 120,
    "bm25_hits": 90,
    "entity_hits": 20,
    "fused": 50,
    "reranked": 20,
    "sources_count": 8
  }
}
```

---

## 7. 增量更新机制

### 7.1 实时入库

```
新闻源 → Kafka(topic: raw_news) → 清洗去重 Flink 任务 → Kafka(topic: clean_news)
        → 向量化 Worker → Milvus + ES + PG
```

### 7.2 知识库冷启动

- 首次部署回灌近 30 天新闻（约 50 万文档）；
- 批量向量化，吞吐 1000 docs/s；
- 预计冷启动耗时 8 小时。

### 7.3 TTL 与归档

- 热数据：30 天内，全量索引；
- 温数据：30-180 天，仅元数据 + 关键词索引；
- 冷数据：> 180 天，归档到对象存储，按需检索。

---

## 8. 评估体系

### 8.1 离线评估

构建标注集（人工标注 500 query 的相关文档）：

| 指标 | 目标 |
|------|------|
| Recall@20 | ≥ 0.85 |
| nDCG@10 | ≥ 0.70 |
| MRR | ≥ 0.65 |
| 引用准确率 | ≥ 0.95 |

### 8.2 在线评估

| 指标 | 来源 |
|------|------|
| 召回片段被 Writer 引用率 | Writer 输出 |
| 引用片段 Reviewer 一致率 | Reviewer 输出 |
| 检索延迟 P95 | Trace |
| 无结果率 | 监控 |

### 8.3 A/B 实验维度

- 切分策略（段落 vs 滑窗）；
- 向量模型（bge vs e5）；
- 融合权重（向量 vs BM25）；
- 时间衰减 λ。

---

## 9. 成本优化

| 优化点 | 措施 | 预期节省 |
|--------|------|----------|
| 向量模型本地部署 | bge 自建 GPU 推理 | vs API 节省 80% |
| 缓存 | query 哈希缓存 top 结果，TTL 5 min | 命中率 30% |
| 分级检索 | 先 BM25 粗排 → 向量精排 | 向量 QPS 降 60% |
| 文档压缩 | 长文档先摘要再向量化 | 存储 -40% |

---

## 10. 监控告警

| 指标 | 阈值 | 告警 |
|------|------|------|
| 入库延迟 | > 10 min | P1 |
| 检索 P95 | > 800 ms | P2 |
| 无结果率 | > 5% | P2 |
| 向量化失败率 | > 1% | P1 |
| 向量库 QPS | > 80% 容量 | P2 |

---

## 11. 安全与合规

- 仅存储公共新闻源内容，付费源仅存摘要 + 链接；
- 用户隐私数据不入库；
- 敏感话题文档标记 `sensitive=true`，检索时按策略过滤；
- 数据库访问全审计。
