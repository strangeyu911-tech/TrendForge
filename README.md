# TrendForge — AI Native 全球内容供给平台

> 把传统内容生产流程抽象为 AI 可以**持续执行、持续优化、持续学习**的系统。
> Multi-Agent Workflow × RAG × Prompt Engineering × 数据反馈闭环 × 全球化内容策略

一个面向互联网 AI 产品经理求职的作品集项目。它不是"一个 Agent"，而是一个**平台**：从热点检测、选题、检索、成稿、事实核查、审核、分发，到用户行为回流、Prompt 效果评估、Bad Case 闭环的完整内容供给飞轮。

```
                         ┌─────────── TrendForge 平台八大中心 ───────────┐
  知识库   →   RAG   →   Multi-Agent   →   Prompt   →   Content   →   Experiment
 (KB)        检索        Workflow         Center       Center         Center
                                                          ↓
                                       Bad Case ← Reviewer ← Metrics
                                        Center     Center    Center
```

---

## 一、产品定位

**问题**：内容生产依赖人工选题、人工成稿、人工审核，难以规模化、难以全球化、难以持续优化。

**方案**：TrendForge 用 Multi-Agent Workflow 自动化内容生产全链路，用 RAG 保证事实可溯源，用数据反馈闭环让系统越跑越准，用国家策略让同一热点服务不同文化背景的用户。

**核心能力**：
- 🔍 **知识库**：10+ 可信媒体 RSS 自动采集，智能 Chunk，向量检索，每日增量
- 🤖 **8-Agent Workflow**：趋势检测→选题→检索→大纲→成稿→事实核查→审核→分发
- 📝 **Prompt Center**：版本管理 + A/B 实验 + 效果回流（CTR/阅读率→eval_score）
- 📊 **Metrics Center**：漏斗/CTR/阅读率/完读/Prompt ROI/成本，按国家/语言/平台拆分
- 🌍 **全球化**：7 国内容策略（US/GB/JP/KR/IN/BR/CN），不同风格/受众/平台/调性
- 🔁 **反馈闭环**：内容→事件→分析→Prompt 优化→Bad Case 回流

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      TrendForge API (FastAPI)                     │
│  /contents · /run-topic · /trace · /events/simulate · /analytics │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
   ┌───────────▼──────────┐      ┌────────────▼────────────┐
   │  Multi-Agent Workflow │      │   Prompt Center          │
   │  (8 步链路 + 决策日志) │◄────►│  版本/实验/效果回流       │
   └───────────┬──────────┘      └─────────────┬───────────┘
               │                                │
   ┌───────────▼──────────────────────────────▼───────────┐
   │                  RAG 知识库                           │
   │  RSS 采集 → 智能Chunk → Embedding → Chroma + SQLite   │
   └───────────┬──────────────────────────────┬───────────┘
               │                              │
   ┌───────────▼──────────┐      ┌────────────▼────────────┐
   │  LLM Provider 抽象    │      │  数据反馈闭环            │
   │  (GLM/OpenAI/...6家)  │      │  events→analytics→prompt│
   └──────────────────────┘      └─────────────────────────┘
```

**技术选型原则**：保留 SQLite + Chroma + FastAPI + 多厂商 LLM，**不堆砌** Kafka/Redis/ES/K8s/ClickHouse。重点在业务闭环与产品设计，而非技术栈罗列。

---

## 三、Multi-Agent Workflow（8 步链路）

数据在 `RunContext` 中真实传递，每个 Agent 有输入/输出/职责/状态/日志，并产出 `_decision`（"为什么"）归集到决策日志。

```
 1.TrendDetector    →  trends（从知识库检测热点趋势）
       ↓
 2.TopicSelector    →  topics（结合国家策略选题）
       ↓
 3.Retriever        →  evidences（RAG 检索 + query 改写）
       ↓
 4.OutlinePlanner   →  outline（按风格生成大纲）
       ↓
 5.Writer           →  article（按大纲+国家风格成文，强制引用）
       ↓
 6.FactChecker      →  fact_check（论断核查，独立于审核）
       ↓
 7.Reviewer         →  review（质量+合规裁决，revise 回退 Writer）
       ↓                  └─ reject → BadCase Center
 8.Publisher        →  publish（分发策略 + 灰度 + 埋点）
                          ↓
                    Content Center + Experiment 分桶
```

| Agent | 职责 | 输入 | 输出 | 决策日志示例 |
|-------|------|------|------|-------------|
| TrendDetector | 热点趋势检测 | signals, country | trends[] | "从60篇近7天新闻识别5个趋势" |
| TopicSelector | 国家策略选题 | trends, country | topics[] | "为CN选出5话题，调性=professional" |
| Retriever | RAG 检索 | topic | evidences[] | "召回12条证据，覆盖5来源" |
| OutlinePlanner | 大纲生成 | topic, evidences | outline[] | "生成5段大纲，引用8条证据" |
| Writer | 成稿 | outline, evidences | article | "按deep_dive/CN生成，引用8/12" |
| FactChecker | 事实核查 | article, evidences | fact_check | "核查6论断，3有据，置信0.95" |
| Reviewer | 质量合规审核 | article, fact_check | verdict | "裁决pass，质量4.0，合规0命中" |
| Publisher | 分发策略 | article, country | distribution | "分发CN的3平台，主推weibo" |

---

## 四、知识库设计

```
RSS 源(13家) → feedparser → trafilatura全文 → sha256(url)去重
     → 智能Chunk(标题→h1→h2→段落, 300-500token, overlap 60)
     → Embedding(MiniLM 384维) → Chroma + SQLite
```

**可信源**（credibility_level 1=权威官方 2=权威媒体）：
AI（OpenAI/Anthropic/DeepMind）、科技（TechCrunch/The Verge/Ars/MIT Tech Review）、新闻（BBC/Reuters/AP）、财经（Federal Reserve/Bloomberg）

**Chunk metadata**：doc_id/title/category/country/language/source/credibility/publish_time/section_path —— 支持 Retriever 多维过滤。

---

## 五、RAG 流程

```
 topic → LLM 改写 5 个 query
      → Chroma 向量检索(top_k=20) + metadata where 过滤
            (category / language / credibility_level_max / time_window)
      → RRF 融合 + 时间衰减
      → 证据集（含来源/可信度/国家/section_path）
      → Writer 强制引用 [ev_xxx]，FactChecker 核查论断
```

**关键约束**：LLM 不联网，所有事实来自知识库，100% 引用溯源。

---

## 六、数据库 ER 图（核心表）

```
 news_documents 1───* news_chunks          (RAG 知识库)
 tasks 1───* task_spans                    (任务 + Trace/可解释性)
 tasks 1───* contents 1───* content_events (内容 + 用户行为)
 prompts                                   (Prompt 版本管理)
 prompt_experiments 1───* experiment_assignments  (A/B 实验)
 bad_cases                                 (Bad Case 闭环)
```

**平台化升级字段**：
- `contents`：country / target_audience / platform / content_style / outline / distribution_plan / **decision_log**
- `content_events`：country / language / platform / finish_rate / like_count / share_count / negative_feedback
- `tasks`：**decision_log**（全流程决策日志，可解释性核心）

---

## 七、Prompt 生命周期

```
 draft → staging → production → archived
                 ↑ promote
                 │
 实验(treatment) ─→ A/B 分桶 ─→ 效果回流(eval_score = CTR*0.6 + 完读*0.4)
                 │
                 └→ 结论 → 新 production 版本
```

- 版本号自动 `v1.{n}.0`，不可变快照
- `ExperimentManager`：哈希分桶 + Z 检验
- **效果回流**：simulate 生成事件后，`update_eval_score` 把 CTR/完读率写回 `prompt.eval_score`

---

## 八、数据反馈闭环

```
 Publisher 发布 → Content 入库
      → simulate 生成用户事件(exposed/clicked/read/finished/like/share/negative)
      → analytics SQL 分析(漏斗/CTR/完读，按国家/语言/平台/Prompt 拆分)
      → 回流 prompt.eval_score → 指导 Prompt 迭代
      → Bad Case → root_cause → fix_action → 回归测试
```

**模拟数据符合产品逻辑**：高质量内容 CTR 更高；summary 风格完读率高于 deep_dive；bad_case 内容 CTR/完读显著下降；日本完读修正 +15%，巴西 -10%。

---

## 九、SQL 分析案例

```sql
-- 1. 不同国家阅读完成率（全球化效果）
SELECT country, AVG(finish_rate) FROM content_events
WHERE event_type='finished' GROUP BY country;

-- 2. 不同 Prompt 版本 CTR 对比（Prompt 效果）
SELECT c.prompt_writer_v,
       SUM(CASE WHEN e.event_type='clicked' THEN 1 ELSE 0 END)*1.0/
       SUM(CASE WHEN e.event_type='exposed' THEN 1 ELSE 0 END) AS ctr
FROM contents c JOIN content_events e ON c.content_id=e.content_id
GROUP BY c.prompt_writer_v;

-- 3. 漏斗转化
SELECT event_type, COUNT(*) FROM content_events GROUP BY event_type;
```

对应 API：`/api/analytics/by-country` · `/by-language` · `/by-platform` · `/prompt-roi` · `/funnel`

---

## 十、Bad Case 闭环

分类体系（F事实/H合规/G政治/C版权/Q质量/D延迟/U未知）→ 记录 → root_cause → fix_action → 回归测试集。

Reviewer reject 时自动写 `bad_cases`（含 affected_prompt_versions），Publisher 撤回机制 `retract()`。

---

## 十一、全球化内容策略

| 国家 | 语言 | 默认风格 | 受众 | 平台 | 调性 |
|------|------|---------|------|------|------|
| US | en | deep_dive | tech_professionals | twitter/linkedin | 客观深度 |
| JP | ja | summary | commuters | line/web_feed | 礼貌简洁 |
| KR | ko | trending | young_mobile | naver/instagram | 活泼 |
| IN | en | startup | startup_enthusiasts | whatsapp/linkedin | 励志 |
| BR | pt | football | sports_fans | instagram/whatsapp | 热情 |
| CN | zh | deep_dive | tech_professionals | weibo/wechat | 专业 |

体现"Agent 理解的是用户，而不仅仅是新闻"。

---

## 十二、技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| API | FastAPI + Uvicorn | 25+ 接口 + Swagger |
| ORM | SQLAlchemy 2.0 async + aiosqlite | SQLite，轻量可迁移 |
| 向量库 | ChromaDB 嵌入式 | 无独立服务 |
| LLM | 多厂商抽象 | GLM(当前)/OpenAI/Anthropic/DeepSeek/Kimi/Qwen |
| 采集 | feedparser + trafilatura | RSS + 全文提取 |
| 调度 | APScheduler | 每日增量采集 |

---

## 十三、快速开始

```bash
# 1. 配置 LLM（src/trendforge/.env）
TF_LLM_VENDOR=glm
TF_GLM_API_KEY=<your key>
TF_LLM_MODEL=glm-5.2

# 2. 初始化（建库 + 默认 Prompt + RSS 采集 ~300 篇）
python main.py seed

# 3. 启动 API
python main.py serve          # http://127.0.0.1:8000/docs

# 4. 端到端跑一篇（8 步 Workflow）
python main.py run

# 5. 模拟用户行为（数据反馈闭环）
python main.py simulate
```

---

## 十四、项目结构

```
ai-news-system/
├── src/trendforge/          # 生产代码（MVP 实现）
│   ├── agents/              # 8 个 Agent + base(RunContext/决策日志)
│   ├── workflow/            # 8 步编排器 + 状态机
│   ├── rag/                 # 采集/Chunk/向量/检索/调度
│   ├── prompts/             # 版本管理 + A/B 实验 + 渲染
│   ├── analytics/           # SQL 分析（全球化拆分）
│   ├── api/                 # FastAPI 25+ 接口
│   ├── simulator.py         # 数据反馈闭环模拟器
│   ├── config.py            # 国家策略 + 分发平台 + RSS 源
│   └── models.py            # 10+ 表（含 decision_log/全球化字段）
├── build/                   # 公网静态门户 + API 控制台
├── enterprise-spec/         # 企业级设计参考（TrendForge 团队规格，纯参考/愿景，非 MVP 范围）
│   ├── docs/                # 12 篇设计稿（PRD/Agent/RAG/Workflow/合规…）
│   ├── architecture/        # 系统架构图
│   ├── dashboard/           # 数据看板原型
│   ├── ui/                  # 控制台/管道规格/设计系统
│   └── demo/                # TrendForge 可运行 Demo
└── README.md
```

---

## 十五、产品迭代记录

| 版本 | 迭代内容 |
|------|---------|
| v1 | Demo：5 Agent + 模拟 LLM + 设计文档 |
| v2 | 生产级：真实 LLM + Chroma + SQLite + FastAPI |
| v3 | 多厂商 LLM（6 家）+ 公网部署套件 |
| v4 | 知识库升级：RSS 采集 + 智能 Chunk + metadata 过滤 + 真 RAG + 每日增量 |
| **v5** | **平台化：8-Agent + 决策日志 + 业务闭环 + 数据反馈 + 全球化策略 + Prompt 效果回流** |

---

## 十六、求职定位

这是一个面向 **AI 产品经理 / AI 应用工程师** 求职的**个人作品集**项目（MVP），展示如何把传统内容生产流程抽象为 AI 可持续执行、持续优化的系统：

- **业务闭环设计**（不是技术 Demo）：热点→成稿→核查→审核→分发→用户行为回流→Prompt 效果
- **Multi-Agent 协作 + 可解释性**（决策日志 `_decision`）
- **Prompt 生命周期与 A/B 实验**（版本快照 + Z 检验 + 效果回流）
- **数据驱动的全球化内容策略**（7 国风格/平台/调性）
- **SQL 数据分析能力**（漏斗/CTR/完读/ROI 按国家拆分）

**仓库结构说明（给面试官/协作者）**：根目录即**可运行的个人 MVP**（包名 `trendforge`，对外统一名 **TrendForge**）；`enterprise-spec/` 是同一产品的**企业级设计参考**（团队规格、集群/多租户/合规引擎等更激进形态），仅作架构深度展示，**不在个人 MVP 交付范围内**，请勿照其过度实现。

**MVP 边界（建议面试强调）**：单进程可跑（SQLite + Chroma + FastAPI + 多厂商 LLM），优先把"能跑通的闭环"和"真实前端控制台"讲清楚；企业级扩展（向量集群、工作流引擎、多租户、全量合规）留作演进路线。
