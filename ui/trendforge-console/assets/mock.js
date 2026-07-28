/* =====================================================================
   TrendForge Console — Offline seed (mock)
   ---------------------------------------------------------------------
   重命名自原 data.js。作为「离线 / 后端不可达」时的回退数据源。
   真实接口由 api.js 调用；两者返回相同的视图模型（VM）结构，
   渲染层无需感知数据来自实时接口还是本地种子。
   ===================================================================== */
const MOCK = {

  /* ---------- OVERVIEW ---------- */
  overview: {
    kpis: [
      { label: "今日生产内容", value: "1,284", unit: "篇", delta: 12.4, dir: "up", spark: [8,12,9,14,11,18,16,22,19,24] },
      { label: "生产成功率", value: "94.2", unit: "%", delta: 1.8, dir: "up", spark: [88,90,91,89,92,93,92,94,93,94] },
      { label: "平均单篇成本", value: "0.38", unit: "¥", delta: -6.1, dir: "up", spark: [0.52,0.49,0.47,0.45,0.44,0.42,0.41,0.40,0.39,0.38] },
      { label: "平均产出时延", value: "42", unit: "s", delta: -9.3, dir: "up", spark: [61,58,55,52,49,47,46,44,43,42] },
    ],
    funnel: [
      { stage: "曝光 Exposed", value: 100, count: "2.41M" },
      { stage: "点击 Clicked", value: 31.2, count: "752K" },
      { stage: "阅读 Read", value: 18.6, count: "448K" },
      { stage: "读完 Finished", value: 9.4, count: "227K" },
    ],
    topics: [
      { content_id: "C-9f21", title: "OpenAI 发布 GPT-6，万亿参数多模态", heat: 98, cat: "tech" },
      { content_id: "C-4a8c", title: "美联储意外降息，风险资产普涨", heat: 91, cat: "finance" },
      { content_id: "C-7b30", title: "欧盟 AI 法案细则落地，合规成本上升", heat: 87, cat: "tech" },
      { content_id: "C-2d15", title: "中东局势缓和，油价单周跌 7%", heat: 79, cat: "world" },
      { content_id: "C-6e44", title: "国产大模型推理成本一年降 80%", heat: 74, cat: "tech" },
    ],
    feed: [
      { icon: "publish", t: "《GPT-6 技术解析》灰度发布 30%", m: "Publisher · writer v2.4.1 · 1.2k 字", time: "2 分钟前", status: "ok" },
      { icon: "check", t: "Reviewer 通过《降息对科技股影响》", m: "事实一致 14/14 · 合规无命中", time: "11 分钟前", status: "ok" },
      { icon: "revision", t: "《欧盟 AI 法案》回退 Writer 重写", m: "Reviewer: 引用缺失 2 处 · 第 2 轮", time: "24 分钟前", status: "warn" },
      { icon: "reject", t: "Bad Case: 《某币暴涨》合规命中 reject", m: "Politics risk: high · 已记录根因", time: "38 分钟前", status: "bad" },
      { icon: "ingest", t: "RAG 入库 Reuters / Bloomberg 12 篇", m: "credibility=2 · 36 chunks", time: "1 小时前", status: "run" },
    ],
    health: [
      { name: "LLM Provider", state: "ok", note: "GPT-6 / 通义 · p99 1.8s" },
      { name: "Chroma 向量库", state: "ok", note: "14,302 chunks · 健康" },
      { name: "Reviewer 队列", state: "warn", note: "积压 18 · 建议扩容" },
      { name: "Publisher 灰度", state: "ok", note: "3 个实验进行中" },
    ],
  },

  /* ---------- PRODUCTION ---------- */
  production: {
    stages: [
      { idx: "01", name: "Trend Detector", role: "趋势探测", state: "done" },
      { idx: "02", name: "Planner", role: "选题 / 大纲", state: "done" },
      { idx: "03", name: "Researcher", role: "RAG 检索", state: "active" },
      { idx: "04", name: "Writer", role: "LLM 生成", state: "pending" },
      { idx: "05", name: "Reviewer", role: "核查 / 合规", state: "pending" },
      { idx: "06", name: "Publisher", role: "灰度发布", state: "pending" },
    ],
    tasks: [
      { id: "T-7f3a", topic: "OpenAI 发布 GPT-6，万亿参数多模态", cat: "tech", pri: "P0", status: "succeeded", dur: "38s", cost: "¥0.41", rounds: 1 },
      { id: "T-9c12", topic: "美联储意外降息 50bp 的市场传导", cat: "finance", pri: "P1", status: "running", dur: "12s", cost: "¥0.12", rounds: 0 },
      { id: "T-2b88", topic: "欧盟 AI 法案实施细则逐条解读", cat: "tech", pri: "P1", status: "degraded", dur: "51s", cost: "¥0.63", rounds: 2 },
      { id: "T-4d05", topic: "国产推理芯片量产对算力格局影响", cat: "tech", pri: "P2", status: "human_pending", dur: "—", cost: "—", rounds: 0 },
      { id: "T-6e91", topic: "中东停火协议后的能源价格路径", cat: "world", pri: "P1", status: "failed", dur: "9s", cost: "¥0.07", rounds: 0 },
      { id: "T-1a47", topic: "量子纠错新突破意味着什么", cat: "tech", pri: "P2", status: "succeeded", dur: "44s", cost: "¥0.39", rounds: 1 },
    ],
  },

  /* ---------- TRACE ---------- */
  trace: {
    tasks: [
      {
        id: "T-7f3a", topic: "OpenAI 发布 GPT-6，万亿参数多模态", status: "succeeded",
        spans: [
          { agent: "trend_detector", name: "Trend Detector", state: "done", model: "—", tokIn: 0, tokOut: 0, cost: 0, dur: 1200, verdict: "信号热度 98，纳入选题池" },
          { agent: "planner", name: "Planner", state: "done", model: "gpt-6", tokIn: 1820, tokOut: 640, cost: 0.09, dur: 4200, verdict: "选定角度：技术解析 / 行业影响" },
          { agent: "researcher", name: "Researcher", state: "done", model: "embed-v3", tokIn: 0, tokOut: 0, cost: 0.03, dur: 3100, verdict: "召回 14 条证据，RRF 融合" },
          { agent: "writer", name: "Writer", state: "done", model: "gpt-6", tokIn: 9400, tokOut: 1180, cost: 0.18, dur: 9800, verdict: "生成 1.2k 字，强制引用 9 处" },
          { agent: "reviewer", name: "Reviewer", state: "done", model: "gpt-6", tokIn: 5200, tokOut: 410, cost: 0.08, dur: 6400, verdict: "事实一致 14/14，合规无命中 → pass" },
          { agent: "publisher", name: "Publisher", state: "done", model: "—", tokIn: 0, tokOut: 0, cost: 0.03, dur: 2300, verdict: "灰度 30%，规划 4 渠道" },
        ],
        log: [
          { who: "Planner", why: "GPT-6 为本周最高热信号，优先 tech 深度解读", ts: "12:01:04" },
          { who: "Researcher", why: "优先采用 credibility≥2 来源，剔除 1 条低质", ts: "12:01:09" },
          { who: "Reviewer", why: "引用 [8] 与 [11] 冲突，已采信权威官方", ts: "12:01:32" },
          { who: "Publisher", why: "先灰度 30% 观察 CTR 再全量", ts: "12:01:41" },
        ],
      },
      {
        id: "T-2b88", topic: "欧盟 AI 法案实施细则逐条解读", status: "degraded",
        spans: [
          { agent: "trend_detector", name: "Trend Detector", state: "done", model: "—", tokIn: 0, tokOut: 0, cost: 0, dur: 1100, verdict: "热度 87，合规强相关" },
          { agent: "planner", name: "Planner", state: "done", model: "gpt-6", tokIn: 1610, tokOut: 590, cost: 0.08, dur: 3900, verdict: "角度：合规成本 / 企业影响" },
          { agent: "researcher", name: "Researcher", state: "done", model: "embed-v3", tokIn: 0, tokOut: 0, cost: 0.03, dur: 2900, verdict: "召回 11 条" },
          { agent: "writer", name: "Writer", state: "done", model: "gpt-6", tokIn: 8800, tokOut: 1050, cost: 0.16, dur: 9100, verdict: "第 1 轮生成，引用缺失 2 处" },
          { agent: "reviewer", name: "Reviewer", state: "done", model: "gpt-6", tokIn: 4900, tokOut: 380, cost: 0.07, dur: 6000, verdict: "revise：引用缺失 → 回退 Writer" },
          { agent: "writer", name: "Writer (R2)", state: "done", model: "gpt-6", tokIn: 9100, tokOut: 1120, cost: 0.18, dur: 9600, verdict: "第 2 轮补齐引用 → pass" },
          { agent: "publisher", name: "Publisher", state: "pending", model: "—", tokIn: 0, tokOut: 0, cost: 0, dur: 0, verdict: "等待人工确认后发布" },
        ],
        log: [
          { who: "Reviewer", why: "引用缺失 2 处，按规则回退 Writer（≤2）", ts: "11:42:18" },
          { who: "Writer", why: "第 2 轮补充官方公报原文引用", ts: "11:42:55" },
          { who: "System", why: "已达回退上限，标记 degraded 待人工", ts: "11:43:10" },
        ],
      },
    ],
  },

  /* ---------- RAG ---------- */
  rag: {
    stats: [
      { label: "文档总数", value: "8,412", sub: "news_documents" },
      { label: "Chunk 总数", value: "14,302", sub: "已向量化" },
      { label: "来源站点", value: "63", sub: "tech_media / official" },
      { label: "检索平均时延", value: "38ms", sub: "hybrid + RRF" },
    ],
    docs: [
      { title: "OpenAI announces GPT-6 with 10T parameters", source: "OpenAI Blog", type: "official", cat: "tech", cred: 1, country: "US", lang: "en", chunks: 6, date: "2026-07-27" },
      { title: "Reuters: 美联储意外降息 50 个基点", source: "Reuters", type: "tech_media", cat: "finance", cred: 2, country: "US", lang: "zh", chunks: 4, date: "2026-07-27" },
      { title: "欧盟 AI 法案实施细则全文发布", source: "European Commission", type: "official", cat: "tech", cred: 1, country: "EU", lang: "en", chunks: 9, date: "2026-07-26" },
      { title: "国产推理芯片量产，单价降 40%", source: "36氪", type: "tech_media", cat: "tech", cred: 2, country: "CN", lang: "zh", chunks: 5, date: "2026-07-26" },
      { title: "中东停火协议要点解读", source: "BBC", type: "tech_media", cat: "world", cred: 2, country: "GB", lang: "en", chunks: 3, date: "2026-07-25" },
    ],
  },

  /* ---------- PROMPTS ---------- */
  prompts: {
    list: [
      { id: "planner_news", agent: "planner", scene: "news", status: "production", ver: "v2.3.0", score: 0.91, author: "li.wei", updated: "2026-07-25" },
      { id: "writer_deep_dive", agent: "writer", scene: "deep_dive", status: "production", ver: "v2.4.1", score: 0.94, author: "li.wei", updated: "2026-07-27" },
      { id: "writer_breaking", agent: "writer", scene: "breaking", status: "staging", ver: "v1.2.0", score: 0.88, author: "sun.q", updated: "2026-07-27" },
      { id: "reviewer_compliance", agent: "reviewer", scene: "compliance", status: "production", ver: "v3.0.2", score: 0.96, author: "wang.f", updated: "2026-07-24" },
      { id: "researcher_rag", agent: "researcher", scene: "rag", status: "archived", ver: "v1.0.4", score: 0.82, author: "system", updated: "2026-07-10" },
    ],
    experiments: [
      {
        id: "EXP-writer-014", agent: "writer", scene: "deep_dive",
        control: "v2.4.1", treatment: "v2.5.0-rc", split: "50 / 50", status: "running",
        report: { control: 0.312, treatment: 0.358, lift: 14.7, z: 2.41, p: 0.016, significant: true, n: 4120,
          conclusion: "treatment 在 CTR 上显著优于 control（p<0.05），建议升版。" },
      },
      {
        id: "EXP-reviewer-007", agent: "reviewer", scene: "compliance",
        control: "v3.0.2", treatment: "v3.1.0-rc", split: "50 / 50", status: "concluded",
        report: { control: 0.943, treatment: 0.951, lift: 0.8, z: 0.62, p: 0.534, significant: false, n: 3860,
          conclusion: "差异不显著，保持当前 production 版本。" },
      },
    ],
  },

  /* ---------- ANALYTICS ---------- */
  analytics: {
    ctrByCat: [
      { cat: "tech", ctr: 34.8 },
      { cat: "finance", ctr: 29.1 },
      { cat: "world", ctr: 22.6 },
      { cat: "science", ctr: 25.3 },
      { cat: "business", ctr: 19.7 },
    ],
    costTrend: [0.52,0.49,0.47,0.45,0.44,0.42,0.41,0.40,0.39,0.38,0.37,0.36],
    effTrend: [820,910,880,1020,980,1100,1150,1120,1240,1284,1260,1310],
    promptEffect: [
      { name: "writer v2.4.1", ctr: 31.2, cost: 0.38 },
      { name: "writer v2.5.0-rc", ctr: 35.8, cost: 0.36 },
      { name: "planner v2.3.0", ctr: 28.4, cost: 0.09 },
      { name: "reviewer v3.0.2", ctr: 94.3, cost: 0.07 },
    ],
  },

  /* ---------- BAD CASES ---------- */
  badcases: [
    { id: "BC-204", content: "《某代币单周暴涨 300%》", l1: "C", l2: "compliance", severity: "critical", status: "open", source: "reviewer", reason: "高 politics/financial risk，疑似荐币", assignee: "—", created: "2026-07-27" },
    { id: "BC-201", content: "《国产芯片全面超越》", l1: "F", l2: "fact", severity: "major", status: "in_fix", source: "reviewer", reason: "事实不一致 2 处，夸大表述", assignee: "sun.q", created: "2026-07-26" },
    { id: "BC-198", content: "《量子计算已实用化》", l1: "Q", l2: "quality", severity: "minor", status: "resolved", source: "human", reason: "标题党，完成率偏低", assignee: "wang.f", created: "2026-07-25" },
    { id: "BC-195", content: "《某车企财报解读》", l1: "G", l2: "copyright", severity: "major", status: "open", source: "reviewer", reason: "版权风险 high，引用超量", assignee: "—", created: "2026-07-24" },
    { id: "BC-190", content: "《天气影响农作物》", l1: "U", l2: "usability", severity: "minor", status: "wontfix", source: "human", reason: "与选题池弱相关", assignee: "li.wei", created: "2026-07-22" },
  ],

  /* ---------- CONTENT LIBRARY + READING PAGE ---------- */
  contents: [
    { content_id: "C-9f21", title: "OpenAI 发布 GPT-6，万亿参数多模态", category: "tech", country: "US", language: "zh", platform: "wechat", content_style: "deep_dive", quality_overall: 0.94, published_at: "2026-07-27T14:10:00", is_bad_case: false },
    { content_id: "C-4a8c", title: "美联储意外降息 50 个基点，风险资产普涨", category: "finance", country: "US", language: "zh", platform: "weibo", content_style: "breaking_news", quality_overall: 0.91, published_at: "2026-07-27T09:32:00", is_bad_case: false },
    { content_id: "C-7b30", title: "欧盟 AI 法案实施细则逐条解读", category: "tech", country: "EU", language: "zh", platform: "zhihu", content_style: "deep_dive", quality_overall: 0.88, published_at: "2026-07-26T18:05:00", is_bad_case: false },
    { content_id: "C-2d15", title: "中东停火协议后的能源价格路径", category: "world", country: "GB", language: "zh", platform: "wechat", content_style: "summary", quality_overall: 0.86, published_at: "2026-07-25T21:40:00", is_bad_case: false },
    { content_id: "C-6e44", title: "国产大模型推理成本一年降 80%，意味着什么", category: "tech", country: "CN", language: "zh", platform: "weibo", content_style: "deep_dive", quality_overall: 0.89, published_at: "2026-07-26T11:15:00", is_bad_case: false },
    { content_id: "C-1c77", title: "某代币单周暴涨 300%，是机会还是陷阱", category: "finance", country: "CN", language: "zh", platform: "weibo", content_style: "breaking_news", quality_overall: 0.41, published_at: "2026-07-27T08:02:00", is_bad_case: true },
  ],

  contentDetail(id) {
    const meta = (MOCK.contents.find(c => c.content_id === id)) || MOCK.contents[0];
    const bodies = {
      "C-9f21": [
        { type: "heading", text: "万亿参数，多模态原生" },
        { type: "paragraph", text: "OpenAI 于今日发布 GPT-6，官方称其参数量达到万亿级别，并在架构层面原生支持文本、图像、音频与视频的统一表征。与迭代式多模态不同，GPT-6 在预训练阶段即完成跨模态对齐，推理时无需额外的桥接模块。", citations: ["[3]", "[8]"] },
        { type: "paragraph", text: "我们在复现基准上观察到，模型在视频时序理解任务上的错误率较上一代下降约 41%，但官方尚未公开完整评测协议，第三方验证仍在进行。", citations: ["[11]"] },
        { type: "heading", text: "对内容生产的直接影响" },
        { type: "paragraph", text: "对于自动化新闻生产链路而言，原生多模态意味着 Researcher 阶段可以直接消费视频证据，Writer 可在同一上下文中组织图文混排。本系统在灰度中已将 writer v2.5.0-rc 接入新模型，初步 CTR 提升 14.7%。", citations: ["[8]", "[14]"] },
        { type: "paragraph", text: "但需警惕：多模态证据的可信度核查成本更高，Reviewer 的核查轮次可能上升。事实一致性应作为发布前的硬性闸门。", citations: ["[8]"] },
      ],
      "C-4a8c": [
        { type: "heading", text: "超预期的一次性降息" },
        { type: "paragraph", text: "美联储本次降息 50 个基点，幅度超出市场一致预期 25 个基点。利率声明中删除了“通胀仍偏高”的措辞，被解读为宽松周期的开启。", citations: ["[2]"] },
        { type: "paragraph", text: "风险资产应声普涨：纳指期货涨 2.3%，黄金突破历史新高，美元指数走弱。但债券市场的长端收益率不降反升，显示对财政可持续性的担忧并未消散。", citations: ["[5]", "[9]"] },
      ],
      "C-1c77": [
        { type: "heading", text: "风险提示" },
        { type: "paragraph", text: "本文因涉及高金融风险且缺乏权威信源，被 Reviewer 标记为 Bad Case（合规命中）。以下为人工复核后的中性表述：该代币近一周价格波动剧烈，流动性不足，散户参与需高度谨慎。", citations: ["[—]"] },
      ],
    };
    return {
      content_id: meta.content_id,
      title: meta.title,
      summary: "由 TrendForge 自动生成，经 Reviewer 核查与合规过滤。下方为正文与全流程可解释性链路。",
      body: bodies[id] || [
        { type: "paragraph", text: "本篇为示例内容，正文数据用于演示阅读页排版与引用体系。真实内容由生产流水线在发布后写入。", citations: [] },
        { type: "heading", text: "小节示例" },
        { type: "paragraph", text: "段落示例：自动化生产系统在保证事实一致性的前提下，持续供给多语言、多平台内容。", citations: ["[3]"] },
      ],
      tags: ["AI", "GPT-6", "多模态", "生产力"],
      category: meta.category,
      word_count: 1180,
      prompt_writer_v: "v2.4.1",
      quality_overall: meta.quality_overall,
      fact_consistency: meta.is_bad_case ? 0.62 : 0.96,
      review_verdict: meta.is_bad_case ? "reject" : "pass",
      is_bad_case: meta.is_bad_case,
      published_at: meta.published_at,
    };
  },

  contentTrace(id) {
    const meta = (MOCK.contents.find(c => c.content_id === id)) || MOCK.contents[0];
    return {
      content_id: id,
      title: meta.title,
      country: meta.country,
      decision_log: meta.is_bad_case
        ? { reviewer: "合规命中：高风险金融荐币表述，无权威信源，标记 reject 并归档根因 C/compliance。", publisher: "未发布，已进入 Bad Case 分诊。" }
        : { planner: "选题热度达标，定为 tech 深度解读，避免标题党。", researcher: "优先 credibility≥2 来源，剔除 1 条低质。", reviewer: "事实一致 14/14，合规无命中 → pass。", publisher: "灰度 30% 观察 CTR 后再全量。" },
      task_status: meta.is_bad_case ? "failed" : "succeeded",
      spans: [
        { agent: "trend_detector", status: "done", model: "—", tokens: 0, cost_cny: 0, duration_ms: 1200, warnings: [] },
        { agent: "planner", status: "done", model: "gpt-6", tokens: 2460, cost_cny: 0.09, duration_ms: 4200, warnings: [] },
        { agent: "researcher", status: "done", model: "embed-v3", tokens: 0, cost_cny: 0.03, duration_ms: 3100, warnings: [] },
        { agent: "writer", status: meta.is_bad_case ? "fail" : "done", model: "gpt-6", tokens: 10580, cost_cny: 0.18, duration_ms: 9800, warnings: meta.is_bad_case ? ["合规风险：高金融风险表述"] : [] },
        { agent: "reviewer", status: meta.is_bad_case ? "fail" : "done", model: "gpt-6", tokens: 5610, cost_cny: 0.08, duration_ms: 6400, warnings: meta.is_bad_case ? ["reject: 合规命中"] : [] },
        { agent: "publisher", status: meta.is_bad_case ? "pending" : "done", model: "—", tokens: 0, cost_cny: 0.03, duration_ms: 2300, warnings: [] },
      ],
    };
  },
};

window.MOCK = MOCK;
window.DB = MOCK; // 兼容别名
