# SQL 数据看板设计文档

> 配套 PRD v1.0，定义 TrendForge 数据埋点、表结构、SQL 分析与看板设计。

---

## 1. 数据埋点

### 1.1 事件清单

| 事件 | 触发时机 | 关键字段 |
|------|----------|----------|
| `topic_discovered` | Planner 输出选题 | topic_id, category, heat_score |
| `evidence_retrieved` | Research 完成 | topic_id, evidence_count, sources |
| `article_generated` | Writer 完成 | topic_id, prompt_version, word_count, citations |
| `review_decided` | Reviewer 完成 | verdict, quality_scores, fact_check |
| `article_published` | Publisher 发布 | content_id, channel, gray_ratio |
| `content_exposed` | 内容曝光 | content_id, user_id, channel, position |
| `content_clicked` | 用户点击 | content_id, user_id, channel |
| `content_read` | 进入阅读页 | content_id, user_id |
| `content_finished` | 完读 | content_id, user_id, read_duration |
| `content_interacted` | 点赞/评论/分享 | content_id, user_id, action_type |
| `bad_case_flagged` | 标记 Bad Case | content_id, reason, source |
| `experiment_assigned` | A/B 分桶 | content_id, experiment_id, variant |

### 1.2 埋点质量

- 客户端埋点 + 服务端埋点双写，以服务端为准；
- 埋点字段 schema 强校验，不符合直接告警；
- 完整率 SLA ≥ 99%。

---

## 2. 数据仓库分层

```
ODS（原始日志） → DWD（明细宽表） → DWS（轻度汇总） → ADS（应用层）
```

### 2.1 ODS 层

原始事件流，按天分区，保留 90 天。

### 2.2 DWD 层

#### `dwd_content_fact`（内容事实表，一行 = 一篇内容）

```sql
CREATE TABLE dwd_content_fact (
  content_id          TEXT PRIMARY KEY,
  topic_id            TEXT,
  category            TEXT,
  language            TEXT,
  template_type       TEXT,
  prompt_planner_v    TEXT,
  prompt_research_v   TEXT,
  prompt_writer_v     TEXT,
  prompt_reviewer_v   TEXT,
  evidence_count      INT,
  citation_count      INT,
  word_count          INT,
  quality_overall     FLOAT,
  fact_consistency    FLOAT,
  review_verdict      TEXT,
  review_rounds       INT,          -- 审核轮次（含回退）
  is_bad_case         BOOLEAN,
  bad_case_reason     TEXT,
  published_at        TIMESTAMPTZ,
  channels            TEXT[],
  gray_ratio          FLOAT,
  trace_id            TEXT,
  total_cost_cny      FLOAT,
  production_duration_sec INT
);
```

#### `dwd_content_event`（内容行为表，一行 = 一次行为）

```sql
CREATE TABLE dwd_content_event (
  event_id    BIGSERIAL PRIMARY KEY,
  content_id  TEXT,
  user_id     TEXT,
  event_type  TEXT,   -- exposed/clicked/read/finished/interacted
  channel     TEXT,
  position    INT,
  read_duration_sec INT,
  action_type TEXT,   -- like/comment/share
  event_ts    TIMESTAMPTZ,
  dt          DATE    -- 分区键
) PARTITION BY RANGE (dt);
```

### 2.3 DWS 层

#### `dws_content_daily`（内容日汇总）

```sql
CREATE TABLE dws_content_daily (
  content_id      TEXT,
  dt              DATE,
  impressions     BIGINT,
  clicks          BIGINT,
  reads           BIGINT,
  finishes        BIGINT,
  likes           BIGINT,
  comments        BIGINT,
  shares          BIGINT,
  read_duration_total_sec BIGINT,
  ctr             FLOAT,    -- clicks/impressions
  read_rate       FLOAT,    -- reads/clicks
  finish_rate     FLOAT,    -- finishes/reads
  interact_rate   FLOAT,    -- (likes+comments+shares)/reads
  PRIMARY KEY (content_id, dt)
);
```

---

## 3. 核心分析 SQL

### 3.1 CTR 分析

#### 3.1.1 整体 CTR 趋势

```sql
SELECT
  dt,
  COUNT(DISTINCT content_id) AS articles,
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  ROUND(SUM(clicks)::numeric / NULLIF(SUM(impressions),0), 4) AS ctr
FROM dws_content_daily
WHERE dt >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY dt
ORDER BY dt;
```

#### 3.1.2 分品类 CTR

```sql
SELECT
  f.category,
  SUM(d.impressions) AS impressions,
  SUM(d.clicks) AS clicks,
  ROUND(SUM(d.clicks)::numeric / NULLIF(SUM(d.impressions),0), 4) AS ctr
FROM dws_content_daily d
JOIN dwd_content_fact f USING(content_id)
WHERE d.dt >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY f.category
ORDER BY ctr DESC;
```

#### 3.1.3 标题 CTR 排行（找优质标题模式）

```sql
SELECT
  content_id,
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  ROUND(SUM(clicks)::numeric / NULLIF(SUM(impressions),0), 4) AS ctr
FROM dws_content_daily
WHERE dt >= CURRENT_DATE - INTERVAL '7 days'
  AND SUM(impressions) >= 1000   -- 显著性过滤
GROUP BY content_id
HAVING SUM(clicks)::numeric / NULLIF(SUM(impressions),0) > 0.05
ORDER BY ctr DESC
LIMIT 20;
```

### 3.2 阅读率分析

#### 3.2.1 阅读率漏斗

```sql
SELECT
  SUM(impressions) AS impressions,
  SUM(clicks) AS clicks,
  SUM(reads) AS reads,
  SUM(finishes) AS finishes,
  ROUND(SUM(clicks)::numeric / NULLIF(SUM(impressions),0),4) AS ctr,
  ROUND(SUM(reads)::numeric / NULLIF(SUM(clicks),0),4) AS read_rate,
  ROUND(SUM(finishes)::numeric / NULLIF(SUM(reads),0),4) AS finish_rate
FROM dws_content_daily
WHERE dt = CURRENT_DATE - 1;
```

#### 3.2.2 完读率 vs 字数（找最佳字数区间）

```sql
SELECT
  CASE
    WHEN word_count < 300 THEN '<300'
    WHEN word_count < 600 THEN '300-600'
    WHEN word_count < 1000 THEN '600-1000'
    WHEN word_count < 1500 THEN '1000-1500'
    ELSE '>=1500'
  END AS word_bucket,
  COUNT(DISTINCT f.content_id) AS articles,
  ROUND(AVG(d.finish_rate),4) AS avg_finish_rate,
  ROUND(AVG(d.read_duration_total_sec / NULLIF(d.reads,0)),1) AS avg_read_sec
FROM dwd_content_fact f
JOIN dws_content_daily d USING(content_id)
WHERE d.dt >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY word_bucket
ORDER BY word_bucket;
```

### 3.3 Prompt 效果分析

#### 3.3.1 各 Prompt 版本效果对比

```sql
SELECT
  prompt_writer_v AS prompt_version,
  COUNT(DISTINCT f.content_id) AS articles,
  ROUND(AVG(d.ctr),4) AS avg_ctr,
  ROUND(AVG(d.read_rate),4) AS avg_read_rate,
  ROUND(AVG(d.finish_rate),4) AS avg_finish_rate,
  ROUND(AVG(f.quality_overall),2) AS avg_quality,
  ROUND(AVG(f.fact_consistency),4) AS avg_fact_consistency,
  SUM(CASE WHEN f.is_bad_case THEN 1 ELSE 0 END)::numeric
    / COUNT(*) AS bad_case_rate,
  ROUND(AVG(f.production_duration_sec),1) AS avg_duration_sec,
  ROUND(AVG(f.total_cost_cny),3) AS avg_cost
FROM dwd_content_fact f
JOIN dws_content_daily d USING(content_id)
WHERE d.dt >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY prompt_writer_v
ORDER BY avg_ctr DESC;
```

#### 3.3.2 Prompt 版本切换前后对比

```sql
WITH version_switch AS (
  SELECT 'v1.3.0' AS before_v, 'v2.0.1' AS after_v,
         '2026-07-15' AS switch_date
)
SELECT
  CASE WHEN f.published_at < vs.switch_date THEN 'before' ELSE 'after' END AS period,
  COUNT(*) AS articles,
  ROUND(AVG(d.ctr),4) AS avg_ctr,
  ROUND(AVG(d.read_rate),4) AS avg_read_rate,
  ROUND(SUM(CASE WHEN f.is_bad_case THEN 1 ELSE 0 END)::numeric/COUNT(*),4) AS bad_case_rate
FROM dwd_content_fact f
JOIN dws_content_daily d USING(content_id)
CROSS JOIN version_switch vs
WHERE f.prompt_writer_v IN (vs.before_v, vs.after_v)
  AND f.published_at >= vs.switch_date::date - INTERVAL '7 days'
  AND f.published_at <  vs.switch_date::date + INTERVAL '7 days'
GROUP BY period;
```

### 3.4 A/B 实验分析

```sql
SELECT
  e.experiment_id,
  a.variant,
  COUNT(DISTINCT a.content_id) AS articles,
  ROUND(AVG(d.ctr),4) AS avg_ctr,
  ROUND(AVG(d.read_rate),4) AS avg_read_rate,
  ROUND(AVG(f.fact_consistency),4) AS avg_fact_consistency,
  -- 显著性检验（CTR 用 Z-test 近似）
  CASE
    WHEN abs(avg_ctr_diff) / sqrt(avg_ctr_var/n) > 1.96 THEN 'significant'
    ELSE 'not_significant'
  END AS ctr_significance
FROM experiment_assignments a
JOIN dws_content_daily d ON d.content_id = a.content_id
JOIN dwd_content_fact f ON f.content_id = a.content_id
JOIN prompt_experiments e ON e.experiment_id = a.experiment_id
WHERE e.status = 'running' OR e.status = 'concluded'
GROUP BY e.experiment_id, a.variant;
```

### 3.5 Bad Case 分析

```sql
SELECT
  bad_case_reason,
  COUNT(*) AS cases,
  ROUND(AVG(quality_overall),2) AS avg_quality,
  ROUND(AVG(fact_consistency),4) AS avg_fact,
  array_agg(DISTINCT prompt_writer_v) AS affected_versions
FROM dwd_content_fact
WHERE is_bad_case = true
  AND published_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY bad_case_reason
ORDER BY cases DESC;
```

### 3.6 生产效率分析

```sql
SELECT
  DATE_TRUNC('day', published_at) AS dt,
  COUNT(*) AS articles,
  ROUND(AVG(production_duration_sec),1) AS avg_duration_sec,
  PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY production_duration_sec) AS p50,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY production_duration_sec) AS p95,
  ROUND(AVG(review_rounds),2) AS avg_review_rounds,
  SUM(CASE WHEN review_rounds > 1 THEN 1 ELSE 0 END)::numeric/COUNT(*) AS rollback_rate
FROM dwd_content_fact
WHERE published_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY 1
ORDER BY 1;
```

### 3.7 成本分析

```sql
SELECT
  DATE_TRUNC('day', published_at) AS dt,
  COUNT(*) AS articles,
  ROUND(SUM(total_cost_cny),2) AS total_cost,
  ROUND(AVG(total_cost_cny),3) AS cost_per_article,
  ROUND(SUM(total_cost_cny)/NULLIF(SUM(impressions),0)*1000,3) AS cpm_cny
FROM dwd_content_fact f
LEFT JOIN dws_content_daily d USING(content_id)
WHERE published_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY 1
ORDER BY 1;
```

---

## 4. 看板设计

> 完整可交互看板见 `dashboard/index.html`。

### 4.1 看板分层

| 看板 | 受众 | 核心模块 |
|------|------|----------|
| 经营总览 | 产品负责人 | 北极星、AI 占比、成本、ROI |
| 生产监控 | 运营 | 生产量、时延、通过率、回退率、人工介入 |
| 分发效果 | 运营/编辑 | CTR、阅读率、完读率、互动率、品类对比 |
| Prompt 实验 | 算法/编辑 | 版本对比、A/B 结论、Bad Case 归因 |
| 成本与质量 | 算法负责人 | 单条成本、Token、质量分、事实一致率 |

### 4.2 核心图表

1. **北极星指标卡**：AI 内容总阅读时长、人均阅读深度
2. **生产漏斗**：选题 → 生成 → 通过 → 发布 → 曝光 → 点击 → 完读
3. **CTR 趋势线**：日粒度，支持品类筛选
4. **Prompt 版本雷达图**：CTR/阅读率/质量/事实一致/Bad Case 五维
5. **A/B 实验对比柱状图**：含误差线与显著性标记
6. **Bad Case 帕累托图**：原因分布与累计占比
7. **成本趋势**：单条成本 + CPM

### 4.3 刷新策略

| 看板 | 刷新 |
|------|------|
| 经营总览 | T+10 min |
| 生产监控 | 实时（流式） |
| 分发效果 | T+10 min |
| Prompt 实验 | T+1 h |
| 成本质量 | T+1 h |

### 4.4 告警规则

| 告警 | 条件 | 级别 |
|------|------|------|
| CTR 下跌 | 7 日均值较上周跌幅 > 20% | P1 |
| Bad Case 激增 | 单日 Bad Case 数 > 50 或率 > 10% | P1 |
| 事实一致率下降 | 7 日均值 < 95% | P1 |
| 生产时延超限 | P95 > 15 min | P2 |
| 单条成本超限 | 日均值 > ¥0.8 | P2 |

---

## 5. 数据治理

- 用户行为数据脱敏（user_id 哈希）；
- 内容数据保留 1 年，行为数据 90 天；
- 敏感品类数据访问需审批；
- 看板按角色权限控制（RBAC）。
