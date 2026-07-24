"""LLM 调用封装：支持真实 OpenAI / 模拟器两种模式"""
from __future__ import annotations
import json
import time
import hashlib
import random
from typing import Any
from config import CONFIG


class LLMResponse:
    def __init__(self, text: str, tokens_in: int, tokens_out: int, model: str, latency_ms: int):
        self.text = text
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.model = model
        self.latency_ms = latency_ms

    @property
    def cost_cny(self) -> float:
        # 粗略成本估算（gpt-4o-mini 价格）
        return round((self.tokens_in * 0.15 + self.tokens_out * 0.6) / 1_000_000 * 7.2, 4)


def _simulate(prompt: str, model: str) -> LLMResponse:
    """模拟 LLM：基于 prompt 关键词生成确定性回复，便于离线演示"""
    time.sleep(random.uniform(0.05, 0.15))  # 模拟网络延迟
    tokens_in = len(prompt) // 3
    tokens_out = max(50, tokens_in // 3)
    latency_ms = random.randint(800, 2000)
    return LLMResponse(
        text=f"[simulated-{model}] " + prompt[:80] + "...",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model,
        latency_ms=latency_ms,
    )


def call_llm(prompt: str, model: str | None = None, response_format: dict | None = None) -> LLMResponse:
    """统一 LLM 调用入口"""
    model = model or CONFIG.writer_model
    if not CONFIG.use_real_llm:
        return _simulate(prompt, model)
    # 真实调用
    try:
        from openai import OpenAI
        client = OpenAI(api_key=CONFIG.openai_api_key, base_url=CONFIG.openai_base_url)
        t0 = time.time()
        kwargs: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if response_format:
            kwargs["response_format"] = response_format
        resp = client.chat.completions.create(**kwargs)
        latency_ms = int((time.time() - t0) * 1000)
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            model=model,
            latency_ms=latency_ms,
        )
    except Exception as e:
        # 真实调用失败时降级到模拟器，保证 Demo 可运行
        print(f"[warn] real LLM failed, fallback to simulator: {e}")
        return _simulate(prompt, model)


def extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（容忍前后多余文本）"""
    text = text.strip()
    # 去掉 markdown code fence
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    # 找第一个 { 或 [
    for i, ch in enumerate(text):
        if ch in "[{":
            break
    else:
        i = 0
    try:
        return json.loads(text[i:])
    except json.JSONDecodeError:
        # 尝试找最后一个 } 或 ]
        for j in range(len(text) - 1, -1, -1):
            if text[j] in "]}":
                try:
                    return json.loads(text[i:j+1])
                except json.JSONDecodeError:
                    continue
        raise
