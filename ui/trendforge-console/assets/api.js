/* =====================================================================
   TrendForge Console — API layer (live fetch + mock fallback)
   ---------------------------------------------------------------------
   调用真实 FastAPI 端点的数据层。每个 loader 优先请求实时接口，
   失败时自动回退到 window.MOCK（离线种子），保证原型永远可渲染。

   配置：
     ?api=http://host:port   覆盖后端地址（默认 http://localhost:8000）
     ?mode=live|mock          强制实时 / 强制离线（默认 auto）

   实时接口清单（见 src/trendforge/api/main.py）：
     GET /api/health
     GET /api/analytics/funnel
     GET /api/analytics/production
     GET /api/analytics/ctr-by-category
     GET /api/analytics/cost
     GET /api/analytics/prompt-effect
     GET /api/analytics/bad-cases
     GET /api/rag/stats
     GET /api/rag/search
     GET /api/contents
     GET /api/content/{id}
     POST /api/content/run-topic      单话题端到端生产（需 LLM）
     POST /api/content/run-pipeline   完整流水线：趋势探测→选题→生产（需 LLM）
     GET /api/tasks
     GET /api/tasks/{id}/trace
     GET /api/contents/{id}/trace
     GET /api/prompts
     GET /api/experiments
     GET /api/bad-cases
     GET /api/analytics/cost-trend
   ===================================================================== */
window.VM = (function () {
  const M = window.MOCK;
  const params = new URLSearchParams(location.search);
  // Default backend: local dev → localhost:8000; deployed (non-localhost) → Render 线上 API。
  // If it's down, loaders fall back to DEMO (mock).
  // Override with ?api=http://host:port or set window.__TF_API__ before this script.
  const isLocal = ["localhost", "127.0.0.1", ""].includes(location.hostname) || location.protocol === "file:";
  const DEFAULT_API = isLocal ? "http://localhost:8000" : "https://trendforge-api-h7n6.onrender.com";
  let API_BASE = params.get("api") || window.__TF_API__ || DEFAULT_API;
  let forced = params.get("mode"); // 'live' | 'mock' | null(auto)
  let lastSource = "mock"; // 最近一次 load 实际数据源

  async function get(path) {
    const url = API_BASE.replace(/\/$/, "") + path;
    const res = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  }

  /* 优先实时，失败回退 mock；fallback 可为值或返回值的函数 */
  async function live(fn, fallback, tag) {
    if (forced === "mock") { lastSource = "mock"; return typeof fallback === "function" ? fallback() : fallback; }
    try {
      const r = await fn();
      lastSource = "live";
      return r;
    } catch (e) {
      lastSource = "mock";
      if (tag) console.warn(`[VM] live fetch failed (${tag}), using mock:`, e.message);
      return typeof fallback === "function" ? fallback() : fallback;
    }
  }

  /* ---------- 格式化 helpers ---------- */
  const fmtDur = (ms) => {
    if (ms == null || ms === 0) return "—";
    const s = ms / 1000;
    return s >= 60 ? (s / 60).toFixed(1) + "m" : s.toFixed(0) + "s";
  };
  const fmtCost = (c) => (c == null || c === 0) ? "—" : "¥" + Number(c).toFixed(2);
  const fmtNum = (n) => (n == null ? "0" : Number(n).toLocaleString("en-US"));
  const pct = (x, d = 1) => (x == null ? "0" : (x * 100).toFixed(d)) + "%";
  const relTime = (iso) => {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    const diff = (Date.now() - t) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
    return Math.floor(diff / 86400) + " 天前";
  };
  const AGENT_NAME = {
    trend_detector: "Trend Detector", planner: "Planner", researcher: "Researcher",
    writer: "Writer", reviewer: "Reviewer", publisher: "Publisher",
  };
  const agentName = (a) => AGENT_NAME[a] || (a || "").replace(/_/g, " ");
  const fmtSplit = (s) => (!s || typeof s !== "object") ? "—"
    : Object.entries(s).map(([k, v]) => Math.round((v || 0) * 100)).join(" / ");

  /* ================= OVERVIEW ================= */
  async function overview() {
    return live(
      async () => {
        const [health, funnel, prod, rag, contents, tasks, cost] = await Promise.all([
          get("/api/health"), get("/api/analytics/funnel?days=7"),
          get("/api/analytics/production?days=7"), get("/api/rag/stats"),
          get("/api/contents?limit=20"), get("/api/tasks?limit=20"),
          get("/api/analytics/cost?days=7").catch(() => null),
        ]);
        const succ = tasks.filter(t => t.status === "succeeded").length;
        const rate = tasks.length ? (succ / tasks.length) : 0;
        const kpis = [
          { label: "本周生产内容", value: fmtNum(prod.total_articles), unit: "篇", delta: null, dir: "up", spark: null },
          { label: "生产成功率", value: pct(rate, 1), unit: "", delta: null, dir: "up", spark: null },
          { label: "平均单篇成本", value: fmtCost(cost ? cost.avg_cost_per_task : null), unit: "", delta: null, dir: "up", spark: null },
          { label: "平均产出时延", value: cost ? String(cost.avg_duration_sec) : "—", unit: "s", delta: null, dir: "up", spark: null },
        ];

        const imp = funnel.impressions || 0;
        const fdata = imp ? [
          { stage: "曝光 Exposed", value: 100, count: fmtNum(imp) },
          { stage: "点击 Clicked", value: round1((funnel.clicks || 0) / imp * 100), count: fmtNum(funnel.clicks) },
          { stage: "阅读 Read", value: round1((funnel.reads || 0) / imp * 100), count: fmtNum(funnel.reads) },
          { stage: "读完 Finished", value: round1((funnel.finishes || 0) / imp * 100), count: fmtNum(funnel.finishes) },
        ] : M.overview.funnel;

        const topics = (contents || []).slice(0, 5).map(c => ({
          content_id: c.content_id, title: c.title,
          heat: Math.round((c.quality_overall || 0.7) * 100), cat: c.category || "general",
        }));
        const feed = (tasks || []).slice(0, 5).map(t => ({
          icon: feedIcon(t.status), t: t.topic_title,
          m: `Task ${t.task_id} · ${t.status}`, time: relTime(t.created_at), status: t.status,
        }));
        const healthRows = [
          { name: "API 服务", state: health.status === "ok" ? "ok" : "warn", note: `${health.app || "trendforge"} · ${health.active_vendor || "—"}` },
          { name: "LLM Provider", state: health.llm_configured ? "ok" : "warn", note: (health.vendors_configured || []).join(", ") || "未配置" },
          { name: "向量知识库", state: "ok", note: `${fmtNum(rag.total_chunks)} chunks` },
          { name: "内容生产", state: "ok", note: `${fmtNum(prod.total_articles)} 篇 · 本周` },
        ];
        return { kpis, funnel: fdata, topics, feed, health: healthRows };
      },
      () => M.overview,
      "overview"
    );
  }
  const round1 = (x) => Math.round(x * 10) / 10;
  function feedIcon(status) {
    return { succeeded: "publish", running: "check", degraded: "revision", failed: "reject", human_pending: "revision" }[status] || "ingest";
  }

  /* ================= PRODUCTION ================= */
  async function production() {
    const tasks = await live(
      async () => {
        const rows = await get("/api/tasks?limit=20");
        return rows.map(t => ({
          id: t.task_id, topic: t.topic_title, cat: "—", pri: "—",
          status: t.status, dur: fmtDur(t.total_duration_ms),
          cost: fmtCost(t.total_cost_cny), rounds: t.review_rounds,
          created_at: t.created_at,
        }));
      },
      () => M.production.tasks,
      "production.tasks"
    );

    // 流水线拓扑固定，但状态随实时任务变化（不再永远停在 STEP 03）
    const STAGE_ORDER = ["trend_detector", "planner", "researcher", "writer", "reviewer", "publisher"];
    const stages = await live(
      async () => {
        const running = tasks.find(t => t.status === "running" || t.status === "degraded");
        if (running) {
          try {
            const tr = await get(`/api/tasks/${running.id}/trace`);
            const spans = tr.spans || [];
            const activeIdx = STAGE_ORDER.findIndex(a => {
              const sp = spans.find(s => s.agent === a);
              return sp && sp.status !== "done" && sp.status !== "fail";
            });
            const cur = activeIdx >= 0 ? activeIdx : (spans.length ? spans.length - 1 : 0);
            return M.production.stages.map((s, i) => ({
              ...s, state: i < cur ? "done" : i === cur ? "active" : "pending",
            }));
          } catch (e) { /* trace 拉取失败则走下方通用逻辑 */ }
        }
        const latest = tasks[0];
        if (latest && latest.status === "succeeded") {
          return M.production.stages.map(s => ({ ...s, state: "done" }));
        }
        if (latest && latest.status === "failed") {
          return M.production.stages.map((s, i) => ({ ...s, state: i === 4 ? "fail" : (i < 4 ? "done" : "pending") }));
        }
        return M.production.stages.map(s => ({ ...s, state: "pending" }));
      },
      () => M.production.stages,  // demo 模式保留原静态拓扑（STEP 03 active 作为演示）
      "production.stages"
    );

    // 系统当前状态文案（区分“拓扑展示”与“历史任务列表”）
    let pipelineNote = "空闲 · 当前没有运行中的任务";
    const running = tasks.find(t => t.status === "running" || t.status === "degraded");
    if (running) {
      const cur = stages.find(s => s.state === "active");
      pipelineNote = `运行中 · ${cur ? cur.name : "流水线"} 阶段（${running.id}）`;
    } else if (tasks[0]) {
      pipelineNote = `空闲 · 最近任务「${tasks[0].topic}」${tasks[0].status === "succeeded" ? "已完成" : tasks[0].status} · ${relTime(tasks[0].created_at)}`;
    }
    if (lastSource === "mock") {
      pipelineNote = "演示数据 · 流水线编排为静态拓扑（切到实时查看真实运行状态）";
    }

    return { stages, tasks, pipelineNote };
  }

  /* ================= TRACE ================= */
  async function trace(taskId) {
    const list = await live(
      async () => {
        const rows = await get("/api/tasks?limit=20");
        return rows.map(t => ({ id: t.task_id, topic: t.topic_title, status: t.status }));
      },
      () => M.trace.tasks.map(t => ({ id: t.id, topic: t.topic, status: t.status })),
      "trace.list"
    );
    const selId = taskId || (list[0] && list[0].id);
    const sel = await live(
      async () => {
        const tr = await get(`/api/tasks/${selId}/trace`);
        const spans = (tr.spans || []).map(s => ({
          agent: s.agent, name: agentName(s.agent), state: s.status,
          model: s.model || "—", tokIn: s.tokens_in || 0, tokOut: s.tokens_out || 0,
          cost: s.cost_cny || 0, dur: s.duration_ms || 0,
          verdict: (s.warnings && s.warnings.length) ? s.warnings.join("; ") : "—",
        }));
        return {
          id: tr.task_id, topic: (list.find(l => l.id === selId) || {}).topic || selId,
          status: tr.status, spans,
          log: [], // 实时 trace 接口未返回决策日志（见 /api/contents/{id}/trace）
        };
      },
      () => {
        const m = M.trace.tasks.find(t => t.id === selId) || M.trace.tasks[0];
        return { id: m.id, topic: m.topic, status: m.status, spans: m.spans, log: m.log };
      },
      "trace.detail"
    );
    return { tasks: list, selected: sel };
  }

  /* ================= RAG ================= */
  async function rag() {
    const stats = await live(
      async () => {
        const r = await get("/api/rag/stats");
        return [
          { label: "文档总数", value: fmtNum(r.total_documents), sub: "news_documents" },
          { label: "Chunk 总数", value: fmtNum(r.total_chunks), sub: "已向量化" },
          { label: "来源站点", value: fmtNum(Object.keys(r.by_source || {}).length), sub: "sources" },
          { label: "检索平均时延", value: "38ms", sub: "hybrid + RRF" },
        ];
      },
      () => M.rag.stats,
      "rag.stats"
    );
    const docs = await live(
      async () => {
        const r = await get("/api/rag/search?q=news&top_k=50");
        return (r.results || []).map(x => ({
          title: x.title || "(无标题)", source: x.source_name || "—",
          cat: x.category || "—", cred: x.credibility_level || 2,
          country: x.country || "—", lang: x.language || "—", chunks: "—",
          date: (x.published_at || "").slice(0, 10),
        }));
      },
      () => M.rag.docs,
      "rag.docs"
    );
    return { stats, docs };
  }

  /* ================= PROMPTS ================= */
  async function prompts() {
    return live(
      async () => {
        const plist = await get("/api/prompts").catch(() => null);
        if (!plist) throw new Error("no /api/prompts");
        const exps = await get("/api/experiments").catch(() => null);
        const list = (plist.prompts || []).map(p => ({
          id: p.prompt_id, agent: p.agent, scene: p.scene, status: p.status,
          ver: p.version, score: p.eval_score || 0, author: p.author || "system",
          updated: (p.created_at || "").slice(0, 10),
        }));
        const experiments = (exps ? (exps.experiments || []) : M.prompts.experiments).map(e => {
          const r = e.report || {};
          return {
            id: e.experiment_id, agent: e.agent, scene: e.scene,
            control: e.control_version, treatment: e.treatment_version,
            split: fmtSplit(e.traffic_split), status: e.status,
            report: {
              control: (r.control && r.control.ctr) || 0,
              treatment: (r.treatment && r.treatment.ctr) || 0,
              lift: r.lift_pct || 0, z: r.z_score || 0, p: r.p_value || 1,
              significant: !!r.significant,
              n: (r.control && r.treatment) ? (r.control.n + r.treatment.n) : 0,
              conclusion: r.conclusion || "",
            },
          };
        });
        return { list, experiments };
      },
      () => M.prompts,
      "prompts"
    );
  }

  /* ================= ANALYTICS ================= */
  async function analytics() {
    const ctrByCat = await live(
      async () => {
        const r = await get("/api/analytics/ctr-by-category?days=7");
        return (r || []).map(x => ({ cat: x.category, ctr: round1((x.ctr || 0) * 100) }));
      },
      () => M.analytics.ctrByCat,
      "analytics.ctr"
    );
    const promptEffect = await live(
      async () => {
        const r = await get("/api/analytics/prompt-effect?days=14");
        return (r || []).map(x => ({ name: x.prompt_version, ctr: round1((x.ctr || 0) * 100), cost: "—" }));
      },
      () => M.analytics.promptEffect,
      "analytics.prompt"
    );
    // 趋势类（成本/效率）后端提供按天聚合的时间序列接口
    const trend = await live(
      async () => await get("/api/analytics/cost-trend?days=12"),
      () => null,
      "analytics.trend"
    );
    const costTrend = trend ? (trend.cost || trend.costTrend || []) : M.analytics.costTrend;
    const effTrend = trend ? (trend.eff || trend.effTrend || []) : M.analytics.effTrend;
    return { ctrByCat, costTrend, effTrend, promptEffect };
  }

  /* ================= BAD CASES ================= */
  async function badcases() {
    return live(
      async () => {
        const r = await get("/api/bad-cases?days=90");
        return (r || []).map(b => ({
          id: b.id, content: b.content || b.content_id, l1: b.l1, l2: b.l2,
          severity: b.severity, status: b.status, source: b.source,
          assignee: b.assignee || "—", created: (b.created || "").slice(0, 10),
        }));
      },
      () => M.badcases,
      "badcases"
    );
  }

  /* ================= CONTENT LIBRARY ================= */
  async function contentsList() {
    return live(
      async () => {
        const r = await get("/api/contents?limit=50");
        return (r || []).map(c => ({
          id: c.content_id, title: c.title, cat: c.category, country: c.country,
          language: c.language, platform: c.platform, quality: c.quality_overall,
          published_at: c.published_at, is_bad_case: !!c.is_bad_case,
        }));
      },
      () => M.contents.map(c => ({
        id: c.content_id, title: c.title, cat: c.category, country: c.country,
        language: c.language, platform: c.platform, quality: c.quality_overall,
        published_at: c.published_at, is_bad_case: c.is_bad_case,
      })),
      "contents"
    );
  }

  /* ================= CONTENT DETAIL (READING PAGE) ================= */
  async function content(id) {
    const detail = await live(
      async () => {
        const c = await get(`/api/content/${id}`);
        return {
          content_id: c.content_id, title: c.title, summary: c.summary || "",
          body: Array.isArray(c.body) ? c.body : (c.body ? [{ type: "paragraph", text: String(c.body), citations: [] }] : []),
          tags: c.tags || [], category: c.category, word_count: c.word_count || 0,
          prompt_writer_v: c.prompt_writer_v || "—", quality_overall: c.quality_overall || 0,
          fact_consistency: c.fact_consistency || 0, review_verdict: c.review_verdict || "",
          is_bad_case: !!c.is_bad_case, published_at: c.published_at,
        };
      },
      () => M.contentDetail(id),
      "content.detail"
    );
    const traceInfo = await live(
      async () => {
        const t = await get(`/api/contents/${id}/trace`);
        return {
          content_id: t.content_id, title: t.title, country: t.country,
          decision_log: t.decision_log || {}, task_status: t.task_status,
          spans: (t.spans || []).map(s => ({
            agent: s.agent, name: agentName(s.agent), state: s.status,
            model: s.model || "—", tokens: s.tokens || 0, cost_cny: s.cost_cny || 0,
            duration_ms: s.duration_ms || 0, warnings: s.warnings || [],
          })),
        };
      },
      () => M.contentTrace(id),
      "content.trace"
    );
    return { ...detail, trace: traceInfo };
  }

  /* ================= RUN TOPIC (生产表单提交) ================= */
  async function runTopic(req) {
    if (forced === "mock") return mockRunTopic(req);
    try {
      const url = API_BASE.replace(/\/$/, "") + "/api/content/run-topic";
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          title: req.title, summary: req.summary || "", category: req.category || "tech",
          language: req.language || "zh", country: req.country || "CN",
          priority: req.priority || "P1", angles: req.angles || [],
        }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      lastSource = "live";
      const r = await res.json();
      return { ...r, simulated: false };
    } catch (e) {
      lastSource = "mock";
      console.warn("[VM] runTopic live failed, simulated:", e.message);
      return mockRunTopic(req);
    }
  }
  function mockRunTopic(req) {
    const id = "T-" + Math.random().toString(16).slice(2, 6);
    return { task_id: id, topic_title: req.title, status: "running", simulated: true,
             message: "已模拟提交（离线模式）" };
  }

  /* ================= RUN PIPELINE (完整流水线：趋势探测→选题→生产) ================= */
  async function runPipeline(req) {
    if (forced === "mock") return mockRunPipeline(req);
    try {
      const url = API_BASE.replace(/\/$/, "") + "/api/content/run-pipeline";
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          signals: req.signals || [],
          categories: req.categories || ["tech", "finance", "world"],
          max_topics: req.max_topics || 3,
          country: req.country || "CN",
          variants_per_topic: req.variants_per_topic || 1,
        }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      lastSource = "live";
      const r = await res.json();
      return { ...r, simulated: false };
    } catch (e) {
      lastSource = "mock";
      console.warn("[VM] runPipeline live failed, simulated:", e.message);
      return mockRunPipeline(req);
    }
  }
  function mockRunPipeline(req) {
    const base = M.pipeline;
    const userItems = (req && req.signals && req.signals[0] && req.signals[0].items) || [];
    const trends = userItems.length
      ? userItems.map(s => ({ title: s.title, heat: s.heat || 80 }))
      : base.trends;
    return {
      country: base.country,
      trends_count: trends.length,
      topics_count: base.topics.length,
      trends, topics: base.topics, results: base.results,
      decision_log: base.decision_log,
      simulated: true,
      message: "已模拟运行完整流水线（离线模式）",
    };
  }

  return {
    get API_BASE() { return API_BASE; },
    setMode(m) { forced = m; },
    get mode() { return forced || "auto"; },
    get lastSource() { return lastSource; },
    overview, production, trace, rag, prompts, analytics, badcases, contentsList, content, runTopic, runPipeline,
  };
})();
