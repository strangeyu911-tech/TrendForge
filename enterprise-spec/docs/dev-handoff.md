# TrendForge · 开发对接文档（前端 / 后端 / 数据库 / Agent 契约）

> 文档目的：把"设计原型 + 设计标注切图"转换成**开发团队可直接开工**的对接基线。
> 配套产物：`ui/trendforge-console.html`（可交互原型）、`ui/trendforge-pipeline-spec.html`（生产流水线开发级标注切图）、`ui/DESIGN_SYSTEM.md`（设计系统）。
>
> 本文所有结论均对照现有代码核对：`src/trendforge/{models,schemas,db}.py`、`src/trendforge/api/main.py`（37 端点）、`src/trendforge/workflow/orchestrator.py`（8 步 Agent 链）。

---

## 0. 当前状态与就绪度（先对齐预期）

| 层 | 现状 | 结论 |
|---|---|---|
| 设计 | 6 视图可交互原型 + 流水线标注切图 + Token 体系 | ✅ **可交付前端** |
| 前端代码 | `ui/` 是单文件静态原型（内联 CSS/JS、假数据、无框架） | ❌ 需重写为真应用 |
| 后端 | FastAPI + 异步 SQLAlchemy + 8-Agent 编排器 + 37 端点 + 12 表 | ✅ 架构领先 UI，可并行 |
| 鉴权 | **无** `/api/auth/*`、无 `current_user` 依赖 | ❌ 必补 |
| 多租户 | 无 `users`/`teams` 表、`team_id` 字段 | ❌ 必补（团队版已出现在 UI） |
| 数据库 | 异步引擎 ✅，但用 SQLite + 手写 `_migrate`（仅 SQLite，脆弱） | ❌ 换 Postgres + Alembic |
| Agent 实现 | orchestrator 在，但 `tasks/` 仅占位 | ⚠️ 需接真实 LLM/RAG |

**一句话**：设计已可交付；后端有骨架但缺「鉴权 / 多租户 / 迁移 / Agent 真实实现」四块；前端需从零搭建真应用。下面给可落地的方案。

---

## 1. 前端框架与构建方案 + 组件拆分清单

### 1.1 推荐：**React 18 + Vite + TypeScript**

选 React 而非 Vue 的理由（针对本项目"数据密集型运营后台"）：
- 生态最契合：数据看板用 **TanStack Query（服务端状态）+ Recharts/visx（图表）**、组件库可用 **shadcn/ui 思路自建**（与本设计 Token 体系天然契合）。
- 团队招聘与社区资料最丰富，A-B、实验台、审核队列这类复杂交互的状态管理案例多。
- 若团队 Vue 经验更强也可换 Vue3 + Vite + Pinia + Element Plus，本设计 Token 同样能套；**框架不是强约束，强约束是下面的"Token 工程化"和"接口契约"**。

**构建与工程栈建议**
```
框架      React 18 + TypeScript
构建      Vite 5（HMR、极快冷启）
路由      React Router v6（6 视图 = 6 路由，侧栏导航）
服务端态  TanStack Query v5（接管所有 /api 请求、缓存、重试、轮询）
本地态    Zustand（仅放 theme / 当前用户 / 抽屉开关等 UI 态）
样式      CSS Modules + 设计 Token（见下）；不引 UI 框架覆盖 Token
图表       Recharts（替代原型里的 Chart.js CDN，便于主题联动）
Mock       MSW（开发期用 mock 对齐字段，联调一键切真实 /api）
测试      Vitest + Testing Library；关键组件加视觉回归（Chromatic/Playwright）
```

### 1.2 设计 Token 工程化（关键，决定一致性）
把原型里的 CSS 变量抽成**单一可信源**，深浅主题用 `data-theme` 切换（与现有原型一致）：

```
src/design/tokens.css      ← :root 与 [data-theme="dark"] 两套变量（颜色/间距/圆角/阴影/动效）
src/design/tokens.ts       ← 同值导出给 TS（颜色计算、图表主题）
src/design/theme.ts        ← setTheme(t) 写 document.documentElement.dataset.theme
```

> 原型里 `--brand:#FF7A45`、Agent 角色色（Planner 橙 / Research 青 / Writer 金 / Reviewer 绿 / Publisher 蓝）已在 CSS 中，直接迁移即可。

### 1.3 组件拆分清单（映射 6 视图）

**布局层（AppShell，全站复用）**
- `AppShell` / `Sidebar`（6 导航项，当前项高亮）/ `TopBar`（搜索触发、通知铃、头像菜单、主题切换）
- `SearchCommandPalette`（⌘K 命令面板：**仅 ESC/选中/✕ 关闭**，点外面不关）/ `NotifyPanel` / `UserMenu`

**基础组件（Design System）**
- `Card` / `Button`（primary/secondary/ghost）/ `Chip`（筛选）/ `Drawer`（右抽屉）/ `Modal` / `Toast`
- `StatusDot`（pending/running/succeeded/failed/human_pending）/ `Badge` / `Table` / `EmptyState` / `Skeleton`
- `SegmentedControl`（7日/30日切换）/ `Kbd`

**视图组件（每个视图一个文件夹）**
| 视图 | 关键组件 |
|---|---|
| `overview/` | `StatCards` · `NewsSourceChart` · `FunnelChart` · `TrendSparkline`（均接 `/api/analytics/*`） |
| `pipeline/` | `PipelineGraph`（5 节点，点击开 `AgentDrawer`/`TaskDrawer`，节点含 暂停/详情 工具）/ `TaskList`（chip 筛选）/ `EventFeed`（实时推送，play/pause 受 `feedPaused` 控制）/ `LivePulse` |
| `review/` | `ReviewQueue` · `ReviewDetail` · `ActionBar`（通过/回退/转人工，键盘 ↑↓ 切换 pending）/ `DecisionLog` |
| `prompt/` | `PromptTable` · `ExpDrawer` · `NewExpModal` · `RadarChart` · `ABTable`（7日/30日切换） |
| `badcase/` | `BadCaseTable`（severity chip 筛选）/ `BCTimeline`（闭环）/ `BCDrawer` |
| `design/` | `TokenSwatches`（点击复制 hex）/ `TypeScale` / `ColorRoles` |

> 组件与 Token 命名请严格对齐 `ui/DESIGN_SYSTEM.md` 与 `ui/trendforge-pipeline-spec.html` 的标注，避免自主研发漂移。

---

## 2. 鉴权与 RBAC 模型

### 2.1 登录方式
- **主登录**：邮箱 + 密码。`password` 用 **argon2/bcrypt** 哈希；签发 **access（15min）+ refresh（7d，轮换）**。
- **Web 端令牌承载**：`access` 放 **httpOnly + Secure + SameSite=Lax** Cookie，`refresh` 独立 Cookie；CSRF 用 double-submit token。**不**把 JWT 塞进 localStorage（防 XSS 窃取）。
- **团队版 SSO**：OIDC（首选）/ SAML，对接企业 IdP；登录后按 `email domain` 或 IdP `groups` 落 `team_memberships`。

**新增端点（当前缺失，必须补）**
```
POST /api/auth/login            {email,password}            → {access,refresh,user}
POST /api/auth/refresh          (cookie refresh)            → {access}
POST /api/auth/logout           → 清 cookie
GET  /api/auth/me               → 当前用户 + 角色 + team
GET  /api/auth/sso/oidc/start   → 302 IdP
POST /api/auth/sso/oidc/callback→ {access,refresh,user}
```

### 2.2 多租户（团队版）——当前**未建模，必须补**
UI 用户菜单已显示"已开通团队版"，但 `models.py` 的 12 张表**没有 `team_id`，也没有 `users`/`teams` 表**。需新增并迁移：
```
users(id, email UNIQUE, name, password_hash, status, created_at)
teams(id, name, plan, owner_id, created_at)
team_memberships(user_id, team_id, role, created_at)   -- 复合主键
```
- 所有业务表加 `team_id`（第一阶段迁移，见 §3.3），**所有查询默认带 `WHERE team_id=?`**（在 `get_db` 或 repo 层统一注入，避免漏写）。
- 个人版：`team_id` 指向该用户私有 team。

### 2.3 角色与 RBAC
- **角色**：`owner` > `admin` > `operator`（内容运营）> `viewer`。
- **后端落地**：FastAPI 依赖 `require_role(*roles)`，包裹需鉴权端点；缺失 `current_user` 依赖（`get_current_user` 从 Cookie 解析 access）。
- **前端**：按角色隐藏/禁用按钮（如 Prompt/实验仅 `admin`），但**权限以后端为准**，前端只是体验优化。

**权限矩阵（端点 → 最低角色）**
| 端点分组 | 角色 |
|---|---|
| `/api/health`, `/api/auth/*` | 公开 / 已登录 |
| `/api/analytics/*`（看板） | viewer+ |
| `/api/content/*`, `/api/tasks/*`, `/api/contents/*` | operator+ |
| `/api/rag/*`（含 ingest/collect） | operator+（collect 限 admin） |
| `/api/prompts/*`（含 promote 上线） | admin |
| `/api/experiments/*`（含创建/结论） | admin |
| `/api/bad-cases`（resolve/wontfix 写） | operator+（assign 限 admin） |

> 注意：`main.py` 当前 37 端点**全部无鉴权**，上线前需逐端点补 `Depends(get_current_user)` + `require_role`。

---

## 3. 生产数据库与 Alembic 迁移

### 3.1 现状
- ✅ 已是**异步引擎**（`create_async_engine` + `async_sessionmaker`），方向正确。
- ❌ 用 **SQLite**（`settings.database_url` 以 `sqlite` 开头）+ 手写 `_migrate()`（PRAGMA/ALTER，仅 SQLite，脆弱、无版本、无回滚）。

### 3.2 推荐方案
1. **驱动切 Postgres**：`DATABASE_URL=postgresql+asyncpg://user:pwd@host:5432/trendforge`。
   `db.py` 里 `connect_args` 的 `timeout/check_same_thread` 仅 SQLite 用，Postgres 下走空 dict（现有代码已处理，保留即可）。
2. **引入 Alembic**（替换手写 `_migrate`）：
   - `alembic.ini` 指向 `DATABASE_URL`；
   - `migrations/env.py` 用**异步** `run_async_migrations`（async_engine）；
   - 生成初始迁移：`alembic revision --autogenerate -m "init schema"`（基于现有 `models.py` 12 张表）。
3. **退役 `init_db` 的手写迁移**：保留 `Base.metadata.create_all` 仅用于测试，生产只用 `alembic upgrade head`。
4. **连接池**：`create_async_engine(..., pool_size=20, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)`。
5. **索引**（models 已含大量单列索引，补复合索引加速看板）：
   - `tasks(status, created_at)`、`tasks(topic_id)`
   - `contents(category, published_at DESC, country)`、`contents(is_bad_case, created_at)`
   - `content_events(content_id, event_type, event_ts)`
   - `news_documents(url)` 唯一已建、`news_chunks(doc_id, category)`

**迁移工作流**
```bash
# 本地起 PG（docker）
docker run -d --name tf-pg -e POSTGRES_DB=trendforge -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
# 初始迁移
alembic revision --autogenerate -m "init schema"
alembic upgrade head
# 后续每次改 models.py
alembic revision --autogenerate -m "add team_id"
alembic upgrade head
```

### 3.3 与 RBAC 配套的第一阶段迁移
- 新增 `users` / `teams` / `team_memberships` 三张表；
- 业务表（`tasks`/`contents`/`content_events`/`bad_cases`/`prompts`/`prompt_experiments`/`news_documents` 等）统一加 `team_id VARCHAR(64) NOT NULL DEFAULT '<personal>'` 并建索引；
- 历史数据回填 `team_id`（单租户期全部归到默认 team）。

---

## 4. Agent 契约与 API 规范

### 4.1 UI 5 节点 ↔ 后端 8 Agent 映射
UI 设计只显 5 个流水线节点（Planner/Research/Writer/Reviewer/Publisher），后端是 8 步链。映射如下，前后端对齐用：

| UI 节点 | 后端 Agent（orchestrator） | 颜色（设计 Token） |
|---|---|---|
| **Planner** | `TrendDetectorAgent` + `TopicSelectorAgent` + `OutlinePlannerAgent` | 橙 `--brand` |
| **Research** | `ResearchAgent`（retriever，接 RAG） | 青 `--a-research` |
| **Writer** | `WriterAgent` | 金 `--a-writer` |
| **Reviewer** | `FactCheckerAgent` + `ReviewerAgent` | 绿 `--a-reviewer` |
| **Publisher** | `PublisherAgent` | 蓝 `--a-publisher` |

> 编排器每个 Agent 产出 `_decision`（"为什么"），归集到 `ctx.decision_log` → 对应 UI 的"决策日志/可解释性"。

### 4.2 每个节点的输入 / 输出（直接复用 `schemas.py` 现有类型）

| 节点 | 输入（schema） | 输出（schema） | 落库 |
|---|---|---|---|
| Planner | `RunTopicRequest` / `RunPipelineRequest.signals` | `Topic` + `outline: list` | `tasks.topic_title`, `contents.outline` |
| Research | `{topic}` / `Topic` | `list[Evidence]`（`Evidence`: content/source_url/credibility/is_conflict） | `contents.evidence_count`, `news_chunks` |
| Writer | `{topic, evidences, outline, prompt_writer_v}` | `Article`（`ArticleBlock[]`: type/text/citations） | `contents.body`, `contents.word_count` |
| Reviewer | `{article, evidences}` | `ReviewResult`（verdict / `QualityScores` / `FactCheck` / `Compliance` / `revision_suggestions` / `bad_case_flag`） | `contents.review_verdict`, `quality_overall`, `fact_consistency`, `bad_cases` |
| Publisher | `{article, citations, prompt_version}` | `{channels, gray_ratio, distribution_plan}` | `contents.channels`, `contents.gray_ratio`, `contents.distribution_plan` |

> `schemas.py` 已定义上述全部类型；**勿另起一套**，前端联调直接按这些字段名对接。

### 4.3 统一 API 响应信封（当前端点返回裸 dict，**需改造**）
所有 `/api` 响应统一包一层，前端用 `data` 取数：
```json
{ "code": "SUCCESS", "message": "", "data": { }, "request_id": "req_xxx", "ts": 1719500000 }
```
分页：
```json
{ "code":"SUCCESS", "data": { "items":[...], "total":120, "page":1, "page_size":20 } }
```
**改造方式**：加 FastAPI 依赖/中间件，把 `dict` 返回值自动包成信封；错误用 `HTTPException` 子类带 `app_code`（见 §4.4）。原型里前端用假数组，真实联调后由 TanStack Query 解 `data`。

### 4.4 错误码表（app_code + HTTP）
| app_code | HTTP | 含义 | 前端处理 |
|---|---|---|---|
| `SUCCESS` | 200 | 成功 | — |
| `VALIDATION_ERROR` | 400 | 入参校验失败（含 Pydantic 422 归一） | 字段级红框提示 |
| `AUTH_REQUIRED` | 401 | 未登录 / access 失效 | 跳登录 |
| `TOKEN_EXPIRED` | 401 | refresh 也过期 | 跳登录 |
| `TOKEN_INVALID` | 401 | 签名/格式错 | 跳登录 |
| `FORBIDDEN` | 403 | 角色不足（RBAC） | 提示无权限 |
| `NOT_FOUND` | 404 | 资源不存在 | 空态/提示 |
| `CONFLICT` | 409 | 版本/实验已存在 | 提示冲突 |
| `RATE_LIMITED` | 429 | 限流（LLM/接口） | 退避重试 |
| `AGENT_ERROR` | 500 | 某 Agent 执行失败 | 任务标 failed，看决策日志 |
| `AGENT_TIMEOUT` | 504 | Agent 超时 | 任务标 degraded，可重试 |
| `RAG_ERROR` | 500 | 检索/向量库异常 | 提示，_writer 降级 |
| `PROMPT_ERROR` | 500 | Prompt 渲染/版本错 | 提示联系 admin |
| `EXPERIMENT_ERROR` | 500 | 实验分配/统计错 | 提示 |
| `LLM_VENDOR_DOWN` | 503 | 供应商不可用 | 提示稍后重试 |
| `INTERNAL_ERROR` | 500 | 未预期 | 上报 + toast |

### 4.5 现有主要端点 → 信封/鉴权改造对照
| 端点 | 鉴权 | 返回 `data` 形状要点 |
|---|---|---|
| `POST /api/content/run-topic` | operator | `TaskResponse`（task_id, status, article?） |
| `POST /api/content/run-pipeline` | operator | `{task_ids:[...]}` |
| `GET /api/tasks` | operator | `{items: TaskResponse[], total}` |
| `GET /api/tasks/{id}/trace` | operator | `{spans: TaskSpan[], decision_log}` |
| `GET /api/content/{id}` / `/contents` | viewer | `Content` 行 |
| `GET /api/rag/search` | operator | `{items: Evidence[]}` |
| `POST /api/prompts` / `GET /api/prompts/{id}` / `promote` | admin | `Prompt` 行 / `{ok}` |
| `POST /api/experiments` / `report` | admin | `ExperimentCreateRequest`/`ABTestReport` |
| `GET /api/analytics/*` | viewer | 对应 `MetricsResponse`/`ABTestReport`/漏斗数组 |
| `POST /api/events/simulate` | admin | `{inserted}` |

> demo 路由（`/search` `/generate` `/workflow` `/stats`）仅本地演示，不进生产。

---

## 5. 前端联调接口清单（按视图，开发直接照此接）

- **运营总览**：`/api/analytics/funnel` · `/api/analytics/ctr-by-category` · `/api/analytics/production` · `/api/analytics/cost` · `/api/analytics/by-country`
- **生产流水线**：`/api/content/run-topic` · `/api/tasks` · `/api/tasks/{id}/trace` · `/api/content/{id}` · 事件流先用前端定时器轮询 `/api/contents`（真实 WS 另议）
- **审核工作台**：`/api/contents?is_bad_case=false` 取待审 · `ReviewResult` 字段驱动通过/回退/转人工 · `PATCH /api/contents/{id}/review`（**需新增**，写 verdict+rounds）
- **Prompt/实验台**：`/api/prompts/*` · `/api/experiments/*` · `/api/analytics/prompt-effect` · `/api/analytics/prompt-roi`
- **Bad Case**：`/api/analytics/bad-cases` · `bad_cases` 表字段 · 闭环写 `PATCH /api/bad-cases/{id}`（**需新增**）
- **设计系统**：无接口，纯 Token 静态页

---

## 6. 交付物与后续行动清单（checklist）

**已交付（设计侧）**
- [x] `ui/trendforge-console.html` — 6 视图可交互原型
- [x] `ui/trendforge-pipeline-spec.html` — 生产流水线开发级标注切图
- [x] `ui/DESIGN_SYSTEM.md` — 设计系统文档

**开发开工前必须锁定的 4 件事**
- [ ] 前端框架确认（本文默认 React+Vite+TS，可改 Vue）
- [ ] 鉴权模型确认（Cookie JWT + OIDC SSO；新增 `users/teams` 表）
- [ ] 生产库确认（Postgres + asyncpg + Alembic；加 `team_id`）
- [ ] Agent 契约确认（§4 已对齐 `schemas.py`，前后端按此字段联调）

**后端待补（优先级排序）**
- [ ] 新增 `/api/auth/*` + `get_current_user` + `require_role`，逐端点补鉴权
- [ ] 新增 `users/teams/team_memberships` 表 + 业务表 `team_id` 迁移
- [ ] Alembic 初始化迁移，退役手写 `_migrate`
- [ ] `tasks/` 真实 Agent 实现（接 LLM + RAG + Prompt 版本）
- [ ] 新增 `PATCH /api/contents/{id}/review`、`PATCH /api/bad-cases/{id}` 等写接口
- [ ] 统一响应信封 + 错误码中间件

**前端待建**
- [ ] 脚手架（Vite+React+TS）+ Token 工程化 + TanStack Query
- [ ] 按 §1.3 组件清单实现，MSW mock → 真实 `/api`
- [ ] 鉴权流（登录/刷新/CSRF）+ 角色化 UI

---
*文档生成：UI Designer（像素君）· 2026-07-28 · 对照 `src/trendforge` 当前代码核对*
