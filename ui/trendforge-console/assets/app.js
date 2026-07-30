/* =====================================================================
   TrendForge Console — App logic (async, VM-driven)
   ===================================================================== */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ---- status / label maps ---- */
const STATUS = {
  succeeded: ["ok", "succeeded"], running: ["run", "running"], degraded: ["warn", "degraded"],
  failed: ["bad", "failed"], human_pending: ["warn", "待人工"], pending: ["muted", "pending"],
  done: ["ok", "done"], active: ["run", "active"], draft: ["muted", "draft"],
  staging: ["exp", "staging"], production: ["ok", "production"], archived: ["muted", "archived"],
  open: ["bad", "open"], in_fix: ["warn", "in_fix"], resolved: ["ok", "resolved"], wontfix: ["muted", "wontfix"],
};
const CAT = { tech: "科技", finance: "财经", world: "国际", science: "科学", business: "商业" };
function badge(status, label) {
  const [cls, txt] = STATUS[status] || ["muted", status];
  return `<span class="badge badge--${cls}"><span class="b-dot"></span>${label || txt}</span>`;
}
function catTag(c) { return c ? `<span class="chip chip--cat">${CAT[c] || c}</span>` : ""; }

/* ---- toast ---- */
function toast(msg) {
  let t = $("#toast");
  if (!t) {
    t = document.createElement("div"); t.id = "toast";
    t.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--ink);color:var(--bg-base);padding:10px 18px;border-radius:10px;font-size:13px;font-weight:600;box-shadow:var(--shadow-lg);opacity:0;transition:all .3s var(--ease-out);z-index:99;";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  requestAnimationFrame(() => { t.style.opacity = "1"; t.style.transform = "translateX(-50%) translateY(0)"; });
  clearTimeout(t._t); t._t = setTimeout(() => { t.style.opacity = "0"; t.style.transform = "translateX(-50%) translateY(20px)"; }, 2200);
}

/* =====================================================================
   SVG CHART HELPERS
   ===================================================================== */
function sparkline(vals, w = 120, h = 34) {
  if (!vals || !vals.length) return "";
  const max = Math.max(...vals), min = Math.min(...vals), rng = (max - min) || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, h - 3 - ((v - min) / rng) * (h - 6)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = `M0 ${h} ` + pts.map(p => "L" + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ") + ` L${w} ${h} Z`;
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="${w}" height="${h}">
    <path d="${area}" fill="var(--ember-soft)"/><path d="${line}" fill="none" stroke="var(--ember)" stroke-width="2" stroke-linecap="round"/></svg>`;
}
function funnel(data) {
  const w = 520, rowH = 50, gap = 12, max = data[0].value;
  const h = data.length * (rowH + gap);
  let s = `<svg viewBox="0 0 ${w} ${h}" class="chart">`;
  data.forEach((d, i) => {
    const y = i * (rowH + gap), bw = (d.value / max) * (w * 0.6), x = (w - bw) / 2;
    const op = 1 - i * 0.14;
    s += `<rect x="${x}" y="${y}" width="${bw}" height="${rowH - 8}" rx="9" fill="var(--ember)" opacity="${op}"/>`;
    s += `<text x="${x - 12}" y="${y + (rowH - 8) / 2 + 4}" text-anchor="end" style="fill:var(--ink-soft)">${d.stage}</text>`;
    s += `<text x="${x + bw + 12}" y="${y + (rowH - 8) / 2 + 4}" style="fill:var(--ink)">${d.count}</text>`;
    s += `<text x="${w / 2}" y="${y + (rowH - 8) / 2 + 4}" text-anchor="middle" style="fill:var(--on-accent);font-weight:600">${d.value}%</text>`;
  });
  return s + "</svg>";
}
function hBars(items, opts) {
  const { label, val, max, unit = "%", cls = "bar-fill", w = 480, rowH = 38, pad = 92 } = opts;
  const h = items.length * rowH + 8;
  let s = `<svg viewBox="0 0 ${w} ${h}" class="chart">`;
  items.forEach((it, i) => {
    const y = i * rowH + 7, bw = (it[val] / max) * (w - pad - 56);
    s += `<text x="0" y="${y + (rowH - 10) / 2 + 4}">${it[label]}</text>`;
    s += `<rect x="${pad}" y="${y}" width="${bw}" height="${rowH - 12}" rx="7" class="${cls}"/>`;
    s += `<text x="${pad + bw + 8}" y="${y + (rowH - 10) / 2 + 4}" style="fill:var(--ink-soft)">${it[val]}${unit}</text>`;
  });
  return s + "</svg>";
}
function lineChart(vals, opts = {}) {
  const w = opts.w || 480, h = opts.h || 170, pad = 30;
  if (!vals || !vals.length) return "";
  const max = Math.max(...vals), min = Math.min(...vals), rng = (max - min) || 1;
  const pts = vals.map((v, i) => [pad + (i / (vals.length - 1)) * (w - pad - 12), h - 22 - ((v - min) / rng) * (h - 46)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = `M${pts[0][0]} ${h - 22} ` + pts.map(p => "L" + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ") + ` L${pts[pts.length - 1][0]} ${h - 22} Z`;
  let s = `<svg viewBox="0 0 ${w} ${h}" class="chart">`;
  for (let g = 0; g <= 3; g++) { const y = 18 + g * ((h - 46) / 3); s += `<line x1="${pad}" y1="${y}" x2="${w - 12}" y2="${y}" class="grid-line"/>`; }
  s += `<path d="${area}" class="line-area"/><path d="${line}" class="line-path"/>`;
  pts.forEach(p => s += `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="var(--ember)"/>`);
  return s + "</svg>";
}

/* ---- feed icons ---- */
const FICON = {
  publish: '<path d="M12 19V6M5 12l7-7 7 7" stroke-linecap="round" stroke-linejoin="round"/>',
  check:   '<path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/>',
  revision:'<path d="M4 12a8 8 0 0114-5M20 12a8 8 0 01-14 5M18 4v3h-3M6 20v-3h3" stroke-linecap="round" stroke-linejoin="round"/>',
  reject:  '<path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/>',
  ingest:  '<path d="M12 3v12M7 10l5 5 5-5M5 21h14" stroke-linecap="round" stroke-linejoin="round"/>',
};

/* ---- small view helpers ---- */
const pct = (x, d = 1) => (x == null ? "0" : (x * 100).toFixed(d)) + "%";
const fmtDate = (iso) => iso ? iso.replace("T", " ").slice(0, 16) : "—";
function scoreBar(label, val) {
  const p = Math.round((val || 0) * 100);
  return `<div class="qrow"><span class="qrow__l">${label}</span><span class="qrow__bar"><i style="width:${p}%"></i></span><b>${p}</b></div>`;
}
function verdictBadge(v) {
  return { pass: ["ok", "pass"], revise: ["warn", "revise"], reject: ["bad", "reject"] }[v] ? badge(...{ pass: ["ok", "pass"], revise: ["warn", "revise"], reject: ["bad", "reject"] }[v]) : `<span class="chip">${v || "—"}</span>`;
}

/* ---- text escape (用户输入可能进入渲染) ---- */
const tfEsc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---- 渲染完整流水线结果（趋势探测 → 选题 → 逐话题生产）---- */
function renderPipelineResult(r) {
  if (!r) return "";
  const trendCount = r.trends_count != null ? r.trends_count : (r.trends ? r.trends.length : 0);
  const trendsHtml = (r.trends && r.trends.length)
    ? `<div class="trend-list">${r.trends.map(t => `<span class="chip">${tfEsc(t.title)}${t.heat ? ` <b>${t.heat}</b>` : ""}</span>`).join("")}</div>`
    : `<div class="hint">从知识库自动探测到 <b>${trendCount}</b> 个趋势</div>`;

  const topicSrc = (r.topics && r.topics.length) ? r.topics
    : (r.results || []).map(x => x.topic).filter(Boolean);
  const topicCount = r.topics_count != null ? r.topics_count : topicSrc.length;
  const topicsHtml = topicSrc.length
    ? `<div class="topic-cards">${topicSrc.slice(0, r.max_topics || 5).map(t => `
        <div class="topic-card">
          <div class="topic-card__t">${tfEsc(t.title || "")}</div>
          <div class="topic-card__m">${catTag(t.category || "")} ${tfEsc(t.priority || "")} · ${(t.suggested_angles || []).join(" / ")}</div>
        </div>`).join("")}</div>`
    : `<div class="hint">未选出话题</div>`;

  const produced = (r.results || []).filter(x => x.status === "succeeded" && x.final && x.final.content_id);
  const producedHtml = produced.length
    ? `<div class="prod-list">${produced.map(x => `
        <div class="prod-item" role="button" tabindex="0" onclick="goContent('${x.final.content_id}')" onkeydown="if(event.key==='Enter')goContent('${x.final.content_id}')">
          <span class="badge badge--ok"><span class="b-dot"></span>${tfEsc(x.status)}</span>
          <span class="prod-item__t">${tfEsc((x.topic && x.topic.title) || "")}</span>
          <span class="prod-item__id mono">${tfEsc(x.final.content_id)}</span>
          <span class="row-action">查看内容 →</span>
        </div>`).join("")}</div>`
    : `<div class="hint">本批无成功产出的内容（可在任务列表查看状态）</div>`;

  const dedup = r.dedup;
  const dedupHtml = dedup
    ? `<div class="pl-meta">${dedup.published_count ? `已发布 ${dedup.published_count} 篇 · 本批规避重复选题 <b>${dedup.filtered_repeats}</b> 个` : "暂无已发布内容，无需去重"}${r.variants_per_topic > 1 ? ` · 每话题 <b>${r.variants_per_topic}</b> 视角裂变` : ""}</div>`
    : "";
  const cacheBanner = r.cached
    ? `<div class="pl-cache ${r.served_from_cache_due_to_error ? "pl-cache--warn" : "pl-cache--ok"}">${r.served_from_cache_due_to_error ? "⚠ 免费模型限流中，已返回上次生成结果（秒开，无需等待）" : "⚡ 已命中缓存，秒开（未重复消耗模型额度）"}</div>`
    : "";
  return `
    <div class="pl-out">
      ${cacheBanner}
      ${dedupHtml}
      <div class="pl-step">
        <div class="pl-step__h"><span class="badge badge--ok"><span class="b-dot"></span>① 趋势探测</span> 发现 ${trendCount} 个热点</div>
        ${trendsHtml}
      </div>
      <div class="pl-step">
        <div class="pl-step__h"><span class="badge badge--ok"><span class="b-dot"></span>② 自动选题</span> 选定 ${topicCount} 个话题</div>
        ${topicsHtml}
      </div>
      <div class="pl-step">
        <div class="pl-step__h"><span class="badge badge--ok"><span class="b-dot"></span>③ 逐话题生产</span> 检索 → 写作 → 审核 → 发布</div>
        ${producedHtml}
      </div>
    </div>`;
}

/* =====================================================================
   VIEW LOADERS (VM)
   ===================================================================== */
const LOAD = {
  overview:   () => VM.overview(),
  production: () => VM.production(),
  trace:      (id) => VM.trace(id),
  rag:        () => VM.rag(),
  prompts:    () => VM.prompts(),
  analytics:  () => VM.analytics(),
  badcases:   () => VM.badcases(),
  contents:   () => VM.contentsList(),
  content:    (id) => VM.content(id),
};

/* =====================================================================
   VIEW RENDERERS  (async, return HTML string)
   ===================================================================== */
const R = {};

R.overview = async (d) => {
  const kpi = d.kpis.map(k => {
    const delta = k.delta == null
      ? `<div class="stat__delta" style="color:var(--ink-faint);font-weight:500">实时</div>`
      : `<div class="stat__delta ${k.dir}">${k.dir === "up" ? "▲" : "▼"} ${Math.abs(k.delta)}% <span style="color:var(--ink-faint)">vs 上周</span></div>`;
    const spark = k.spark ? `<div class="stat__spark">${sparkline(k.spark)}</div>` : "";
    return `<div class="stat"><div class="stat__label">${k.label}</div>
      <div class="stat__value">${k.value}<small> ${k.unit}</small></div>${delta}${spark}</div>`;
  }).join("");
  const feed = d.feed.map(f => `
    <div class="feed__item">
      <div class="feed__icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${FICON[f.icon]}</svg></div>
      <div class="feed__main"><div class="t">${f.t}</div><div class="m">${f.m}</div></div>
      <div class="feed__time">${f.time}</div>
    </div>`).join("");
  const topics = d.topics.map((t, i) => `
    <div class="rank" ${t.content_id ? `role="button" tabindex="0" onclick="goContent('${t.content_id}')" onkeydown="if(event.key==='Enter')goContent('${t.content_id}')"` : ""}>
      <span class="rank__no ${i === 0 ? "top" : ""}">${String(i + 1).padStart(2, "0")}</span>
      <div style="flex:1;min-width:0"><div class="strong" style="font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.title}</div>${catTag(t.cat)}</div>
      <div class="heat">${[1,2,3,4,5].map(n => `<i class="${n <= Math.round(t.heat / 20) ? "on" : ""}" style="height:${8 + n * 3}px"></i>`).join("")}</div>
      <span class="rank__val">${t.heat}</span>
    </div>`).join("");
  const health = d.health.map(h => `
    <div class="feed__item" style="padding:10px 0">
      <span class="badge badge--${h.state === "ok" ? "ok" : "warn"}"><span class="b-dot"></span>${h.name}</span>
      <div class="feed__main"><div class="m">${h.note}</div></div>
    </div>`).join("");

  return `
    <div class="stat-grid">${kpi}</div>
    <div class="grid grid--2" style="margin-top:var(--s5)">
      <div class="card">
        <div class="card__head"><h3>内容转化漏斗</h3><span class="sub">曝光 → 读完</span></div>
        <div class="card__body">${funnel(d.funnel)}</div>
      </div>
      <div class="card">
        <div class="card__head"><h3>热点话题榜</h3><span class="sub">点击进入阅读页</span></div>
        <div class="card__body" style="padding-top:var(--s4)">${topics}</div>
      </div>
    </div>
    <div class="grid grid--2" style="margin-top:var(--s5)">
      <div class="card">
        <div class="card__head"><h3>生产动态</h3><span class="sub">最近任务</span></div>
        <div class="card__body card__body--tight"><div class="feed">${feed}</div></div>
      </div>
      <div class="card">
        <div class="card__head"><h3>系统健康</h3><span class="sub">依赖与服务</span></div>
        <div class="card__body card__body--tight">${health}</div>
      </div>
    </div>`;
};

R.production = async (d) => {
  const stageState = (s) => s.state === "done" ? ["ok", "完成"]
    : s.state === "active" ? ["run", "执行中"]
    : s.state === "fail" ? ["bad", "失败"]
    : ["muted", "等待"];
  const stages = d.stages.map((s, i) => {
    const [cls, txt] = stageState(s);
    return `
    <div class="stage ${s.state === "done" ? "is-done" : ""} ${s.state === "active" ? "is-active" : ""} ${s.state === "fail" ? "is-fail" : ""}">
      <div class="stage__idx">STEP ${s.idx}</div>
      <div class="stage__name">${s.name}</div>
      <div class="stage__role">${s.role}</div>
      <div class="stage__state">${badge(cls, txt)}</div>
    </div>${i < d.stages.length - 1 ? '<span class="arrow"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg></span>' : ""}`;
  }).join("");
  const rows = d.tasks.map(t => `
    <tr>
      <td class="mono">${t.id}</td>
      <td class="strong" style="max-width:260px">${t.topic}</td>
      <td>${catTag(t.cat)}</td>
      <td><span class="badge badge--muted">${t.pri}</span></td>
      <td>${badge(t.status)}</td>
      <td class="mono">${t.dur}</td>
      <td class="mono">${t.cost}</td>
      <td class="mono">${t.rounds}</td>
      <td class="row-action" onclick="goView('trace','${t.id}')">查看链路 →</td>
    </tr>`).join("");
  return `
    <div class="page-head">
      <div><h2>内容生产</h2><p>两种方式：① 运行完整流水线（系统自动探测热点并选题）；② 手动指定单个话题生产。</p></div>
    </div>

    <div class="card card--pipeline">
      <div class="card__head"><h3>运行完整流水线</h3><span class="sub">自动趋势探测 → 选题 → 检索 → 写作 → 审核 → 发布</span></div>
      <div class="card__body">
        <label class="field__label">趋势信号（可选，每行一条；留空则由系统从知识库自动探测热点）</label>
        <textarea class="textarea" id="sigInput" placeholder="OpenAI 发布 GPT-6，万亿参数多模态&#10;美联储意外降息 50 个基点&#10;欧盟 AI 法案实施细则落地"></textarea>
        <label class="field__label" style="margin-top:var(--s3)">目标语言</label>
        <select class="select" id="countrySel" style="max-width:200px"><option value="CN" selected>中文</option><option value="US">英文</option></select>
        <label class="field__label" style="margin-top:var(--s3)">每话题变体数（多视角裂变）</label>
        <select class="select" id="variantsSel" style="max-width:200px">
          <option value="1" selected>1 · 单篇</option>
          <option value="2">2 · 双视角</option>
          <option value="3">3 · 三视角</option>
        </select>
        <div class="pl-actions">
          <button class="btn btn--primary" id="runPipelineBtn" type="button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" stroke-linejoin="round"/></svg>
            运行完整流水线
          </button>
          <label class="chk"><input type="checkbox" id="forceGenChk" /> 强制重新生成（跳过缓存）</label>
          <span class="hint">将依次执行 8 步 Agent 链路，耗时视话题数而定</span>
        </div>
        <div id="pipelineResult"></div>
      </div>
    </div>

    <div class="card">
      <div class="card__head"><h3>或：手动指定单个话题</h3><span class="sub">由你给定话题，系统完成检索→写作→审核→发布</span></div>
      <div class="card__body">
        <form id="topicForm" class="field-row">
          <div class="field" style="grid-column:1/3">
            <label>话题标题</label>
            <input class="input" name="title" placeholder="例如：OpenAI 发布 GPT-6，万亿参数多模态" required />
          </div>
          <div class="field" style="grid-column:1/3">
            <label>摘要 / 背景</label>
            <textarea class="textarea" name="summary" placeholder="一句话描述事件要点与已知信息…"></textarea>
          </div>
          <div class="field"><label>品类</label>
            <select class="select" name="category"><option value="tech">科技</option><option value="finance">财经</option><option value="world">国际</option></select>
          </div>
          <div class="field"><label>优先级</label>
            <select class="select" name="priority"><option>P0</option><option selected>P1</option><option>P2</option></select>
          </div>
          <div class="field"><label>目标语言</label>
            <select class="select" name="country"><option value="CN" selected>中文</option><option value="US">英文</option></select>
          </div>
          <div class="field" style="grid-column:1/3"><label>切入角度（逗号分隔）</label>
            <input class="input" name="angles" placeholder="技术解析, 行业影响, 市场反应" />
          </div>
          <div style="grid-column:1/3;display:flex;gap:var(--s3);margin-top:var(--s2)">
            <button class="btn btn--primary" type="submit">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" stroke-linejoin="round"/></svg>
              开始生产
            </button>
            <button class="btn btn--ghost" type="button">存为草稿</button>
          </div>
        </form>
      </div>
    </div>

    <div class="section-title"><h3>流水线编排</h3><span class="hint">${d.pipelineNote || "DAG · 状态机 · 回退"}</span></div>
    <div class="pipeline">${stages}</div>

    <div class="section-title"><h3>任务列表</h3><span class="hint">${d.tasks.length} 个任务（实时历史）· 点击查看链路</span></div>
    <div class="card"><div class="card__body" style="padding:0">
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>任务</th><th>话题</th><th>品类</th><th>优先级</th><th>状态</th><th>时延</th><th>成本</th><th>轮次</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div></div>`;
};

R.trace = async (d, param) => {
  const list = d.tasks.map(t => `
    <div class="feed__item" style="cursor:pointer;padding:10px 0" data-tid="${t.id}" onclick="goView('trace','${t.id}')">
      <span style="margin-right:4px;color:var(--ember)">${traceSel === t.id ? "▸" : "•"}</span>
      <div class="feed__main"><div class="t" style="font-size:13px">${t.topic}</div><div class="m mono">${t.id} · ${badge(t.status)}</div></div>
    </div>`).join("");
  const t = d.selected;
  const dag = t.spans.map(s => `
    <div class="dag__node ${s.state === "pending" ? "" : ""} ${s.state === "fail" ? "is-fail" : ""}">
      <div class="h"><span class="badge badge--${s.state === "done" ? "ok" : s.state === "active" ? "run" : s.state === "fail" ? "bad" : "muted"}"><span class="b-dot"></span>${s.state === "done" ? "完成" : s.state === "active" ? "执行" : s.state === "fail" ? "失败" : "等待"}</span><span class="nm">${s.name}</span></div>
      <div class="meta"><span>tok <b>${(s.tokIn + s.tokOut).toLocaleString()}</b></span><span>¥<b>${Number(s.cost || 0).toFixed(2)}</b></span><span><b>${((s.dur || 0) / 1000).toFixed(1)}s</b></span></div>
      <div class="verdict">${s.verdict}</div>
    </div>`).join("");
  const log = (t.log || []).map(l => `
    <div class="log__row"><span class="who">${l.who}</span><span class="why">${l.why}</span><span class="ts">${l.ts}</span></div>`).join("");
  const logBlock = log
    ? `<div class="card"><div class="card__body"><div class="log">${log}</div></div></div>`
    : `<div class="card"><div class="card__body" style="color:var(--ink-faint)">实时 trace 接口未返回决策日志（详见单篇内容详情页的「全流程链路」）。</div></div>`;
  const totalCost = t.spans.reduce((a, s) => a + (s.cost || 0), 0);
  const totalDur = t.spans.reduce((a, s) => a + (s.dur || 0), 0);
  return `
    <div class="grid grid--2">
      <div class="card"><div class="card__head"><h3>任务</h3><span class="sub">${d.tasks.length} 个可观测</span></div>
        <div class="card__body card__body--tight">${list}</div></div>
      <div class="card"><div class="card__head"><h3>任务概览</h3><span class="sub">${t.id}</span></div>
        <div class="card__body">
          <div class="strong" style="font-size:15px;margin-bottom:var(--s3)">${t.topic}</div>
          <div style="display:flex;gap:var(--s5);flex-wrap:wrap">
            <div><div class="stat__label">状态</div>${badge(t.status)}</div>
            <div><div class="stat__label">总成本</div><div class="mono" style="font-size:18px;font-weight:600">¥${totalCost.toFixed(2)}</div></div>
            <div><div class="stat__label">总时延</div><div class="mono" style="font-size:18px;font-weight:600">${(totalDur / 1000).toFixed(1)}s</div></div>
            <div><div class="stat__label">Span 数</div><div class="mono" style="font-size:18px;font-weight:600">${t.spans.length}</div></div>
          </div>
        </div></div>
    </div>
    <div class="section-title"><h3>Agent Span DAG</h3><span class="hint">每个节点的决策与消耗</span></div>
    <div class="dag">${dag}</div>
    <div class="section-title"><h3>决策日志</h3><span class="hint">可解释性 · 每个 Agent 的「为什么」</span></div>
    ${logBlock}`;
};

R.rag = async (d) => {
  const stats = d.stats.map(s => `
    <div class="stat" style="padding:var(--s4) var(--s5)">
      <div class="stat__label">${s.label}</div>
      <div class="stat__value" style="font-size:var(--fs-xl)">${s.value}</div>
      <div class="stat__delta" style="color:var(--ink-faint)">${s.sub}</div>
    </div>`).join("");
  const rows = d.docs.map(x => `
    <tr>
      <td class="strong" style="max-width:280px">${x.title}</td>
      <td>${x.source}</td>
      <td>${catTag(x.cat)}</td>
      <td><span class="badge badge--${x.cred === 1 ? "ok" : "muted"}"><span class="b-dot"></span>${x.cred === 1 ? "权威官方" : "权威媒体"}</span></td>
      <td class="mono">${x.country}/${x.lang}</td>
      <td class="mono">${x.chunks}</td>
      <td class="mono">${x.date}</td>
    </tr>`).join("");
  return `
    <div class="stat-grid">${stats}</div>
    <div class="page-head" style="margin-top:var(--s7)">
      <div><h2>知识库检索</h2><p>混合检索（向量 + 关键词）+ RRF 融合 + 时间衰减。</p></div>
      <div style="display:flex;gap:var(--s3)">
        <input class="input" placeholder="检索知识库，例如：GPT-6" style="min-width:240px" />
        <button class="btn btn--primary" onclick="toast('检索完成 · 召回证据')">检索</button>
      </div>
    </div>
    <div class="card"><div class="card__body" style="padding:0">
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>标题</th><th>来源</th><th>品类</th><th>可信度</th><th>地区/语言</th><th>Chunks</th><th>入库</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div></div>
    <div class="section-title"><h3>入库新文档</h3></div>
    <div class="card"><div class="card__body">
      <form class="field-row" onsubmit="event.preventDefault();toast('已加入采集队列')">
        <div class="field"><label>来源名称</label><input class="input" placeholder="Reuters" /></div>
        <div class="field"><label>标题</label><input class="input" placeholder="新闻标题" /></div>
        <div class="field" style="grid-column:1/3"><label>原文链接</label><input class="input" placeholder="https://…" /></div>
        <div class="field"><label>品类</label><select class="select"><option>tech</option><option>finance</option><option>world</option></select></div>
        <div class="field"><label>可信度层级</label><select class="select"><option value="1">1 · 权威官方</option><option value="2" selected>2 · 权威媒体</option><option value="3">3 · 一般</option></select></div>
        <div style="grid-column:1/3"><button class="btn btn--primary" type="submit">入库并向量化</button></div>
      </form>
    </div></div>`;
};

R.prompts = async (d) => {
  const rows = d.list.map(p => `
    <tr>
      <td class="mono strong">${p.id}</td>
      <td>${p.agent}</td>
      <td>${p.scene}</td>
      <td><span class="badge badge--ember">${p.ver}</span></td>
      <td>${badge(p.status)}</td>
      <td class="mono">${p.score.toFixed(2)}</td>
      <td>${p.author}</td>
      <td class="mono">${p.updated}</td>
    </tr>`).join("");
  const exp = d.experiments.map(e => {
    const r = e.report;
    return `
    <div class="card">
      <div class="card__head"><h3>${e.id}</h3>${badge(e.status === "running" ? "run" : "ok", e.status === "running" ? "进行中" : "已结束")}</div>
      <div class="card__body">
        <div style="display:flex;gap:var(--s4);flex-wrap:wrap;margin-bottom:var(--s4)">
          <span class="chip">agent: ${e.agent}</span><span class="chip">scene: ${e.scene}</span>
          <span class="chip">分流 ${e.split}</span>
          <span class="chip">n=${r.n.toLocaleString()}</span>
        </div>
        <div class="grid grid--2" style="gap:var(--s4);align-items:stretch">
          <div style="background:var(--bg-sunken);border-radius:var(--r-md);padding:var(--s4)">
            <div class="stat__label">Control · ${e.control}</div>
            <div class="stat__value" style="font-size:var(--fs-xl)">${(r.control * 100).toFixed(1)}%</div>
            <div class="stat__delta" style="color:var(--ink-faint)">CTR</div>
          </div>
          <div style="background:var(--bg-sunken);border-radius:var(--r-md);padding:var(--s4)">
            <div class="stat__label">Treatment · ${e.treatment}</div>
            <div class="stat__value" style="font-size:var(--fs-xl);color:var(--violet)">${(r.treatment * 100).toFixed(1)}%</div>
            <div class="stat__delta ${r.lift >= 0 ? "up" : "down"}">${r.lift >= 0 ? "▲" : "▼"} ${Math.abs(r.lift)}% lift</div>
          </div>
        </div>
        <div style="margin-top:var(--s4);padding-top:var(--s4);border-top:1px solid var(--line);display:flex;gap:var(--s6);flex-wrap:wrap;align-items:center">
          <div><div class="stat__label">Z 值</div><div class="mono" style="font-size:16px;font-weight:600">${r.z}</div></div>
          <div><div class="stat__label">P 值</div><div class="mono" style="font-size:16px;font-weight:600">${r.p}</div></div>
          <div style="flex:1;min-width:200px">${badge(r.significant ? "ok" : "muted", r.significant ? "统计显著 (p<0.05)" : "不显著")}
            <div class="m" style="font-size:12px;color:var(--ink-faint);margin-top:6px">${r.conclusion}</div></div>
        </div>
      </div>
    </div>`;
  }).join("");
  return `
    <div class="page-head"><div><h2>Prompt 版本管理</h2><p>每个 Agent 的 Prompt 独立版本化，支持 draft → staging → production → archived 生命周期。</p></div>
      <button class="btn btn--primary" onclick="toast('已创建新 Prompt 草稿')">+ 新建 Prompt</button></div>
    <div class="card"><div class="card__body" style="padding:0">
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>ID</th><th>Agent</th><th>Scene</th><th>当前版本</th><th>状态</th><th>评分</th><th>作者</th><th>更新</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div></div>
    <div class="section-title"><h3>A/B 实验与显著性检验</h3><span class="hint">Z 检验 · 提升度</span></div>
    <div class="grid grid--2">${exp}</div>`;
};

R.analytics = async (d) => {
  const maxCtr = Math.max(...d.ctrByCat.map(x => x.ctr), 1);
  const maxP = Math.max(...d.promptEffect.map(x => x.ctr), 1);
  const pe = hBars(d.promptEffect, { label: "name", val: "ctr", max: maxP, unit: "%", cls: "bar-fill--vio", w: 460, rowH: 40, pad: 140 });
  return `
    <div class="page-head"><div><h2>数据分析</h2><p>转化漏斗、分品类表现、成本与生产效率趋势。</p></div></div>
    <div class="grid grid--2">
      <div class="card"><div class="card__head"><h3>分品类 CTR</h3><span class="sub">点击率 %</span></div><div class="card__body">${hBars(d.ctrByCat, { label: "cat", val: "ctr", max: maxCtr, unit: "%", cls: "bar-fill", w: 460, rowH: 44 })}</div></div>
      <div class="card"><div class="card__head"><h3>单篇成本趋势</h3><span class="sub">近 12 周 · ¥</span></div><div class="card__body">${lineChart(d.costTrend, { w: 460, h: 170 })}</div></div>
    </div>
    <div class="grid grid--2" style="margin-top:var(--s5)">
      <div class="card"><div class="card__head"><h3>生产效率</h3><span class="sub">周产量 · 篇</span></div><div class="card__body">${lineChart(d.effTrend, { w: 460, h: 170 })}</div></div>
      <div class="card"><div class="card__head"><h3>Prompt 版本效果</h3><span class="sub">CTR by version</span></div><div class="card__body">${pe}</div></div>
    </div>`;
};

R.badcases = async (d) => {
  const rows = d.map(b => `
    <tr>
      <td class="mono">${b.id}</td>
      <td class="strong" style="max-width:240px">${b.content}</td>
      <td><span class="badge badge--muted">${b.l1} · ${b.l2}</span></td>
      <td>${badge(b.severity === "critical" ? "bad" : b.severity === "major" ? "warn" : "muted", b.severity)}</td>
      <td>${badge(b.status)}</td>
      <td>${b.source}</td>
      <td>${b.assignee}</td>
      <td class="row-action" onclick="toast('打开 ${b.id} 修复面板')">处理 →</td>
    </tr>`).join("");
  const bc = document.getElementById("bcBadge");
  if (bc) bc.textContent = d.filter(b => b.status === "open").length;
  return `
    <div class="page-head"><div><h2>Bad Case 质控</h2><p>Reviewer 与人工标记的的质量问题，按根因分类（F/H/C/G/Q/U/D）追踪修复。</p></div>
      <button class="btn btn--ghost" onclick="toast('已导出 Bad Case 周报')">导出周报</button></div>
    <div class="card"><div class="card__body" style="padding:0">
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>ID</th><th>内容</th><th>分类</th><th>严重度</th><th>状态</th><th>来源</th><th>负责人</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div></div>`;
};

R.contents = async (d) => {
  const rows = d.map(c => `
    <tr role="button" tabindex="0" onclick="goContent('${c.id}')" onkeydown="if(event.key==='Enter')goContent('${c.id}')" style="cursor:pointer">
      <td class="strong" style="max-width:320px">${c.title}</td>
      <td>${catTag(c.cat)}</td>
      <td><span class="chip">${c.country}</span></td>
      <td class="mono">${c.language}</td>
      <td class="mono">${c.platform || "—"}</td>
      <td><span class="qpill ${c.quality >= 0.85 ? "ok" : c.quality >= 0.6 ? "warn" : "bad"}">${Math.round(c.quality * 100)}</span></td>
      <td class="mono">${fmtDate(c.published_at)}</td>
      <td>${c.is_bad_case ? badge("bad", "Bad Case") : badge("ok", "正常")}</td>
    </tr>`).join("");
  return `
    <div class="page-head"><div><h2>内容库</h2><p>已发布内容列表。点击任意一行进入阅读页，查看正文与全流程可解释性链路。</p></div>
      <div style="display:flex;gap:var(--s3)">
        <input class="input" placeholder="搜索标题…" style="min-width:220px" />
        <button class="btn btn--primary" onclick="toast('已刷新内容库')">刷新</button>
      </div>
    </div>
    <div class="card"><div class="card__body" style="padding:0">
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>标题</th><th>品类</th><th>国家</th><th>语言</th><th>平台</th><th>质量</th><th>发布</th><th>标记</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div></div>`;
};

R.content = async (d, id) => {
  const c = d; // content VM (detail + trace)
  // 收集全文所有 ev 引用，建立 ev_id -> 序号映射（去重保序），渲染为干净编号角标
  const evMap = {};
  let evSeq = 0;
  (c.body || []).forEach(b => {
    const ids = [...((b.text || "").match(/ev_[a-zA-Z0-9_]+/g) || []), ...(b.citations || [])]
      .map(x => String(x).replace(/[\[\]]/g, ""));
    ids.forEach(ev => { if (ev && !(ev in evMap)) evMap[ev] = ++evSeq; });
  });
  const normEv = (ev) => String(ev).replace(/[\[\]]/g, "");
  const citeSup = (ev) => `<sup class="cite" title="证据 ${esc(ev)}">[${evMap[normEv(ev)] != null ? evMap[normEv(ev)] : "?"}]</sup>`;
  const bodyHtml = (c.body && c.body.length)
    ? c.body.map(b => {
        if (b.type === "heading") return `<h2 class="article__h">${esc(b.text)}</h2>`;
        // 正文内联的 [ev_xxx] / ev_xxx → 编号角标；未在正文内联的 citations → 段尾补上标
        const rendered = esc(b.text || "").replace(/\[?ev_([a-zA-Z0-9_]+)\]?/g, (m, id) => {
          const ev = "ev_" + id;
          return ev in evMap ? citeSup(ev) : esc(m);
        });
        const inlineIds = (b.text || "").match(/ev_[a-zA-Z0-9_]+/g) || [];
        const extra = (b.citations || []).filter(ct => ct && !inlineIds.includes(ct));
        return `<p class="article__p">${rendered}${extra.map(citeSup).join("")}</p>`;
      }).join("")
    : `<p class="article__p">（暂无正文）</p>`;

  const tags = (c.tags || []).map(t => `<span class="chip">#${esc(t)}</span>`).join("");

  const dl = c.trace && c.trace.decision_log;
  const logHtml = dl && typeof dl === "object" && !Array.isArray(dl)
    ? Object.entries(dl).map(([k, v]) => `
        <div class="log__row"><span class="who">${esc(k)}</span><span class="why">${esc(v)}</span></div>`).join("")
    : (Array.isArray(dl) ? dl.map(l => `<div class="log__row"><span class="who">${esc(l.who || "")}</span><span class="why">${esc(l.why || "")}</span></div>`).join("") : `<div class="m" style="color:var(--ink-faint)">无决策日志</div>`);

  const spans = (c.trace && c.trace.spans || []).map(s => `
    <tr>
      <td class="strong">${esc(s.name || s.agent)}</td>
      <td class="mono">${esc(s.model || "—")}</td>
      <td class="mono">${((s.tokens || 0)).toLocaleString()}</td>
      <td class="mono">¥${Number(s.cost_cny || 0).toFixed(2)}</td>
      <td class="mono">${((s.duration_ms || 0) / 1000).toFixed(1)}s</td>
      <td>${badge(s.state)}</td>
      <td class="m" style="max-width:220px">${(s.warnings || []).map(esc).join("; ") || "—"}</td>
    </tr>`).join("");

  return `
    <button class="link-back" onclick="goView('contents')">← 返回内容库</button>
    <article class="reader">
      <div class="reader__meta">
        ${catTag(c.category)}
        ${c.is_bad_case ? badge("bad", "Bad Case") : ""}
        <span class="chip">${esc(c.country || "—")}</span>
        <span class="chip">${esc(c.language || "—")}</span>
        ${c.trace && c.trace.country ? "" : ""}
      </div>
      <h1 class="reader__title">${esc(c.title)}</h1>
      ${c.summary ? `<p class="reader__lead">${esc(c.summary)}</p>` : ""}
      <div class="reader__facts">
        <span>平台 <b>${esc(c.trace ? (c.trace.country || "—") : "—")}</b></span>
        <span>发布 <b>${fmtDate(c.published_at)}</b></span>
        <span>字数 <b>${c.word_count || "—"}</b></span>
        <span>Writer <b>${esc(c.prompt_writer_v || "—")}</b></span>
      </div>
      <div class="reader__body">${bodyHtml}</div>
      <div class="reader__tags">${tags}</div>
    </article>

    <div class="grid grid--2" style="margin-top:var(--s7)">
      <div class="card">
        <div class="card__head"><h3>质量评估</h3><span class="sub">Reviewer 产出</span></div>
        <div class="card__body">
          ${scoreBar("综合质量 overall", c.quality_overall)}
          ${scoreBar("事实一致性 fact", c.fact_consistency)}
          <div style="margin-top:var(--s4);display:flex;gap:var(--s3);align-items:center;flex-wrap:wrap">
            <span class="stat__label" style="margin:0">审核结论</span>
            ${verdictBadge(c.review_verdict)}
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card__head"><h3>全流程链路</h3><span class="sub">${c.trace ? c.trace.task_status || "" : ""}</span></div>
        <div class="card__body">
          <div class="table-wrap"><table class="tbl">
            <thead><tr><th>Agent</th><th>模型</th><th>Token</th><th>成本</th><th>时延</th><th>状态</th><th>告警</th></tr></thead>
            <tbody>${spans}</tbody>
          </table></div>
        </div>
      </div>
    </div>

    <div class="section-title" style="margin-top:var(--s7)"><h3>决策日志</h3><span class="hint">可解释性 · 每个 Agent 的「为什么」</span></div>
    <div class="card"><div class="card__body"><div class="log">${logHtml}</div></div></div>`;
};

/* ---- security: escape user/content text ---- */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* =====================================================================
   NAVIGATION / BOOT
   ===================================================================== */
const TITLES = {
  overview: ["概览看板", "实时生产健康度与关键指标"],
  production: ["内容生产", "发起话题生产 · 流水线编排 · 任务列表"],
  trace: ["任务链路", "端到端可观测 · Agent Span · 决策日志"],
  contents: ["内容库", "已发布内容 · 点击进入阅读页与全流程链路"],
  content: ["内容详情", "阅读页 · 全流程可解释性"],
  rag: ["知识库 RAG", "新闻入库 · 向量检索 · 知识库统计"],
  prompts: ["Prompt 实验室", "版本生命周期 · A/B 实验 · 显著性检验"],
  analytics: ["数据分析", "漏斗 · 分品类 CTR · 成本与效率"],
  badcases: ["Bad Case 质控", "质量问题分诊 · 根因 · 修复追踪"],
};

let traceSel = null;
let currentView = "overview";
let currentParam = null;

function loadingHTML() {
  return `<div class="loading"><span class="spinner"></span> 加载中…</div>`;
}

async function goView(v, param) {
  currentView = v; currentParam = param;
  $$(".view").forEach(s => s.hidden = true);
  const el = $("#view-" + v); el.hidden = false;
  el.innerHTML = loadingHTML();
  try {
    const d = await LOAD[v](param);
    el.innerHTML = await R[v](d, param);
    if (v === "trace" && param) traceSel = param;
    if (v === "production") reattachPipelineIfRunning();
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><h3>加载失败</h3><p>${esc(e.message)}</p></div>`;
  }
  $$(".nav__item").forEach(n => n.classList.toggle("is-active", n.dataset.view === v));
  $("#pageTitle").textContent = (TITLES[v] || [v])[0];
  $("#pageSub").textContent = (TITLES[v] || [""])[1];
  $("#app").classList.remove("nav-open");
  updateSrcPill();
  window.scrollTo({ top: 0 });
}
window.goView = goView;
window.goContent = (id) => goView("content", id);

/* ---- data source pill ---- */
function updateSrcPill() {
  const pill = $("#srcPill"); if (!pill) return;
  const live = VM.lastSource === "live";
  pill.textContent = live ? "● LIVE" : "○ DEMO";
  pill.classList.toggle("is-live", live);
}
function toggleSource() {
  const next = (VM.mode === "live") ? "mock" : "live";
  VM.setMode(next);
  toast(next === "live" ? "已切换为实时数据源" : "已切换为离线演示数据");
  goView(currentView, currentParam);
}

/* ---- theme ---- */
const themeBtn = $("#themeBtn");
function setTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  $("#themeIcon").innerHTML = t === "dark"
    ? '<path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" stroke-linejoin="round"/>'
    : '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" stroke-linecap="round"/>';
}
themeBtn.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  setTheme(cur === "dark" ? "light" : "dark");
});

/* ---- nav / menu / pill events ---- */
$("#nav").addEventListener("click", e => { const a = e.target.closest(".nav__item"); if (a) goView(a.dataset.view); });
$("#menuBtn").addEventListener("click", () => $("#app").classList.toggle("nav-open"));
$("#scrim").addEventListener("click", () => $("#app").classList.remove("nav-open"));
$("#srcPill").addEventListener("click", toggleSource);

/* ---- topic form submit (真实 POST /api/content/run-topic) ---- */
document.addEventListener("submit", e => {
  if (e.target.id === "topicForm") {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const data = new FormData(form);
    const req = {
      title: (data.get("title") || "").toString().trim(),
      summary: (data.get("summary") || "").toString().trim(),
      category: data.get("category") || "tech",
      priority: data.get("priority") || "P1",
      language: "zh",
      country: data.get("country") || "CN",
      angles: (data.get("angles") || "").toString().split(",").map(s => s.trim()).filter(Boolean),
    };
    if (!req.title) { toast("请先填写话题标题"); return; }
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span> 生产中…';
    VM.runTopic(req).then(res => {
      if (res && res.simulated) {
        toast("离线模式：已模拟提交「" + req.title + "」（接入后端后将真实触发流水线）");
      } else {
        toast("生产已启动 · 任务 " + (res.task_id || "?"));
        if (res.task_id) goView("trace", res.task_id);
      }
    }).catch(err => {
      toast("提交失败：" + (err && err.message ? err.message : err));
    }).finally(() => {
      btn.disabled = false; btn.innerHTML = orig; form.reset();
    });
  }
});

/* ---- full pipeline run (趋势探测→选题→生产) —— 后台任务 + 轮询（刷新安全） ---- */
let activePollTimer = null;

function resetRunBtn() {
  const b = document.getElementById("runPipelineBtn");
  if (b) { b.disabled = false; b.innerHTML = "运行完整流水线"; }
}
function finishRun() {
  if (activePollTimer) { clearInterval(activePollTimer); activePollTimer = null; }
  localStorage.removeItem("tf_pipeline_job");
  resetRunBtn();
}
// 轮询后台任务状态；phaseTimer 为可选的客户端状态轮播计时器（刷新恢复场景为 null）
function startPolling(job_id, box, phaseTimer) {
  const tick = async () => {
    try {
      // 视图切换/刷新会重建 #pipelineResult，故每次重新查找当前 DOM 元素，避免写入被替换的旧节点
      box = document.getElementById("pipelineResult") || box;
      const job = await VM.pollPipelineJob(job_id);
      if (job.status === "succeeded") {
        if (phaseTimer) clearInterval(phaseTimer);
        if (activePollTimer) { clearInterval(activePollTimer); activePollTimer = null; }
        const r = job.result || {};
        if (r.cached) toast(r.served_from_cache_due_to_error ? "限流中：已返回上次生成结果" : "命中缓存（秒开）");
        else toast("完整流水线已执行 · 发现 " + (r.trends_count || 0) + " 趋势 / " + (r.topics_count || 0) + " 选题");
        if (box) box.innerHTML = renderPipelineResult(r);
        // 持久化最近一次成功结果，供切走再回来时回显（24h 内）
        try { localStorage.setItem("tf_pipeline_last", JSON.stringify({ result: r, at: Date.now() })); } catch (e) {}
        finishRun();
      } else if (job.status === "failed") {
        if (phaseTimer) clearInterval(phaseTimer);
        if (activePollTimer) { clearInterval(activePollTimer); activePollTimer = null; }
        if (box) box.innerHTML = pipelineErrorHTML(job);
        toast("生成失败，已给出降级提示");
        finishRun();
      } else if (job.status === "not_found") {
        if (phaseTimer) clearInterval(phaseTimer);
        if (activePollTimer) { clearInterval(activePollTimer); activePollTimer = null; }
        if (box) box.innerHTML = pipelineErrorHTML({ ok: false, error: "任务未找到（服务可能已重启）", tip: "请重新运行完整流水线。" });
        toast("任务未找到，请重试");
        finishRun();
      }
      // running：保持轮播状态，继续轮询
    } catch (e) {
      // 网络抖动：继续轮询，不中断
    }
  };
  tick();
  activePollTimer = setInterval(tick, 3000);
}

document.addEventListener("click", e => {
  if (!e.target.closest("#runPipelineBtn")) return;
  const btn = e.target.closest("#runPipelineBtn");
  const input = $("#sigInput");
  const lines = (input && input.value ? input.value : "").split("\n").map(s => s.trim()).filter(Boolean);
  const signals = lines.length ? [{ source: "console", items: lines.map(t => ({ title: t, heat: 0 })) }] : [];
  const box = $("#pipelineResult");
  const force = !!(document.getElementById("forceGenChk") && document.getElementById("forceGenChk").checked);
  btn.disabled = true; btn.innerHTML = "生成中…";
  if (box) box.innerHTML = `<div class="hint" id="plStatus">正在探测趋势并执行流水线…</div>`;
  // 友好状态轮播：免费模型可能限流排队，给出“模型繁忙自动重试”的心理预期
  const phases = [
    "正在探测趋势并执行流水线…",
    "① 趋势探测 → ② 自动选题（已做去重）…",
    "③ 检索知识库 + 调用 AI 写作中（免费模型排队请稍候）…",
    "模型繁忙？已自动退避重试 / 切换备用免费模型，无需操作…",
    "审核与发布中…",
  ];
  let pi = 0;
  const phaseTimer = setInterval(() => { pi = (pi + 1) % phases.length; const s = document.getElementById("plStatus"); if (s) s.textContent = phases[pi]; }, 6000);

  VM.runPipeline({ signals, categories: ["tech", "finance", "world"], max_topics: 3,
    country: ($("#countrySel") ? $("#countrySel").value : "CN"),
    variants_per_topic: ($("#variantsSel") ? parseInt($("#variantsSel").value, 10) || 1 : 1),
    force })
    .then(r => {
      if (r && r.job_id) {
        // 后台任务：记录 job_id 并轮询（刷新安全，进度不丢失）
        clearInterval(phaseTimer);
        localStorage.setItem("tf_pipeline_job", r.job_id);
        if (box) box.innerHTML = `<div class="hint" id="plStatus">正在后台生成中…（可刷新页面，进度不丢失）</div>`;
        startPolling(r.job_id, box, null);
      } else {
        // 同步结果（命中缓存 / 离线模拟）
        clearInterval(phaseTimer);
        if (r && r.ok === false) { if (box) box.innerHTML = pipelineErrorHTML(r); toast("生成失败，已给出降级提示"); finishRun(); return; }
        if (r && r.cached) toast(r.served_from_cache_due_to_error ? "限流中：已返回上次生成结果" : "命中缓存（秒开）");
        else if (r && r.simulated) toast("离线模式：已模拟完整流水线");
        else toast("完整流水线已执行 · 发现 " + (r.trends_count || 0) + " 趋势 / " + (r.topics_count || 0) + " 选题");
        if (box) box.innerHTML = renderPipelineResult(r);
        finishRun();
      }
    })
    .catch(err => { clearInterval(phaseTimer); toast("运行失败：" + (err && err.message ? err.message : err)); if (box) box.innerHTML = ""; finishRun(); });
});

/* 刷新后恢复轮询：若上次运行尚未结束，自动继续（进度不丢失） */
(function resumePipelineJob() {
  const job_id = localStorage.getItem("tf_pipeline_job");
  if (!job_id) return;
  const box = $("#pipelineResult");
  if (box) box.innerHTML = `<div class="hint" id="plStatus">正在后台生成中…（已恢复轮询，进度不丢失）</div>`;
  const b = document.getElementById("runPipelineBtn");
  if (b) { b.disabled = true; b.innerHTML = "生成中…"; }
  startPolling(job_id, box, null);
})();

/* 进入内容生产视图时：若后台流水线仍在跑则恢复“生成中”状态并继续轮询；
   若已完成（含切走期间跑完）则回显上次结果 —— 解决“视图切换导致流水线看起来停止/结果丢失” */
function reattachPipelineIfRunning() {
  const job_id = localStorage.getItem("tf_pipeline_job");
  if (job_id) {
    // 仍在运行：重新显示“生成中”，轮询计时器本身跨视图存活，box 由 tick 动态查找
    const box = document.getElementById("pipelineResult");
    const b = document.getElementById("runPipelineBtn");
    if (b) { b.disabled = true; b.innerHTML = "生成中…"; }
    if (box) box.innerHTML = `<div class="hint" id="plStatus">正在后台生成中…（已恢复轮询，进度不丢失）</div>`;
    return;
  }
  // 无在跑任务：若有 24h 内最近一次成功结果，回显（解决“完成前切走再回来结果丢失”）
  const last = localStorage.getItem("tf_pipeline_last");
  if (last) {
    try {
      const obj = JSON.parse(last);
      if (obj.at && Date.now() - obj.at < 24 * 3600 * 1000) {
        const box = document.getElementById("pipelineResult");
        const b = document.getElementById("runPipelineBtn");
        if (b) { b.disabled = false; b.innerHTML = "运行完整流水线"; }
        if (box) box.innerHTML = renderPipelineResult(obj.result || obj);
      }
    } catch (e) {}
  }
}

/* 生成失败（如免费模型持续限流且无可降级缓存）时的友好降级卡片 */
function pipelineErrorHTML(r) {
  return `<div class="pl-out">
    <div class="pl-cache pl-cache--warn">⚠ 本次生成失败：${tfEsc((r.error || "").slice(0, 160))}</div>
    <div class="pl-step">
      <div class="pl-step__h"><span class="badge badge--warn"><span class="b-dot"></span>降级建议</span></div>
      <div class="hint">${tfEsc(r.tip || "免费模型当前限流或生成失败，可稍后重试。")}</div>
      <div class="pl-actions" style="margin-top:var(--s3)">
        <button class="btn" onclick="goView('contents')">查看已生成内容 →</button>
      </div>
    </div>
  </div>`;
}

/* ---- bad case badge count (mock-only metric) ---- */
try { $("#bcBadge").textContent = (window.MOCK.badcases || []).filter(b => b.status === "open").length; } catch (e) {}

/* ---- boot ---- */
setTheme("light");
goView("overview");
