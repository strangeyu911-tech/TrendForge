"""本地重建/扩充知识库：在已有 data/ 上增量追加采集（URL hash 去重，只会变多不会变少）。"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "trendforge"))
from db import async_session, init_db
from rag import collect_initial, source_status

async def main():
    await init_db()
    srcs = await source_status()
    print(f"[regen] 配置源数: {len(srcs)}")
    async with async_session() as session:
        stats = await collect_initial(session, target=600)
    print("[regen] 采集统计:", stats)
    # 报告总量
    try:
        import sqlite3
        db = os.path.join(os.path.dirname(__file__), "src", "trendforge", "data", "trendforge.db")
        con = sqlite3.connect(db)
        n_doc = con.execute("SELECT COUNT(*) FROM news_documents").fetchone()[0]
        n_chunk = con.execute("SELECT COUNT(*) FROM news_chunks").fetchone()[0]
        print(f"[regen] 入库总量: docs={n_doc} chunks={n_chunk}")
        con.close()
    except Exception as e:
        print("[regen] 统计失败:", e)

if __name__ == "__main__":
    asyncio.run(main())
