# Prompt 版本管理方案

> 配套 PRD v1.0，定义 Prompt 的版本管理、优化迭代、A/B 实验与效果回流机制。

---

## 1. 设计目标

- **可追溯**：每个生产内容都能关联到确切的 Prompt 版本。
- **可回滚**：线上 Prompt 出问题能秒级回滚到上一稳定版本。
- **可实验**：支持 A/B 实验与灰度，量化对比效果。
- **可迭代**：Prompt 优化有标准化流程，沉淀经验。
- **可复用**：模板化、变量化，跨语言跨场景复用。

---

## 2. Prompt 版本规范

### 2.1 语义化版本号

采用 `MAJOR.MINOR.PATCH`：

| 版本位 | 变更类型 | 示例 |
|--------|----------|------|
| MAJOR | 根本性改写（角色/结构/目标变化） | v1 → v2 |
| MINOR | 新增变量、调整段落、新增约束 | v1.0 → v1.1 |
| PATCH | 修 bug、调措辞、改示例 | v1.0.0 → v1.0.1 |

### 2.2 Prompt 元数据 Schema

```json
{
  "prompt_id": "writer_deep_dive",
  "version": "v2.0.1",
  "agent": "writer",
  "scene": "deep_dive",
  "language": "zh",
  "status": "draft | reviewing | staging | production | archived | rollback",
  "author": "strange",
  "created_at": "2026-07-15T10:00:00+08:00",
  "approved_at": "2026-07-16T14:00:00+08:00",
  "parent_version": "v2.0.0",
  "changelog": "修正引用格式示例，避免 Writer 漏写 evidence_id",
  "template": "...",          // Jinja2 模板
  "variables": ["topic", "evidences", "constraints"],
  "default_model": "gpt-4o-mini",
  "expected_output_schema": {...},
  "eval_score": 4.1,
  "tags": ["finance", "tech"]
}
```

### 2.3 不可变原则

- Prompt 版本一经发布（status=production）即不可修改；
- 修改必须新建版本；
- 历史版本永久保留，用于回滚与归因。

---

## 3. Prompt 生命周期

```
   draft ──(自测)──► reviewing ──(评审)──► staging ──(灰度)──► production
                       │                       │                     │
                       │ 不通过                │ 实验失败             │ 出问题
                       ▼                       ▼                     ▼
                    draft                rollback_staging      rollback_production
                                                                   (回滚到上一稳定版)
                                                              archived (归档旧版)
```

### 3.1 评审清单

Prompt 升版前必检：

- [ ] 变量定义完整，无未声明变量；
- [ ] 输出 Schema 与下游 Agent 契约一致；
- [ ] 包含 Few-shot 示例（≥ 2 个）；
- [ ] 明确"禁止编造"、"必须引用"等硬约束；
- [ ] 通过离线评估集（≥ 30 case）；
- [ ] 无敏感词、无诱导违规内容；
- [ ] changelog 清晰说明改动点。

---

## 4. 模板设计

### 4.1 模板结构（Jinja2）

```
# Role
你是一名资深{{ category }}领域新闻编辑。

# Task
基于以下证据，撰写一篇 {{ template_type }} 稿件。

# Constraints
- 字数 {{ constraints.min_words }}~{{ constraints.max_words }}
- 语气：{{ constraints.tone }}
- 必须引用证据 ID，格式 [ev_xxx]
- 禁止编造未在证据中出现的事实
- 输出 JSON，遵循 schema

# Evidence
{% for ev in evidences %}
[{{ ev.evidence_id }}] ({{ ev.source_name }}, {{ ev.published_at }})
{{ ev.content }}
{% endfor %}

# Topic
{{ topic.title }}
角度建议：{{ topic.suggested_angles | join('、') }}

# Output Schema
{{ output_schema }}

# Few-shot
{{ few_shot_examples }}

# Output
```

### 4.2 多语言变体

同一 prompt_id 下，按 language 维护变体：

- `writer_deep_dive.zh.v2.0.1`
- `writer_deep_dive.en.v2.0.1`
- `writer_deep_dive.ja.v2.0.1`

变体间保持变量与 Schema 一致，仅自然语言措辞不同。

### 4.3 Few-shot 管理

Few-shot 示例单独管理（`few_shot_library/`），Prompt 模板引用：

```json
{
  "few_shot_id": "fs_writer_good_001",
  "scene": "writer_deep_dive",
  "input": {...},
  "output": {...},
  "quality_score": 4.5,
  "tags": ["good_example"]
}
```

---

## 5. 离线评估

### 5.1 评估集

每个 Agent 场景维护 ≥ 30 个标注 case：

```json
{
  "case_id": "case_001",
  "scene": "writer_deep_dive",
  "inputs": {...},
  "expected_output": {...},   // 人工撰写的"标杆输出"
  "rubric": {
    "factuality": 5,          // 与证据一致
    "readability": 4,
    "structure": 5
  }
}
```

### 5.2 评估指标

| 指标 | 计算方式 |
|------|----------|
| 事实一致率 | LLM judge + 规则校验引用 |
| 结构合规率 | JSON Schema 校验通过率 |
| 与标杆相似度 | 语义相似度（embedding cosine） |
| 平均质量分 | LLM rubric 评分均值 |
| 引用覆盖率 | 引用 evidence 数 / 总 evidence 数 |

### 5.3 自动评估流水线

```
新版 Prompt → 跑评估集 → 输出指标报告 → 与上一版对比 → 是否通过门槛
                                            ↓ 通过
                                       进入 staging
```

门槛：每项指标不低于上一版 95%，且无单项降幅 > 10%。

---

## 6. A/B 实验

> 详细方案见 `A_B实验方案.md`，此处给出 Prompt 维度的实验设计。

### 6.1 实验配置

```json
{
  "experiment_id": "exp_writer_v2_vs_v1",
  "agent": "writer",
  "scene": "deep_dive",
  "variants": {
    "control": "v1.3.0",
    "treatment": "v2.0.1"
  },
  "traffic_split": {"control": 0.5, "treatment": 0.5},
  "target_metrics": ["ctr", "read_rate", "fact_consistency"],
  "min_sample_size": 1000,
  "significance_level": 0.05,
  "duration_days": 7
}
  ```

### 6.2 分桶策略

- 按 `content_id` 哈希分桶，保证同一读者体验一致；
- 分桶比例可在运行时调整（无需重启）；
- 分桶日志写入 `experiment_assignments` 表。

### 6.3 显著性检验

- 连续指标：Welch t-test（不假设等方差）；
- 比例指标：卡方检验 / Z-test；
- 多指标时用 Bonferroni 校正；
- 达到 min_sample_size 且 p < 0.05 才下结论。

### 6.4 决策规则

| 情况 | 决策 |
|------|------|
| treatment 显著优于 control | 升版 production，旧版 archived |
| treatment 显著劣于 control | 终止实验，treatment 回炉 |
| 无显著差异 | 延长实验 3 天；仍无差异则保守保留 control |
| treatment 出现 Bad Case 激增 | 立即熔断，回滚 |

---

## 7. 效果回流

### 7.1 数据归因

每条发布内容携带 `prompt_version`，数据回流时按版本聚合：

```sql
SELECT
  prompt_version,
  COUNT(*) AS articles,
  AVG(ctr) AS avg_ctr,
  AVG(read_rate) AS avg_read_rate,
  SUM(CASE WHEN bad_case THEN 1 ELSE 0 END) / COUNT(*) AS bad_case_rate
FROM content_metrics
WHERE published_at >= NOW() - INTERVAL '7 days'
GROUP BY prompt_version;
```

### 7.2 Prompt 效果看板

> 完整看板见 `SQL数据看板设计.md` 与 `dashboard/index.html`。

核心图表：

- 各版本 CTR 趋势；
- 各版本 Bad Case 率；
- 版本切换前后对比；
- 实验组 vs 对照组差异。

### 7.3 自动优化建议

系统每日跑批，对每个 production Prompt 产出建议：

- 若 Bad Case 率 > 5%，触发"Prompt 优化任务"；
- 若 CTR 连续 7 天下降，触发"Prompt 优化任务"；
- 任务进入待办，编辑评审后起新版。

---

## 8. 优化迭代流程（SOP）

```
1. 信号触发（Bad Case / CTR 下降 / 业务需求）
        │
        ▼
2. 归因分析（定位是 Prompt 问题还是数据/检索问题）
        │  是 Prompt 问题
        ▼
3. 起草新版本（draft）+ changelog
        │
        ▼
4. 离线评估（跑评估集，对比上一版）
        │  通过门槛
        ▼
5. 评审（编辑 + 算法）
        │  通过
        ▼
6. A/B 实验（staging → 灰度 10% → 50%）
        │  显著优于
        ▼
7. 升版 production，旧版 archived
        │
        ▼
8. 监控 7 天，确认无回归
```

---

## 9. 存储设计

```sql
CREATE TABLE prompts (
  prompt_id     TEXT,
  version       TEXT,
  agent         TEXT,
  scene         TEXT,
  language      TEXT,
  status        TEXT,
  template      TEXT,
  variables     JSONB,
  changelog     TEXT,
  parent_version TEXT,
  author        TEXT,
  created_at    TIMESTAMPTZ,
  approved_at   TIMESTAMPTZ,
  eval_score    FLOAT,
  PRIMARY KEY (prompt_id, version)
);

CREATE TABLE prompt_experiments (
  experiment_id TEXT PRIMARY KEY,
  agent         TEXT,
  scene         TEXT,
  control_version TEXT,
  treatment_version TEXT,
  traffic_split JSONB,
  status        TEXT,  -- running | concluded | aborted
  start_at      TIMESTAMPTZ,
  end_at        TIMESTAMPTZ,
  result        JSONB
);

CREATE TABLE experiment_assignments (
  content_id    TEXT,
  experiment_id TEXT,
  variant       TEXT,  -- control | treatment
  assigned_at   TIMESTAMPTZ,
  PRIMARY KEY (content_id, experiment_id)
);
```

---

## 10. 工具支持

- **Prompt 实验台**（Web）：可视化编辑、评估、实验配置；
- **Diff 工具**：版本间模板 diff；
- **回滚按钮**：一键回滚 production；
- **Changelog 时间线**：版本演进可视化。

---

## 11. 治理

- production 版本变更需双人审批（编辑 + 算法）；
- MAJOR 版本升级需产品负责人签字；
- 每月 Prompt 健康度报告（CTR / Bad Case / 实验结论）；
- 季度 Prompt 退役审查（archived 版本清理）。
