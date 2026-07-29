import urllib.request, json, time, sys, re

BASE = "https://trendforge-api-h7n6.onrender.com"

def get(path, timeout=30):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def post(path, data, timeout=540):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())

# 1) 等 API 起来
print("waiting for API up...")
up = False
for i in range(40):
    try:
        h = get("/api/health", timeout=20)
        if h.get("llm_configured"):
            print("API up:", h); up = True; break
    except Exception as e:
        print("not up yet (%d): %s" % (i, str(e)[:80]))
    time.sleep(15)
if not up:
    print("API did not come up in time"); sys.exit(1)

# 2) 跑 run-topic（步骤3-8，比 run-pipeline 快）
topic = {
    "title": "OpenAI 发布 GPT-5.6：分层架构、安全强化与企业级生态扩展",
    "summary": "OpenAI 正式发布 GPT-5.6 系列，引入 Sol/Terra/Luna 分层模型体系与更强的安全红队机制，并扩展企业级生态。",
    "category": "tech", "priority": "P0", "angles": "技术架构,安全对齐,企业生态,行业影响"
}
print("running run-topic...")
cid = None
try:
    st, resp = post("/api/content/run-topic", topic, timeout=540)
    print("run-topic status", st, "keys:", list(resp.keys()) if isinstance(resp, dict) else resp)
    cid = resp.get("content_id") or (resp.get("content", {}) or {}).get("content_id")
except Exception as e:
    print("run-topic call failed:", str(e)[:200])

# 3) 兜底：轮询最新内容
if not cid:
    try:
        items = get("/api/contents?limit=3", timeout=30)
        items = items if isinstance(items, list) else items.get("contents", [])
        cid = items[0].get("content_id") if items else None
        print("polled newest:", cid)
    except Exception as e:
        print("poll failed:", e)

# 4) 拉详情并校验
if cid:
    d = get("/api/content/" + cid, timeout=30)
    body = d.get("body", [])
    full = " ".join(b.get("text", "") for b in body)
    wc = d.get("word_count") or len(full)
    raw_concat = re.findall(r'ev_[a-zA-Z0-9_]{2,}(?=[a-zA-Z0-9_])', full)  # ev_xxx 紧接 ev_xxx（无空格/括号）= 黏连乱码
    dup_bracket = full.count("[ev_")  # 正文里残留的 [ev_xxx] 标记（应已被前端处理，但 API 原文仍带，属正常）
    out = {
        "cid": cid, "title": d.get("title"), "wc": wc,
        "body_chars": len(full), "paragraphs": len(body),
        "raw_ev_concat_count": len(raw_concat),
        "inline_bracket_markers_in_api_text": dup_bracket,
        "sample": full[:600],
    }
    print("=== RESULT ===")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open("/tmp/verify_result.txt", "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))
print("DONE")
