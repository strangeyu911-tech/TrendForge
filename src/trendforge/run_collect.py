"""临时脚本：首次全量采集 ~300 篇真实新闻（后台运行）"""
import asyncio
from db import init_db, async_session
from rag import collect_initial, get_vector_store


async def main():
    await init_db()
    async with async_session() as s:
        stats = await collect_initial(s, target=300)
    print(f"\n===== 全量采集完成 =====")
    print(f"新增: {stats['added']} 篇")
    print(f"跳过: {stats['skipped']}  失败: {stats['failed']}")
    print(f"各源: {stats['by_source']}")
    print(f"向量库 chunk 总数: {get_vector_store().count}")


if __name__ == "__main__":
    asyncio.run(main())
