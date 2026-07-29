"""验证语言默认：不带 country 调 run-topic 应产出中文(zh/CN)"""
import json, time, urllib.request, urllib.error

BASE = "https://trendforge-api-h7n6.onrender.com"

def get(path):
    for _ in range(120):
        try:
            with urllib.request.urlopen(BASE + path, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(5)
    return None

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=480) as r:
        return json.loads(r.read())

print("等待 API 就绪…")
h = get("/api/health")
print("health:", h.get("app"), h.get("active_vendor") if h else "down")

print("提交 run-topic（不带 country，应默认中文 CN）…")
try:
    res = post("/api/content/run-topic",
               {"title": "国产大模型开源生态最新进展", "category": "tech", "priority": "P1"})
except Exception as e:
    print("RUN-TOPIC ERROR:", e)
    raise SystemExit

print("status:", res.get("status"), "| task:", res.get("task_id"))
final = res.get("final") or {}
cid = final.get("content_id")
print("content_id:", cid)
if cid:
    c = get(f"/api/content/{cid}")
    print("TITLE :", (c.get("title") or "")[:50])
    print("LANG  :", c.get("language"), "| COUNTRY:", c.get("country"))
    print("VERIFY:", "中文默认 OK" if c.get("language") == "zh" else "仍非中文!")
else:
    print("未产出 content（可能 degraded/failed）; error=", res.get("error"))
