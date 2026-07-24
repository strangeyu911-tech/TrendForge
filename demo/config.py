"""TrendForge Demo 全局配置"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompts"


@dataclass
class Config:
    # 是否使用真实 LLM（False 时走模拟器，便于无 API key 运行）
    use_real_llm: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # 默认模型
    planner_model: str = "gpt-4o-mini"
    research_model: str = "gpt-4o-mini"
    writer_model: str = "gpt-4o-mini"
    reviewer_model: str = "gpt-4o-mini"
    # Workflow
    max_review_rounds: int = 2
    sla_seconds: int = 480
    # RAG
    rag_top_k: int = 20
    # 灰度发布
    gray_initial_ratio: float = 0.1
    gray_observation_minutes: int = 30
    gray_ctr_threshold: float = 0.03


# 单例
CONFIG = Config()


def load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
