"""部署后验证：跑 max_topics=1 variants=2 CN，核对变体产出 + 去重键。"""
import urllib.request, json, time

BASE = "https://trendforge-api-h7n6.onrender.com"
API = BASE + "/api"

def get(path, timeout=20):
    for i in range(80):
        try:
            with urllib.request.urlopen(API + path, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(15)
    return None

def post(path, body, timeout=600):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:400]}
    except Exception as e:
        return {"_error": str(e)}

print("[1] 健康/KB ...")
h = get("/health")
print("   ", h)
st = get("/rag/stats")
if st: print("    docs:", st.get("documents") or st.get("total_documents"))

print("[2] run-pipeline max_topics=1 variants=2 CN ...")
r = post("/content/run-pipeline", {"max_topics": 1, "country": "CN", "variants_per_topic": 2, "categories": ["tech","finance","world"]}, timeout=600)
if r and "dedup" in r:
    print("   dedup:", r.get("dedup"))
    print("   variants_per_topic:", r.get("variants_per_topic"))
    print("   trends_count:", r.get("trends_count"), "topics_count:", r.get("topics_count"))
    res = r.get("results", [])
    print("   results 数:", len(res))
    for x in res:
        t = (x.get("topic") or {}).get("title")
        cid = (x.get("final") or {}).get("content_id")
        print(f"     - {x.get('status')} | {t} | {cid}")
else:
    print("   run-pipeline 异常返回:", json.dumps(r, ensure_ascii=False)[:500])
print("DONE")
