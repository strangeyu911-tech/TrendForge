# Workflow 设计文档

> 配套 PRD v1.0，定义 TrendForge 端到端内容生产流水线的编排、异常处理与回退机制。

---

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| 自动化 | 热点发现→检索→生成→审核→发布 全自动 |
| 可编排 | DAG 定义流程，节点可插拔 |
| 可恢复 | 异常自动重试，失败不丢任务 |
| 可介入 | 关键节点支持人工审核 |
| 可观测 | 全链路 Trace，每步可回放 |

---

## 2. Workflow 引擎选型

| 选项 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| Airflow | 成熟、生态好 | 偏批处理、延迟高 | ❌ |
| Temporal | 长任务、状态持久化、强一致 | 学习成本 | ✅ 主选 |
| 自研 DAG | 灵活 | 维护成本高 | ❌ |
| LangGraph | 与 LLM 集成好 | 偏 Agent 编排 | ✅ Agent 层用 |

**决策**：基础设施层用 Temporal（任务持久化、重试、定时）；Agent 协作用 LangGraph（状态机、条件分支、回退）。

---

## 3. DAG 定义

### 3.1 主流程 DAG

```
[hot_signal_listener] ──► [planner] ──► [research] ──► [writer] ──► [reviewer] ──► [publisher]
                                                  ▲            │
                                                  │  revise    │
                                                  └────────────┘
                                                       │ reject
                                                       ▼
                                                [human_review_queue]
```

### 3.2 节点定义

```yaml
workflow: trendforge_main
version: "1.0"
trigger:
  type: event
  source: hot_signal_listener
  condition: "heat_score >= 1e5"

nodes:
  - id: planner
    type: agent
    agent: Planner
    timeout: 60s
    retry:
      max: 2
      backoff: exponential
      base: 5s
    on_failure: fallback_rule_based

  - id: research
    type: agent
    agent: Research
    depends_on: [planner]
    timeout: 120s
    retry:
      max: 2
      backoff: exponential
    on_failure: degraded_single_source

  - id: writer
    type: agent
    agent: Writer
    depends_on: [research]
    timeout: 180s
    retry:
      max: 3
      backoff: exponential
    on_failure: human_fallback

  - id: reviewer
    type: agent
    agent: Reviewer
    depends_on: [writer]
    timeout: 90s
    retry:
      max: 2
    on_verdict:
      pass: publisher
      revise: writer   # 回退，最多 2 次
      reject: human_review_queue

  - id: publisher
    type: agent
    agent: Publisher
    depends_on: [reviewer]
    timeout: 60s
    retry:
      max: 2
    on_failure: partial_publish

  - id: human_review_queue
    type: human
    sla: 30m
    on_action:
      approve: publisher
      edit: writer
      discard: end

  - id: data_pipeline
    type: async
    depends_on: [publisher]
    action: emit_metrics
```

### 3.3 回退次数控制

- Writer ← Reviewer revise：最多 2 次；
- 超过 2 次仍未通过 → 转人工；
- 回退计数持久化在 TaskContext，防止跨实例丢失。

---

## 4. 状态机

每个任务的状态流转：

```
pending → running → succeeded
                 → failed → retrying → running
                 → degraded   (降级完成)
                 → human_pending → running
                 → aborted
```

任务持久化到 PostgreSQL，Temporal 保证 at-least-once 执行。

---

## 5. 异常处理

### 5.1 异常分类

| 类别 | 示例 | 策略 |
|------|------|------|
| 瞬时故障 | 网络超时、限流 429 | 指数退避重试 |
| 模型故障 | LLM 5xx、超时 | 重试 → 切备用模型 |
| 数据故障 | 检索为空、证据冲突 | 降级或回退上游 |
| 质量故障 | Reviewer reject | 回退 Writer |
| 合规故障 | 命中红线 | 直接 reject + 告警 |
| 系统故障 | DB 不可用 | Temporal 持久化，恢复后续跑 |

### 5.2 重试策略

```python
@retry(
    max_attempts=3,
    backoff=ExponentialBackoff(base=5, factor=2, max=60),
    retry_on=[TimeoutError, RateLimitError, ModelServerError],
    no_retry_on=[ComplianceViolationError, SchemaValidationError]
)
async def call_agent(agent, ctx, inputs): ...
```

### 5.3 死信队列

- 重试耗尽的任务进入 DLQ；
- DLQ 消费者：告警 + 人工处理入口；
- DLQ 消息保留 7 天。

### 5.4 熔断

- 单 Agent 失败率 > 30%（窗口 5 min）→ 熔断 60s；
- 熔断期间该 Agent 直接走 fallback；
- 半开试探恢复。

---

## 6. 人工介入

### 6.1 触发条件

- Reviewer 连续 2 次 reject；
- 命中"高危话题"规则（政治、重大灾难）；
- Bad Case 自动标记；
- 运营手动挂起。

### 6.2 人工节点

```yaml
- id: human_review
  type: human
  ui: review_console
  actions:
    - approve: 通过，进入 publisher
    - edit_and_approve: 编辑后通过
    - reject_with_reason: 丢弃，reason 入 Bad Case 库
    - escalate: 升级到高级编辑
  sla: 30m
  sla_breach: auto_approve_with_flag  # 超时策略可配
```

### 6.3 介入留痕

所有人工操作记录到 `human_actions` 表，含操作人、时间、动作、原因、修改内容。

---

## 7. 定时与事件触发

### 7.1 事件触发（主）

- Kafka topic `hot_signals` 来消息即触发主流程；
- 保证至少一次消费，需幂等（按 dedup_key 去重）。

### 7.2 定时触发（辅）

- 每 5 分钟扫描热点源，补充信号；
- 每小时跑"长尾选题"任务（非热点但有价值的话题）；
- 每日 0 点跑数据汇总与 Prompt 健康报告。

---

## 8. 可观测性

### 8.1 Trace

每个任务一个 trace_id，每个 Agent 调用一个 span：

```json
{
  "trace_id": "trace_abc123",
  "task_id": "task_001",
  "spans": [
    {"span_id": "s1", "agent": "planner", "start": "...", "duration_ms": 28000, "status": "ok", "model": "gpt-4o-mini", "tokens": 1200, "cost": 0.05},
    {"span_id": "s2", "agent": "research", "start": "...", "duration_ms": 55000, "status": "degraded", "warnings": ["web_search_timeout"]},
    {"span_id": "s3", "agent": "writer", "start": "...", "duration_ms": 90000, "status": "ok"},
    {"span_id": "s4", "agent": "reviewer", "start": "...", "duration_ms": 60000, "status": "ok", "verdict": "pass"},
    {"span_id": "s5", "agent": "publisher", "start": "...", "duration_ms": 8000, "status": "ok"}
  ],
  "total_duration_ms": 241000,
  "total_cost_cny": 0.32
}
```

### 8.2 关键指标

| 指标 | 阈值 | 告警 |
|------|------|------|
| 端到端 P95 | > 15 min | P1 |
| 单 Agent P95 | 见 Agent 设计 | P2 |
| 任务失败率 | > 5% | P1 |
| 人工介入率 | > 10% | P2 |
| DLQ 积压 | > 50 | P1 |
| 熔断次数 | > 0 | P1 |

---

## 9. 配置化与可插拔

### 9.1 流程配置

DAG 定义存 YAML，热加载：

```yaml
# config/workflow_main.yaml
strategies:
  tech:
    reviewer_strict: false
    gray_release_ratio: 0.1
  politics:
    reviewer_strict: true
    human_review_required: true
    gray_release_ratio: 0  # 不灰度，人工确认后直发
```

### 9.2 Agent 替换

Agent 实现注册表，运行时按配置选择：

```python
AGENT_REGISTRY = {
  "planner": {"default": PlannerAgent, "rule_based": RulePlannerAgent},
  "writer": {"gpt4o": GPT4oWriter, "claude": ClaudeWriter, "gemini": GeminiWriter},
  ...
}
```

---

## 10. 容量与扩展

- Agent 无状态 → 水平扩展 Worker；
- 检索与 LLM 调用异步并发；
- 队列削峰（Kafka 分区）；
- 预期峰值：500 任务/分钟，需 20 个 Worker。

---

## 11. 灾备

- Temporal 持久化到 PG，PG 主从；
- Milvus / ES 集群；
- LLM 多供应商（OpenAI / Claude / 自建）；
- 跨可用区部署。
