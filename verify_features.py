"""验证 P0 去重 / P1 知识库 / P2 多视角变体：等部署->查 KB 总量->跑 variants=2 流水线->核对结果。"""
import urllib.request, json, time, sys

BASE = "https://trendforge-api-h7n6.onrender.com"
API = BASE + "/api"

def get(path, timeout=60):
    for i in range(60):
        try:
            with urllib.request.urlopen(API + path, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i % 10 == 0:
                print(f"[wait] {path}: {e}")
            time.sleep(15)
    return None

def post_json(path, body, timeout=600):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:300]}
    except Exception as e:
        return {"_error": str(e)}

# 1) 等健康 + KB 总量
print("[1] 等待部署健康 ...")
h = get("/health", timeout=20)
print("    health:", h)
stats = get("/rag/stats")
if stats:
    docs = stats.get("documents") or stats.get("total_documents")
    print(f"[1] KB 文档总量: {docs}  chunks: {stats.get('chunks')}")

# 2) 跑流水线：1 话题 × 2 变体（中文），验证 P2
print("[2] 触发 run-pipeline (max_topics=1, variants=2, CN) ...")
r = post_json("/content/run-pipeline",
              {"max_topics": 1, "country": "CN", "variants_per_topic": 2, "categories": ["tech","finance","world"]},
              timeout=600)
if r and "dedup" in r:
    print("[2] 去重统计(dedup):", r.get("dedup"))
    print("[2] variants_per_topic:", r.get("variants_per_topic"))
print("[2] 返回 trends_count:", r.get("trends_count"), "topics_count:", r.get("topics_count"),
      "results:", len(r.get("results", [])) if r else 0)

# 3) 轮询最新内容，确认变体产出（标题应带风格后缀）
print("[3] 轮询最新内容 ...")
time.sleep(5)
cl = get("/contents?limit=4")
items = cl if isinstance(cl, list) else cl.get("contents", cl.get("data", []))
cn = [c for c in items if c.get("country") == "CN"][:4]
for c in cn:
    print(f"   - {c.get('content_id')} | {c.get('title')} | {c.get('content_style')} | {c.get('status')}")
print("DONE")
