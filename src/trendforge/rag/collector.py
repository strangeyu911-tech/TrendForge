"""News Collector — 可信媒体 RSS 采集 + 全文提取 + hash 去重

数据流：RSS_SOURCES → feedparser 解析 → 提取全文(trafilatura) → 算 hash 去重
       → ingest_news(智能 Chunk + Embedding + 写 SQLite + 写 Chroma)

两类入口：
  collect_initial(target=300)  首次初始化，拉取约 300 篇
  update()                     增量更新，只入库新文章（hash 去重）
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime
from urllib.parse import urlparse
import feedparser
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import NewsDocument
from config import settings, RSS_SOURCES
from .ingestor import ingest_news, compute_hash, _clean_plain


def _parse_published(item) -> datetime:
    """从 feedparser item 解析发布时间"""
    pt = item.get("published_parsed") or item.get("updated_parsed")
    if pt:
        try:
            return datetime(*pt[:6])
        except Exception:
            pass
    for key in ("published", "updated", "created"):
        v = item.get(key)
        if v:
            try:
                from dateutil import parser as dp
                return dp.parse(v).replace(tzinfo=None)
            except Exception:
                continue
    return datetime.utcnow()


def _feed_content(item) -> str:
    """从 feedparser item 提取 RSS 自带的内容（HTML 或纯文本）"""
    # content:encoded 优先
    if item.get("content"):
        try:
            return item["content"][0].get("value", "")
        except Exception:
            pass
    return item.get("summary", "") or item.get("description", "")


def _fetch_fulltext(url: str) -> str:
    """用 trafilatura 抓取页面全文（同步）"""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False, favor_precision=True)
        return text or ""
    except Exception:
        return ""


def _fetch_feed_sync(feed_url: str):
    """同步拉取并解析 RSS（在线程池中运行）"""
    try:
        return feedparser.parse(feed_url, agent=settings.collector_user_agent)
    except Exception as e:
        print(f"[collector] feed 拉取失败 {feed_url}: {e}")
        return None


async def _existing_hashes(session: AsyncSession, hashes: list[str]) -> set[str]:
    """查询哪些 hash 已存在（用于去重，避免重复抓全文）"""
    if not hashes:
        return set()
    stmt = select(NewsDocument.hash).where(NewsDocument.hash.in_(hashes))
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


async def collect(
    session: AsyncSession,
    limit_per_feed: int | None = None,
    target: int | None = None,
    fetch_fulltext: bool | None = None,
) -> dict:
    """采集新闻。返回 {fetched, added, skipped, failed, by_source}"""
    limit_per_feed = limit_per_feed or settings.collector_per_feed_limit
    fetch_fulltext = settings.collector_fetch_fulltext if fetch_fulltext is None else fetch_fulltext
    added = skipped = failed = 0
    by_source: dict[str, int] = {}
    total_processed = 0

    for src in RSS_SOURCES:
        feed_url = src["feed_url"]
        # 1. 拉取 feed（线程池，避免阻塞）
        feed = await asyncio.to_thread(_fetch_feed_sync, feed_url)
        if not feed or getattr(feed, "bozo", 0) and not feed.entries:
            print(f"[collector] 跳过 {src['source_name']}（无条目）")
            continue
        entries = list(feed.entries)[:limit_per_feed]
        print(f"[collector] {src['source_name']}: 取 {len(entries)} 条")

        # 2. 预算 hash，批量查重
        items = []
        hashes = []
        for e in entries:
            url = e.get("link", "")
            if not url:
                continue
            h = compute_hash(url)
            items.append((e, url, h))
            hashes.append(h)
        existing = await _existing_hashes(session, hashes)

        # 3. 逐条处理新文章
        for e, url, h in items:
            if h in existing:
                skipped += 1
                continue
            total_processed += 1
            try:
                title = _clean_plain(e.get("title", ""))
                if not title:
                    continue
                # 提取全文：先用 RSS 自带内容
                raw = _feed_content(e)
                full_text = _clean_plain(raw)
                # 若 RSS 内容过短，抓页面全文
                if fetch_fulltext and len(full_text) < 500:
                    ft = await asyncio.to_thread(_fetch_fulltext, url)
                    if ft and len(ft) > len(full_text):
                        full_text = ft
                if len(full_text) < 80:
                    # 内容太短，跳过（可能是视频/图片新闻）
                    skipped += 1
                    continue

                author = _clean_plain(e.get("author", ""))[:128]
                published_at = _parse_published(e)

                doc_id = await ingest_news(
                    session,
                    source_name=src["source_name"],
                    source_type=src["source_type"],
                    title=title,
                    full_text=full_text,
                    url=url,
                    published_at=published_at,
                    language=src["language"],
                    country=src["country"],
                    category=src["category"],
                    credibility_level=src["credibility_level"],
                    author=author,
                    entities=[],
                )
                if doc_id:
                    added += 1
                    by_source[src["source_name"]] = by_source.get(src["source_name"], 0) + 1
                    existing.add(h)
                    await session.commit()  # 每篇立即提交，缩短写锁持有时间
                else:
                    skipped += 1
                # 达到目标数提前结束
                if target and added >= target:
                    await session.commit()
                    return _stats(added, skipped, failed, by_source, total_processed)
            except Exception as ex:
                failed += 1
                print(f"[collector] 失败 {url}: {ex}")
        await session.commit()

    return _stats(added, skipped, failed, by_source, total_processed)


def _stats(added, skipped, failed, by_source, total_processed) -> dict:
    return {
        "fetched": total_processed,
        "added": added,
        "skipped": skipped,
        "failed": failed,
        "by_source": by_source,
        "at": datetime.utcnow().isoformat(),
    }


async def collect_initial(session: AsyncSession, target: int | None = None) -> dict:
    """首次初始化：采集约 target 篇（默认 300）"""
    target = target or settings.collector_initial_target
    print(f"[collector] 首次初始化采集，目标 {target} 篇...")
    return await collect(session, limit_per_feed=60, target=target, fetch_fulltext=True)


async def update(session: AsyncSession) -> dict:
    """增量更新：拉取各 feed 最新条目，hash 去重后只入库新文章"""
    print("[collector] 增量更新...")
    return await collect(session, limit_per_feed=20, target=None, fetch_fulltext=True)


async def source_status() -> list[dict]:
    """各源配置与可用性（不实际拉取，仅返回配置）"""
    return [
        {
            "source_name": s["source_name"], "feed_url": s["feed_url"],
            "category": s["category"], "country": s["country"], "language": s["language"],
            "credibility_level": s["credibility_level"],
        }
        for s in RSS_SOURCES
    ]
