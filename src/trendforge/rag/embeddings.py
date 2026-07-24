"""Embedding 服务 — 独立于对话厂商

策略：
- 配置了 TF_EMBEDDING_API_KEY 或某厂商 key → 用 OpenAI 兼容 embedding
- 否则 → Chroma 内置 all-MiniLM-L6-v2（本地真实向量化，与种子数据维度兼容，零配置）
"""
from __future__ import annotations
from typing import Protocol
from config import settings
from llm import get_embedder


class EmbeddingFunction(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


def get_embedding_function():
    """返回 Chroma 用的 embedding function"""
    emb = get_embedder()
    if emb is not None:
        try:
            from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
            return OpenAIEmbeddingFunction(
                api_key=emb.api_key,
                api_base=emb.base_url,
                model_name=settings.embedding_model,
            )
        except Exception as e:
            print(f"[embedding] OpenAI EF 构造失败，回退本地: {e}")
    # 默认：Chroma 内置 all-MiniLM-L6-v2（onnx，本地真实向量化，与种子数据兼容）
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()
