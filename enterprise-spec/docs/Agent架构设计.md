# Agent 架构设计文档

> 配套 PRD v1.0，定义 TrendForge 五大 Agent 的职责、I/O 契约、协作链路与异常回退机制。

---

## 1. 设计原则

1. **单一职责**：每个 Agent 只做一件事，便于独立优化与替换。
2. **契约驱动**：Agent 间通过结构化 Schema 通信，不依赖隐式上下文。
3. **无状态**：Agent 本身无状态，状态由 Workflow 持久化，便于水平扩展。
4. **可观测**：每次调用记录 input/output/latency/tokens/cost。
5. **可回退**：任何 Agent 失败都有明确的回退路径，不允许静默失败。
6. **可插拔**：Agent 实现可替换（如 Writer 可切换 GPT/Claude/Gemini）。

---

## 2. Agent 总览

```
                  ┌──────────┐
   热点信号 ─────► │ Planner  │ ── 选题任务 ──┐
                  └──────────┘                  ▼
                                          ┌──────────┐
                                          │ Research │ ◄── RAG / Web
                                          └────┬─────┘
                                               │ 证据集
                                               ▼
                                          ┌──────────┐
                                          │  Writer  │ ◄── Prompt 库
                                          └────┬─────┘
                                               │ 稿件
                                               ▼
                                          ┌──────────┐
                            ┌─────────────│ Reviewer │
                            │不通过        └────┬─────┘
                            │回退               │通过
                            └───────┐           ▼
                                    │     ┌──────────┐
                                    │     │ Publisher │ ── 多渠道
                                    │     └──────────┘
                                    ▼
                              [Bad Case 队列]
```

---

## 3. 通用契约

### 3.1 任务上下文（TaskContext）

所有 Agent 共享的上下文，随流程流转：

```json
{
  "task_id": "task_20260721_001",
  "trace_id": "trace_abc123",
  "topic": "OpenAI 发布 GPT-6",
  "language": "zh",
  "priority": "P0",
  "sla_deadline": "2026-07-21T19:20:00+08:00",
  "prompt_version": {
    "planner": "v1.2.0",
    "research": "v1.1.0",
    "writer": "v2.0.1",
    "reviewer": "v1.3.0"
  },
  "history": [
    {"agent": "planner", "ts": "...", "status": "ok"}
  ]
}
```

### 3.2 标准 Agent 接口

```python
class BaseAgent(ABC):
    name: str
    version: str

    @abstractmethod
    async def run(self, ctx: TaskContext, inputs: AgentInput) -> AgentOutput:
        ...

    @abstractmethod
    async def fallback(self, ctx: TaskContext, error: AgentError) -> AgentOutput:
        ...
```

### 3.3 AgentOutput 通用结构

```json
{
  "agent": "writer",
  "status": "ok | degraded | failed",
  "data": { ... },            // Agent 特定输出
  "metrics": {
    "latency_ms": 3200,
    "tokens_in": 1200,
    "tokens_out": 800,
    "cost_cny": 0.12,
    "model": "gpt-4o-mini"
  },
  "warnings": ["low_confidence_evidence"],
  "trace_id": "trace_abc123"
}
```

---

## 4. Planner（选题策划与任务分配）

### 4.1 职责

- 聚合多源热点信号，识别 Hot Topic；
- 对话题打分、去重、过滤；
- 生成选题并分配下游任务。

### 4.2 输入

```json
{
  "signals": [
    {"source": "weibo_hot", "items": [{"title": "...", "heat": 9.8e6, "url": "..."}]},
    {"source": "twitter_trend", "items": [...]},
    {"source": "news_rss", "items": [...]}
  ],
  "strategy": {
    "categories": ["tech", "finance", "world"],
    "languages": ["zh", "en"],
    "max_topics": 20,
    "min_heat": 1e5,
    "sensitive_filters": ["politics_redline"]
  }
}
```

### 4.3 输出

```json
{
  "topics": [
    {
      "topic_id": "topic_001",
      "title": "OpenAI 发布 GPT-6",
      "summary": "...",
      "category": "tech",
      "heat_score": 9.5,
      "suggested_angles": ["技术解析", "行业影响", "竞品对比"],
      "target_languages": ["zh", "en"],
      "priority": "P0",
      "evidence_hint": ["https://openai.com/blog/..."],
      "dedup_key": "gpt6_launch_20260721"
    }
  ]
}
```

### 4.4 内部流程

1. **信号归一化**：不同源字段统一为 `{title, heat, url, source, ts}`。
2. **去重**：基于标题语义相似度（≥0.85 视为重复）+ 关键实体匹配。
3. **打分**：`heat_score = f(原始热度, 增速, 跨源出现次数, 时效性)`。
4. **过滤**：敏感词、版权、24h 内已发布去重。
5. **角度生成**：LLM 基于话题生成 3 个差异化角度。
6. **任务分配**：按优先级与 SLA 入队。

### 4.5 异常回退

| 异常 | 处理 |
|------|------|
| 信号源不可用 | 跳过该源，标记 degraded，继续聚合其他源 |
| LLM 调用失败 | 退化为规则打分（基于热度排序），不生成角度（用默认角度） |
| 全部信号源失败 | 标记 failed，告警，使用 24h 缓存选题兜底 |
| 输出超过 max_topics | 按 heat_score 截断 |

---

## 5. Research（热点检索与信息收集）

### 5.1 职责

- 基于 Planner 选题，调用 RAG 检索 + Web 检索；
- 输出结构化证据集合，供 Writer 引用。

### 5.2 输入

```json
{
  "topic": {
    "topic_id": "topic_001",
    "title": "OpenAI 发布 GPT-6",
    "suggested_angles": ["技术解析"],
    "target_languages": ["zh", "en"]
  },
  "retrieval_config": {
    "top_k": 20,
    "min_relevance": 0.6,
    "time_window_hours": 48,
    "sources": ["rag_news_kb", "web_search"]
  }
}
```

### 5.3 输出

```json
{
  "evidences": [
    {
      "evidence_id": "ev_001",
      "content": "OpenAI 于 7 月 21 日发布 GPT-6...",
      "source_url": "https://openai.com/blog/gpt6",
      "source_name": "OpenAI Blog",
      "published_at": "2026-07-21T18:00:00Z",
      "credibility": 0.95,
      "language": "en",
      "retrieval_score": 0.92,
      "is_conflict": false,
      "entities": ["OpenAI", "GPT-6"]
    }
  ],
  "conflicts": [
    {
      "claim": "GPT-6 参数量",
      "values": [{"value": "10T", "evidence_ids": ["ev_002"]},
                 {"value": "8T", "evidence_ids": ["ev_003"]}]
    }
  ],
  "coverage_summary": "共召回 23 条证据，覆盖 8 个来源，1 处冲突"
}
```

### 5.4 内部流程

1. **查询改写**：LLM 基于选题生成多个检索 query（含角度、实体）。
2. **并行检索**：RAG 向量检索 + BM25 + Web Search 并行。
3. **融合重排**：RRF（Reciprocal Rank Fusion）+ 时间衰减加权。
4. **冲突检测**：相同事实断言多源不一致则标记。
5. **可信度评估**：基于来源白名单 + 一致性 + 时效性。
6. **去重压缩**：语义相似片段合并。

### 5.5 异常回退

| 异常 | 处理 |
|------|------|
| RAG 检索失败 | 仅用 Web Search，标记 degraded |
| Web Search 失败 | 仅用 RAG，标记 degraded |
| 召回数 < 5 | 标记 low_evidence，触发"补充检索"重试 1 次；仍不足则回退 Planner 改角度 |
| 全部失败 | failed，告警，任务转人工 |
| 证据严重冲突 | 标记 conflict，Writer 须显式说明分歧 |

---

## 6. Writer（内容生成）

### 6.1 职责

- 基于 Research 证据 + Prompt 模板生成结构化稿件；
- 强制引用证据 ID。

### 6.2 输入

```json
{
  "topic": {...},
  "evidences": [...],
  "template": "deep_dive",
  "prompt_version": "v2.0.1",
  "language": "zh",
  "constraints": {
    "min_words": 400,
    "max_words": 1200,
    "must_cite_all_evidences": true,
    "tone": "objective"
  }
}
```

### 6.3 输出

```json
{
  "article": {
    "title": "GPT-6 来了：10 万亿参数背后的工程突破",
    "summary": "...",
    "body": [
      {"type": "paragraph", "text": "...", "citations": ["ev_001", "ev_002"]},
      {"type": "heading", "text": "技术解析"},
      {"type": "paragraph", "text": "...", "citations": ["ev_003"]}
    ],
    "tags": ["AI", "OpenAI", "大模型"],
    "cover_suggestion": "一个发光的神经网络节点..."
  },
  "citations": ["ev_001", "ev_002", "ev_003"],
  "word_count": 850,
  "language": "zh"
}
```

### 6.4 内部流程

1. **模板选择**：根据 topic.category 与 strategy 选模板（快讯/深度/盘点/图表）。
2. **Prompt 组装**：变量填充（topic/evidences/template/constraints）→ 渲染 Jinja2。
3. **分级生成**：draft 用便宜模型（gpt-4o-mini）生成草稿；quality 用强模型精修。
4. **引用校验**：本地脚本校验每个 citation 是否在 evidences 中，缺失即重写该段。
5. **字数控制**：超长截断 + 不足补全。

### 6.5 异常回退

| 异常 | 处理 |
|------|------|
| LLM 调用超时 | 重试 2 次（指数退避），仍失败切便宜模型 |
| 引用校验失败 | 局部重写该段，最多 3 轮 |
| 字数严重偏离 | 重新生成 1 次 |
| 输出格式错误 | JSON 修复 + Schema 校验，失败则重试 |
| 全部失败 | failed，转人工 |

---

## 7. Reviewer（质量审核与事实核查）

### 7.1 职责

- 事实核查：引用与证据一致性；
- 质量打分：可读性/客观性/完整性/时效性；
- 合规审核：敏感词、版权、政治红线。

### 7.2 输入

```json
{
  "topic": {...},
  "evidences": [...],
  "article": {...},
  "review_policy": {
    "min_quality_score": 3.5,
    "fact_check_strict": true,
    "compliance_rules": ["sensitive_words_v3", "politics_redline"]
  }
}
```

### 7.3 输出

```json
{
  "verdict": "pass | revise | reject",
  "quality_scores": {
    "readability": 4.2,
    "objectivity": 4.0,
    "completeness": 3.8,
    "timeliness": 4.5,
    "overall": 4.1
  },
  "fact_check": {
    "checked_claims": 12,
    "consistent": 11,
    "inconsistent": 1,
    "details": [{"claim": "...", "evidence_id": "ev_003", "status": "inconsistent", "reason": "..."}]
  },
  "compliance": {
    "sensitive_hits": [],
    "copyright_risk": "low",
    "politics_risk": "none"
  },
  "revision_suggestions": [
    {"section": "技术解析", "issue": "数据与证据不符", "fix": "改为 8T 参数"}
  ],
  "bad_case_flag": false
}
```

### 7.4 内部流程

1. **事实核查**：抽取文章每个断言 → 比对证据 → 标记不一致。
2. **合规扫描**：敏感词词典 + 规则引擎 + 政治红线模型。
3. **质量打分**：LLM rubric 评分（1-5 分四维）+ 规则校验。
4. **裁决**：
   - 合规命中 → reject；
   - 事实不一致 ≥ 1 → revise（带建议回退 Writer）；
   - overall < min_quality_score → revise；
   - 否则 pass。

> 严格度说明：事实不一致即回退为默认策略；可在 ReviewPolicy 设 `fact_strict=false` 时降级为「仅 critical 不一致（如数字/实体错误）回退，minor 不一致标注放行」，与 Workflow §9.1 的 `reviewer_strict` 开关联动。

### 7.5 异常回退

| 异常 | 处理 |
|------|------|
| 事实核查模型失败 | 退化为规则匹配（关键词比对），标记 degraded |
| 合规引擎失败 | **强制 reject**（保守策略），转人工 |
| LLM 评分失败 | 退化为规则评分（长度/引用率/结构） |
| 回退次数超限（>2） | 转人工审核队列 |

---

## 8. Publisher（内容发布与分发）

### 8.1 职责

- 多渠道发布；
- 灰度发布与效果观察；
- 元数据回写；
- 撤回机制。

### 8.2 输入

```json
{
  "article": {...},
  "review_verdict": "pass",
  "publish_config": {
    "channels": ["site_feed", "weibo", "twitter", "rss"],
    "gray_release": {
      "enabled": true,
      "initial_ratio": 0.1,
      "scale_up_threshold_ctr": 0.03,
      "observation_minutes": 30
    },
    "prompt_version": "v2.0.1"
  }
}
```

### 8.3 输出

```json
{
  "publish_records": [
    {
      "channel": "site_feed",
      "content_id": "c_20260721_001",
      "url": "https://site.com/article/001",
      "status": "published | gray_10pct | failed",
      "published_at": "2026-07-21T19:16:00+08:00"
    }
  ],
  "gray_status": {
    "current_ratio": 0.1,
    "next_action": "scale_up | hold | rollback",
    "observed_ctr": 0.041
  },
  "metadata": {
    "prompt_version": "v2.0.1",
    "evidence_ids": ["ev_001", "ev_002"],
    "trace_id": "trace_abc123"
  }
}
```

### 8.4 内部流程

1. **渠道适配**：按各渠道格式转换（字数/标签/图片）。
2. **灰度发布**：先 10% 流量，观察 30 分钟 CTR，达标则放量。
3. **元数据回写**：发布即写入 content_id、prompt_version、trace_id。
4. **撤回**：监听撤回指令，多渠道并行下线。

### 8.5 异常回退

| 异常 | 处理 |
|------|------|
| 单渠道发布失败 | 重试 2 次，仍失败标记 channel_failed，不影响其他渠道 |
| 灰度 CTR 不达标 | 自动 rollback，文章下线，转 Reviewer 复核 |
| 撤回指令 | 最高优先级，全网并行下线，失败告警人工兜底 |
| 元数据回写失败 | 异步重试队列，最多 5 次 |

---

## 9. 协作链路（Happy Path）

```
T+0s     Planner 收到信号 → 输出选题（耗时 ~30s）
T+30s    Research 检索 → 输出证据（耗时 ~60s）
T+90s    Writer 生成 → 输出稿件（耗时 ~90s）
T+180s   Reviewer 审核 → pass（耗时 ~60s）
T+240s   Publisher 灰度发布（耗时 ~10s）
T+250s   灰度观察 30min → 达标全量
T+250s~  数据回流 → 看板更新
```

端到端 P50 ≈ 4 分钟（不含灰度观察），满足 SLA ≤ 8 分钟。

---

## 10. 异常回退矩阵（汇总）

| Agent | 降级策略 | 失败兜底 |
|-------|----------|----------|
| Planner | 规则打分替代 LLM | 24h 缓存选题 |
| Research | 单源降级 | 人工补充线索 |
| Writer | 草稿模型 + 精修 | 转人工 |
| Reviewer | 规则评分替代 LLM | **强制保守 reject + 人工** |
| Publisher | 单渠道隔离 | 撤回 + 人工 |

---

## 11. 可观测性

每个 Agent 调用产出统一 Trace 记录：

```json
{
  "trace_id": "trace_abc123",
  "task_id": "task_001",
  "spans": [
    {"agent": "planner", "start": "...", "end": "...", "status": "ok", "model": "...", "tokens": 1200, "cost": 0.05},
    {"agent": "research", "start": "...", "end": "...", "status": "degraded", "warnings": ["web_search_failed"]},
    ...
  ]
}
```

看板指标：成功率、降级率、P50/P95 时延、Token 成本、回退次数、人工介入率。

---

## 12. 扩展性设计

- **新 Agent 接入**：实现 BaseAgent 接口 + 注册到 Workflow 引擎。
- **新渠道接入**：实现 PublisherAdapter 接口。
- **新语言接入**：新增 Prompt 模板 + 翻译校验。
- **新模型接入**：Agent 配置 model 字段，运行时切换。
