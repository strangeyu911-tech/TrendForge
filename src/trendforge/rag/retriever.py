"""检索器 — Query 改写 + 向量检索 + RRF 融合 + 时间衰减 + 重排"""
from __future__ import annotations
import math
from datetime import datetime
from collections import defaultdict
from config import settings
from .vectorstore import get_vector_store


class Retriever:
    """混合检索：向量检索 + RRF 融合 + 时间衰减加权"""

    def __init__(self):
        self.store = get_vector_store()

    def retrieve(
        self,
        queries: list[str],
        top_k: int = 20,
        time_window_hours: int | None = None,
        category: str | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        """多 query 并行检索 + RRF 融合 + 时间衰减 + 可信度加权

        filters 支持的键（全部可选，AND 关系）:
            country: str           国家，如 "US"/"GB"
            language: str          语言，如 "en"/"zh"
            category: str          分类，如 "tech"/"finance"/"world"
            credibility_level_max: int   可信等级上限（1=最权威），如 1 只看权威官方
            time_window_hours: int       时间窗口（小时）
            source_name: str       指定来源
        """
        f = dict(filters or {})
        if category:
            f.setdefault("category", category)
        if time_window_hours:
            f.setdefault("time_window_hours", time_window_hours)
        tw = f.pop("time_window_hours", None)

        # 1. 构建 Chroma where（等值过滤 + credibility $lte）
        where = self._build_where(f)

        # 2. 每个 query 向量检索 top 30
        per_query = 30
        all_hits = self.store.query(queries, top_k=per_query, where=where)

        # 3. 时间窗口过滤（Chroma 不支持字符串日期范围，post-filter）
        if tw:
            cutoff = datetime.utcnow().timestamp() - tw * 3600
            filtered = []
            for h in all_hits:
                pa = h.get("published_at", "")
                try:
                    ts = datetime.fromisoformat(pa).timestamp()
                    if ts >= cutoff:
                        filtered.append(h)
                except Exception:
                    filtered.append(h)
            all_hits = filtered

        # 4. RRF 融合（k=60）
        rrf_scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, dict] = {}
        by_query: dict[int, list[dict]] = defaultdict(list)
        for h in all_hits:
            by_query[h["query_index"]].append(h)
        for qi, hits in by_query.items():
            hits_sorted = sorted(hits, key=lambda x: -x["score"])
            for rank, h in enumerate(hits_sorted):
                cid = h["chunk_id"]
                rrf_scores[cid] += 1.0 / (60 + rank + 1)
                chunk_map[cid] = h

        # 5. 按融合分排序，取 top 50
        fused = sorted(rrf_scores.items(), key=lambda x: -x[1])[:50]
        results = []
        for cid, rrf in fused:
            h = chunk_map[cid]
            h["rrf_score"] = rrf
            results.append(h)

        # 6. 时间衰减加权
        for r in results:
            r["final_score"] = r["rrf_score"] * self._time_decay(r.get("published_at", ""))

        # 7. 重排（credibility 越高权重越大：level 1 → 1.0, 3 → 0.7）
        for r in results:
            lvl = r.get("credibility_level", r.get("credibility", 2))
            cred_boost = {1: 1.0, 2: 0.85, 3: 0.7}.get(int(lvl), 0.8)
            r["final_score"] = r["final_score"] * 0.88 + cred_boost * 0.12 * r["rrf_score"]
        results.sort(key=lambda x: -x["final_score"])

        return results[:top_k]

    @staticmethod
    def _build_where(filters: dict) -> dict | None:
        """把 filters 转成 Chroma where 子句"""
        conds = []
        for key in ("country", "language", "category", "source_name"):
            v = filters.get(key)
            if v:
                conds.append({key: v})
        cmax = filters.get("credibility_level_max")
        if cmax is not None:
            conds.append({"credibility_level": {"$lte": int(cmax)}})
        if not conds:
            return None
        if len(conds) == 1:
            return conds[0]
        return {"$and": conds}

    @staticmethod
    def _time_decay(published_at: str) -> float:
        if not published_at:
            return 1.0
        try:
            ts = datetime.fromisoformat(published_at).timestamp()
        except Exception:
            return 1.0
        hours_ago = max(0, (datetime.utcnow().timestamp() - ts) / 3600)
        return math.exp(-settings.rag_time_decay_lambda * hours_ago)

    def stats(self) -> dict:
        return {"total_chunks": self.store.count}


def get_retriever() -> Retriever:
    return Retriever()
