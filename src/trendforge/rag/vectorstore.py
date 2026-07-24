"""Chroma 向量库封装 — 文档切分、向量化、存储"""
from __future__ import annotations
import hashlib
import time
from datetime import datetime
from typing import Any
import chromadb
from chromadb.config import Settings as ChromaSettings
from config import settings
from .embeddings import get_embedding_function


class VectorStore:
    """Chroma 嵌入式向量库"""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self.ef = get_embedding_function()
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def count(self) -> int:
        return self.collection.count()

    def add_chunks(self, chunks: list[dict]) -> int:
        """批量入库 chunk。每个 chunk 含完整 metadata:
        {chunk_id, content, doc_id, title, source_name, source_url, published_at,
         credibility, credibility_level, language, country, category, section_path, entities}"""
        if not chunks:
            return 0
        ids = [c["chunk_id"] for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = []
        for c in chunks:
            meta = {
                "doc_id": c.get("doc_id", ""),
                "chunk_id": c.get("chunk_id", ""),
                "title": c.get("title", ""),
                "source_name": c.get("source_name", ""),
                "source_url": c.get("source_url", ""),
                "published_at": c.get("published_at", ""),
                "credibility": int(c.get("credibility", c.get("credibility_level", 2))),
                "credibility_level": int(c.get("credibility_level", c.get("credibility", 2))),
                "language": c.get("language", "en"),
                "country": c.get("country", "US"),
                "category": c.get("category", "tech"),
                "section_path": c.get("section_path", ""),
                "entities": ",".join(c.get("entities", []) or []),
            }
            # Chroma metadata 不支持 None
            metadatas.append({k: (v if v is not None else "") for k, v in meta.items()})
        # 分批（Chroma 单批上限）
        batch = 100
        for i in range(0, len(ids), batch):
            self.collection.upsert(
                ids=ids[i:i+batch],
                documents=documents[i:i+batch],
                metadatas=metadatas[i:i+batch],
            )
        return len(chunks)

    def query(self, texts: list[str], top_k: int = 20, where: dict | None = None) -> list[dict]:
        """向量检索，返回带完整 metadata 的结果"""
        results = self.collection.query(
            query_texts=texts,
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        flat = []
        for qi in range(len(texts)):
            ids = results["ids"][qi]
            docs = results["documents"][qi]
            metas = results["metadatas"][qi]
            dists = results["distances"][qi]
            for cid, doc, meta, dist in zip(ids, docs, metas, dists):
                flat.append({
                    "chunk_id": cid,
                    "content": doc,
                    "doc_id": meta.get("doc_id", ""),
                    "title": meta.get("title", ""),
                    "source_name": meta.get("source_name", ""),
                    "source_url": meta.get("source_url", ""),
                    "published_at": meta.get("published_at", ""),
                    "credibility": float(meta.get("credibility", 2)),
                    "credibility_level": int(meta.get("credibility_level", meta.get("credibility", 2))),
                    "language": meta.get("language", "en"),
                    "country": meta.get("country", "US"),
                    "category": meta.get("category", "tech"),
                    "section_path": meta.get("section_path", ""),
                    "entities": [e for e in meta.get("entities", "").split(",") if e],
                    "distance": dist,
                    "score": 1.0 - dist,  # cosine distance -> similarity
                    "query_index": qi,
                })
        return flat

    def delete_by_doc(self, doc_id: str) -> None:
        self.collection.delete(where={"doc_id": doc_id})


# 单例
_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def chunk_id_for(doc_id: str, idx: int) -> str:
    return f"chk_{hashlib.md5(f'{doc_id}_{idx}'.encode()).hexdigest()[:16]}"
