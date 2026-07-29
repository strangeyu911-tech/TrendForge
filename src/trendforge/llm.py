"""LLM Provider — 多厂商统一抽象（OpenAI / Anthropic / DeepSeek / Kimi / Qwen / GLM）

设计：
- OpenAICompatibleProvider: 处理 openai/deepseek/kimi/qwen/glm（都走 /chat/completions 兼容接口）
- AnthropicProvider: 原生 Messages API（claude）
- 厂商密钥解析：TF_<VENDOR>_API_KEY 优先，回退通用 TF_LLM_API_KEY
- Embedding 独立配置（get_embedder），与对话厂商解耦，保持向量维度稳定
"""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Any
import httpx
from openai import AsyncOpenAI
from config import settings, VENDOR_DEFAULTS


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_ms: int
    vendor: str = ""
    cost_cny: float = 0.0


# 模型定价（¥/1M tokens，输入/输出）— 近似值，仅用于成本核算
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (1.5, 6.0), "gpt-4o": (18.0, 72.0),
    "gpt-4.1-mini": (1.5, 6.0), "gpt-4.1": (30.0, 120.0),
    "gpt-4-turbo": (60.0, 180.0),
    # Anthropic
    "claude-3-5-haiku-20241022": (6.0, 30.0),
    "claude-3-5-sonnet-20241022": (22.0, 110.0),
    "claude-3-opus-20240229": (110.0, 550.0),
    "claude-3-haiku-20240307": (1.8, 9.0),
    # DeepSeek
    "deepseek-chat": (1.0, 2.0), "deepseek-reasoner": (4.0, 16.0),
    # Kimi (Moonshot)
    "moonshot-v1-8k": (12.0, 12.0), "moonshot-v1-32k": (24.0, 24.0), "moonshot-v1-128k": (60.0, 60.0),
    # Qwen (DashScope)
    "qwen-plus": (0.8, 2.0), "qwen-turbo": (2.0, 6.0), "qwen-max": (20.0, 60.0),
    # GLM (智谱)
    "glm-4.7-flash": (0.0, 0.0), "glm-4-flash": (0.1, 0.1), "glm-4": (50.0, 50.0), "glm-4-air": (1.0, 1.0), "glm-4-plus": (50.0, 50.0),
    "default": (2.0, 8.0),
}


def _calc_cost(model: str, tin: int, tout: int) -> float:
    pin, pout = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    return round((tin * pin + tout * pout) / 1_000_000, 4)


# ============ 厂商密钥解析 ============
def get_vendor_api_key(vendor: str) -> str:
    """厂商 API key：优先 TF_<VENDOR>_API_KEY（settings 或 env），回退通用 TF_LLM_API_KEY"""
    v = (vendor or settings.llm_vendor).lower()
    per_vendor = getattr(settings, f"{v}_api_key", "") or ""
    if per_vendor:
        return per_vendor
    return settings.llm_api_key or os.environ.get(f"TF_{v.upper()}_API_KEY", "")


def list_vendors() -> list[dict]:
    """列出全部支持的厂商及其配置状态（不暴露 key）"""
    out = []
    for v, d in VENDOR_DEFAULTS.items():
        out.append({
            "vendor": v, "label": d["label"], "kind": d["kind"],
            "base_url": d["base_url"], "default_model": d["default_model"],
            "configured": bool(get_vendor_api_key(v)),
            "active": v == settings.llm_vendor,
        })
    return out


# ============ Provider 抽象 ============
class BaseProvider:
    """LLM 对话 Provider 基类"""
    vendor: str = "base"
    kind: str = "base"

    def __init__(self, base_url: str, api_key: str, default_model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


# 向后兼容别名（旧代码引用 LLMProvider 类型提示）
LLMProvider = BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI 兼容厂商：openai / deepseek / kimi / qwen / glm"""
    kind = "openai"

    def __init__(self, vendor: str, base_url: str, api_key: str, default_model: str):
        super().__init__(base_url, api_key, default_model)
        self.vendor = vendor
        self.client = AsyncOpenAI(
            api_key=api_key, base_url=base_url,
            timeout=settings.llm_timeout, max_retries=settings.llm_max_retries,
        )

    async def chat(self, prompt, model=None, system=None, json_mode=False, temperature=0.7, max_tokens=None) -> LLMResponse:
        model = model or self.default_model
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": model, "messages": messages, "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.time()
        resp = await self.client.chat.completions.create(**kwargs)
        latency_ms = int((time.time() - t0) * 1000)
        text = resp.choices[0].message.content or ""
        tin = resp.usage.prompt_tokens if resp.usage else 0
        tout = resp.usage.completion_tokens if resp.usage else 0
        return LLMResponse(
            text=text, tokens_in=tin, tokens_out=tout, model=model,
            latency_ms=latency_ms, vendor=self.vendor, cost_cny=_calc_cost(model, tin, tout),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化（仅 OpenAI 兼容厂商支持）"""
        resp = await self.client.embeddings.create(model=settings.embedding_model, input=texts)
        return [d.embedding for d in resp.data]


class AnthropicProvider(BaseProvider):
    """Anthropic 原生 Messages API（claude）"""
    vendor = "anthropic"
    kind = "anthropic"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, base_url: str, api_key: str, default_model: str):
        super().__init__(base_url, api_key, default_model)
        self._http = httpx.AsyncClient(timeout=settings.llm_timeout)

    async def chat(self, prompt, model=None, system=None, json_mode=False, temperature=0.7, max_tokens=None) -> LLMResponse:
        model = model or self.default_model
        sys_parts: list[str] = []
        if system:
            sys_parts.append(system)
        if json_mode:
            # Anthropic 无原生 json_object，用 system 指令约束
            sys_parts.append("请严格只输出合法 JSON 对象，不要 markdown 围栏、不要任何解释文字。")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 2048,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if sys_parts:
            body["system"] = "\n\n".join(sys_parts)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        t0 = time.time()
        r = await self._http.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
        latency_ms = int((time.time() - t0) * 1000)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:400]}")
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        tin = usage.get("input_tokens", 0)
        tout = usage.get("output_tokens", 0)
        return LLMResponse(
            text=text, tokens_in=tin, tokens_out=tout, model=model,
            latency_ms=latency_ms, vendor=self.vendor, cost_cny=_calc_cost(model, tin, tout),
        )


# ============ 工厂 ============
def get_provider(vendor: str | None = None) -> BaseProvider:
    """构造指定厂商的 Provider（未配置 key 抛错）"""
    v = (vendor or settings.llm_vendor).lower()
    if v not in VENDOR_DEFAULTS:
        raise ValueError(f"不支持的厂商: {v}（支持: {', '.join(VENDOR_DEFAULTS.keys())}）")
    d = VENDOR_DEFAULTS[v]
    base_url = settings.llm_base_url or d["base_url"]
    api_key = get_vendor_api_key(v)
    model = settings.llm_model or d["default_model"]
    if not api_key:
        raise RuntimeError(
            f"未配置厂商 [{v}] 的 API Key。请在 .env 设置 TF_{v.upper()}_API_KEY 或通用 TF_LLM_API_KEY"
        )
    if d["kind"] == "anthropic":
        return AnthropicProvider(base_url, api_key, model)
    return OpenAICompatibleProvider(v, base_url, api_key, model)


# 单例缓存（按厂商）
_providers: dict[str, BaseProvider] = {}


def get_llm(vendor: str | None = None) -> BaseProvider:
    """获取 LLM Provider 单例（vendor 留空用 settings.llm_vendor）"""
    v = (vendor or settings.llm_vendor).lower()
    if v not in _providers:
        _providers[v] = get_provider(v)
    return _providers[v]


def get_embedder() -> OpenAICompatibleProvider | None:
    """Embedding 厂商（仅 OpenAI 兼容）；未配置 key 返回 None → 走本地 MiniLM"""
    v = settings.embedding_vendor.lower()
    d = VENDOR_DEFAULTS.get(v) or VENDOR_DEFAULTS["openai"]
    key = settings.embedding_api_key or get_vendor_api_key(v)
    if not key:
        return None
    base = settings.embedding_base_url or d["base_url"]
    return OpenAICompatibleProvider(v, base, key, settings.embedding_model)


async def test_vendor(vendor: str, prompt: str = "ping") -> dict:
    """连通性测试：用 1 token 级别的小请求验证厂商可用"""
    t0 = time.time()
    try:
        prov = get_provider(vendor)
        resp = await prov.chat(prompt, max_tokens=16, temperature=0)
        return {
            "vendor": vendor, "ok": True, "model": resp.model,
            "latency_ms": resp.latency_ms, "tokens_out": resp.tokens_out,
            "preview": resp.text[:80], "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {
            "vendor": vendor, "ok": False, "error": str(e)[:200],
            "elapsed_ms": int((time.time() - t0) * 1000),
        }


def extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（容忍前后多余文本与 markdown fence）"""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = 0
    for i, ch in enumerate(text):
        if ch in "[{":
            start = i
            break
    end = len(text)
    for j in range(len(text) - 1, start - 1, -1):
        if text[j] in "]}":
            end = j + 1
            break
    return json.loads(text[start:end])
