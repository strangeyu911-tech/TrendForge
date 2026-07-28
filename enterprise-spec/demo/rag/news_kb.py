"""RAG 新闻知识库（Demo 版：基于本地 JSON + 内存向量检索）"""
from __future__ import annotations
import math
import hashlib
from datetime import datetime, timezone
from typing import Iterable
from config import load_json, DATA_DIR


class NewsKnowledgeBase:
    """轻量级 RAG 实现：TF-IDF + 时间衰减，便于无 GPU 环境运行"""

    def __init__(self, news_file: str = "sample_news.json"):
        self.documents: list[dict] = []
        self.doc_freq: dict[str, int] = {}
        self.total_docs: int = 0
        self._load(news_file)

    def _load(self, news_file: str) -> None:
        path = DATA_DIR / news_file
        try:
            data = load_json(path)
        except FileNotFoundError:
            data = []
        self.documents = data if isinstance(data, list) else data.get("news", [])
        self.total_docs = len(self.documents)
        self._build_index()

    def _build_index(self) -> None:
        """构建文档频率索引"""
        for doc in self.documents:
            tokens = self._tokenize(doc.get("content", "") + " " + doc.get("title", ""))
            unique = set(tokens)
            for t in unique:
                self.doc_freq[t] = self.doc_freq.get(t, 0) + 1

    def _tokenize(self, text: str) -> list[str]:
        # 简单分词：中文按字 + 英文按词
        tokens = []
        buf = ""
        for ch in text.lower():
            if "\u4e00" <= ch <= "\u9fff":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            elif ch.isalnum():
                buf += ch
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
        if buf:
            tokens.append(buf)
        return tokens

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        vec = {}
        for t, freq in tf.items():
            idf = math.log((self.total_docs + 1) / (self.doc_freq.get(t, 0) + 1)) + 1
            vec[t] = freq * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1
        return {t: v / norm for t, v in vec.items()}

    def _cosine(self, v1: dict, v2: dict) -> float:
        if not v1 or not v2:
            return 0.0
        common = set(v1) & set(v2)
        return sum(v1[t] * v2[t] for t in common)

    def _time_decay(self, published_at: str, lam: float = 0.02) -> float:
        try:
            pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            hours_ago = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            return math.exp(-lam * max(hours_ago, 0))
        except Exception:
            return 0.5

    def retrieve(self, queries: list[str], top_k: int = 20) -> list[dict]:
        """混合检索：TF-IDF 语义 + 时间衰减"""
        if not self.documents:
            return []
        # 合并所有 query 的 token
        all_tokens = []
        for q in queries:
            all_tokens.extend(self._tokenize(q))
        query_vec = self._tfidf(all_tokens)

        scored = []
        for doc in self.documents:
            doc_tokens = self._tokenize(doc.get("content", "") + " " + doc.get("title", ""))
            doc_vec = self._tfidf(doc_tokens)
            semantic = self._cosine(query_vec, doc_vec)
            decay = self._time_decay(doc.get("published_at", ""))
            final = semantic * 0.7 + decay * 0.3
            scored.append((final, semantic, decay, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for final, semantic, decay, doc in scored[:top_k]:
            if final < 0.05:
                continue
            chunk = {
                "chunk_id": f"chk_{hashlib.md5(doc.get('url','').encode()).hexdigest()[:8]}",
                "doc_id": doc.get("doc_id", ""),
                "content": doc.get("content", "")[:500],
                "source_url": doc.get("url", ""),
                "source_name": doc.get("source_name", ""),
                "published_at": doc.get("published_at", ""),
                "credibility": doc.get("credibility", 0.5),
                "language": doc.get("language", "zh"),
                "category": doc.get("category", "news"),
                "entities": doc.get("entities", []),
                "score": round(final, 4),
                "semantic_score": round(semantic, 4),
                "time_decay": round(decay, 4),
            }
            results.append(chunk)
        return results

    def stats(self) -> dict:
        return {
            "total_docs": self.total_docs,
            "vocab_size": len(self.doc_freq),
            "sources": len({d.get("source_name", "") for d in self.documents}),
        }
