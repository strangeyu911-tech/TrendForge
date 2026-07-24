"""新闻入库 — hash 去重 + 智能 Chunk + 完整 metadata + 写 SQLite + 写 Chroma"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import NewsDocument, NewsChunk
from config import settings
from .vectorstore import get_vector_store, chunk_id_for
from .chunker import smart_chunk, estimate_tokens


def _clean_plain(text: str) -> str:
    """清洗为纯文本（去 HTML 标签、合并空白）"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_hash(url: str) -> str:
    """新闻去重 hash = sha256(url)。URL 是最稳定的文章标识"""
    return hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()


def _make_summary(full_text: str, fallback: str = "") -> str:
    """生成摘要：取前 1-2 句，截断 ~200 字"""
    text = _clean_plain(full_text) or _clean_plain(fallback)
    if not text:
        return ""
    # 按句号/问号/感叹号切，取前 2 句
    sents = re.split(r"(?<=[。！？!?\.])\s+", text)
    summary = " ".join(sents[:2])
    if len(summary) > 200:
        summary = summary[:200].rstrip() + "…"
    return summary


def _doc_id_for(hash_val: str) -> str:
    return f"doc_{hash_val[:16]}"


async def ingest_news(
    session: AsyncSession,
    *,
    source_name: str,
    title: str,
    content: str = "",
    full_text: str = "",
    summary: str = "",
    url: str,
    published_at: datetime | str | None = None,
    language: str = "en",
    country: str = "US",
    category: str = "tech",
    credibility_tier: int = 2,
    credibility_level: int | None = None,
    source_type: str = "tech_media",
    source_id: str = "",
    author: str = "",
    entities: list[str] | None = None,
    skip_if_exists: bool = True,
) -> str | None:
    """入库一篇新闻：hash 去重 → 智能切分 → 向量化 → 写 SQLite + Chroma。返回 doc_id（已存在且 skip 则返回 None）"""
    title = _clean_plain(title)
    full_text = _clean_plain(full_text) or _clean_plain(content)
    if not full_text:
        return None
    if not summary:
        summary = _make_summary(full_text, fallback=title)

    # 时间解析
    if published_at is None:
        published_at = datetime.utcnow()
    elif isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.utcnow()
    if hasattr(published_at, "tzinfo") and published_at.tzinfo:
        published_at = published_at.replace(tzinfo=None)

    # ---- hash 去重 ----
    h = compute_hash(url)
    doc_id = _doc_id_for(h)
    if skip_if_exists:
        existing = await session.get(NewsDocument, doc_id)
        if existing:
            return None  # 已存在，跳过

    clevel = credibility_level if credibility_level is not None else credibility_tier

    # ---- 智能切分 ----
    pieces = smart_chunk(title, full_text)
    if not pieces:  # 兜底：整篇作为一个 chunk
        pieces = [{"content": full_text, "token_count": estimate_tokens(full_text), "section_path": ""}]

    chunks_data = []
    for idx, piece in enumerate(pieces):
        cid = chunk_id_for(doc_id, idx)
        chunks_data.append({
            "chunk_id": cid,
            "content": piece["content"],
            "doc_id": doc_id,
            "chunk_index": idx,
            "token_count": piece["token_count"],
            "title": title,
            "source_name": source_name,
            "source_url": url,
            "published_at": published_at.isoformat(),
            "credibility": clevel,
            "credibility_level": clevel,
            "language": language,
            "country": country,
            "category": category,
            "section_path": piece.get("section_path", ""),
            "entities": entities or [],
        })

    # ---- 写 SQLite ----
    doc = NewsDocument(
        doc_id=doc_id, source_id=source_id or f"{source_name}_{doc_id}",
        source_name=source_name, source_type=source_type,
        title=title, summary=summary, content=full_text, full_text=full_text,
        url=url, author=author, published_at=published_at,
        country=country, language=language, category=category,
        credibility_tier=clevel, credibility_level=clevel, hash=h,
        entities=entities or [], status="indexed",
    )
    session.add(doc)
    for cd in chunks_data:
        session.add(NewsChunk(
            chunk_id=cd["chunk_id"], doc_id=doc_id, chunk_index=cd["chunk_index"],
            content=cd["content"], token_count=cd["token_count"],
            title=cd["title"], category=cd["category"], country=cd["country"],
            language=cd["language"], source_name=cd["source_name"],
            source_url=cd["source_url"], publish_time=published_at,
            credibility=cd["credibility"], section_path=cd["section_path"],
            embedding_model=settings.embedding_model,
        ))
    await session.flush()

    # ---- 写 Chroma ----
    store = get_vector_store()
    store.add_chunks(chunks_data)
    return doc_id


async def ingest_batch(session: AsyncSession, news_list: list[dict]) -> tuple[int, int]:
    """批量入库，返回 (成功数, 跳过数)"""
    added, skipped = 0, 0
    for item in news_list:
        try:
            doc_id = await ingest_news(session, **item)
            if doc_id:
                added += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"[ingest] 失败 {item.get('url', '')}: {e}")
    return added, skipped
