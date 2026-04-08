"""
coherent_engine LLM provider.
接口：.chat(system, user, model) -> (text, prompt_tokens, completion_tokens)
回退：任何异常抛出，由调用方（_build_shots_via_llm）降级到 mock。

支持两种 provider（优先级由环境变量控制）：
  COHERENT_LLM_PROVIDER=ollama   → OllamaLLMClient（本地，无需 Key）
  COHERENT_LLM_PROVIDER=anthropic → AnthropicLLMClient（需要 ANTHROPIC_API_KEY）
  未设置 → 自动探测：Ollama 在线则用 Ollama，否则用 Anthropic
"""
import hashlib
import json
import os
from typing import Any, Optional, Tuple


class OllamaLLMClient:
    """
    调用本地 Ollama OpenAI 兼容接口（http://localhost:11434/v1）。
    无需 API Key。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "gemma3:4b",
        timeout: float = 60.0,
    ):
        raw_base = (base_url or os.environ.get("OLLAMA_BASE_URL", "") or "http://localhost:11434").strip()
        raw_base = raw_base.rstrip("/")
        if raw_base.endswith("/v1"):
            raw_base = raw_base[:-3]
            raw_base = raw_base.rstrip("/")
        self.base_url = raw_base
        self._model = model or os.environ.get("OLLAMA_MODEL", "gemma3:4b")

        self.timeout = timeout

    def chat(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> Tuple[str, int, int]:
        """
        Returns (response_text, prompt_tokens, completion_tokens).
        Raises on error so caller can fallback.
        """
        import urllib.request
        import logging as _log

        _model = model or self._model
        payload = json.dumps({
            "model": _model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        import urllib.error
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if getattr(e, "code", None) == 404:
                try:
                    tags = json.loads(urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2).read().decode("utf-8"))
                    models = tags.get("models") or []
                    alt = (models[0].get("name") if models else "") or ""
                except Exception:
                    alt = ""
                if alt and alt != _model:
                    self._model = alt
                    _model = alt
                    payload = json.dumps({
                        "model": _model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "options": {"num_predict": max_tokens},
                    }, ensure_ascii=False).encode("utf-8")
                    req = urllib.request.Request(
                        f"{self.base_url}/api/chat",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                else:
                    raise
            else:
                raise

        if "choices" in data:
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        else:
            text = (data.get("message") or {}).get("content", "") or ""
            prompt_tokens = int(data.get("prompt_eval_count") or 0)
            completion_tokens = int(data.get("eval_count") or 0)
        text = text.strip()
        _log.getLogger(__name__).debug("ollama raw text=%r model=%s", text[:200], _model)
        return text, prompt_tokens, completion_tokens


class AnthropicLLMClient:
    """
    Thin wrapper around anthropic.Anthropic SDK.
    Raises on any error so callers can apply their own fallback.
    """

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("dep.anthropic.no_api_key: ANTHROPIC_API_KEY not set")
        import anthropic
        base_url = (os.environ.get("ANTHROPIC_BASE_URL", "") or "").strip()
        kwargs: dict = {"api_key": self.api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._model = "claude-sonnet-4-6"

    def chat(
        self,
        system: str,
        user: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 2048,
    ) -> Tuple[str, int, int]:
        """
        Returns (response_text, prompt_tokens, completion_tokens).
        Raises on API error / timeout.
        """
        msg = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # collect all text blocks (skip ThinkingBlock / dict type blocks)
        parts = []
        for block in (msg.content or []):
            if isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(block["text"])
            elif getattr(block, "type", "") == "text" and hasattr(block, "text"):
                parts.append(block.text)
        text = "\n".join(parts).strip()
        import logging as _log
        _log.getLogger(__name__).debug("llm_client raw text=%r content_types=%s",
            text[:200] if text else "",
            [getattr(b, 'type', type(b).__name__) for b in (msg.content or [])])
        usage = getattr(msg, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        return text, prompt_tokens, completion_tokens


class GatewayLLMClient:
    """
    通过 TaijiOS Gateway 调用 LLM。
    实现与 OllamaLLMClient / AnthropicLLMClient 相同的 .chat() 接口。
    """

    def __init__(self, timeout: float = 120.0):
        from aios.gateway.client import GatewayClient
        self._gw = GatewayClient(timeout_s=int(timeout))

    def chat(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> Tuple[str, int, int]:
        from aios.gateway.client import GatewayContext
        import logging as _log

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        ctx = GatewayContext(caller_type="coherent_engine", route_profile="default")
        result = self._gw.chat_completions(
            model=model or "qwen2.5:3b",
            messages=messages,
            max_tokens=max_tokens,
            ctx=ctx,
        )
        if not result.success:
            raise RuntimeError(f"Gateway 调用失败: {result.reason_code} {result.error}")

        _log.getLogger(__name__).debug("gateway raw text=%r model=%s",
            result.content[:200] if result.content else "", result.model)
        return result.content.strip(), result.prompt_tokens, result.completion_tokens


def _ollama_available(base_url: str = "http://localhost:11434") -> bool:
    """HEAD /api/tags — Ollama 在线返回 True，否则 False。"""
    import urllib.request
    try:
        urllib.request.urlopen(f"{base_url}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def prompt_hash(system: str, user: str) -> str:
    """SHA256 of system+user prompt for run_trace evidence."""
    h = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()
    return h[:16]


def plan_hash(plan: Any) -> str:
    """SHA256 of serialised plan dict."""
    h = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return h[:16]


def make_llm_client() -> Optional[Any]:
    """
    返回可用的 LLM client，优先级：
      0. Gateway 已启用且可用 → GatewayLLMClient
      1. COHERENT_LLM_PROVIDER=ollama  → OllamaLLMClient
      2. COHERENT_LLM_PROVIDER=anthropic → AnthropicLLMClient
      3. 自动探测：Ollama 在线 → OllamaLLMClient
      4. ANTHROPIC_API_KEY 存在 → AnthropicLLMClient
      5. 否则返回 None（调用方降级 mock）
    """
    import logging as _log
    _logger = _log.getLogger(__name__)

    # Gateway 优先路径
    if os.environ.get("TAIJIOS_GATEWAY_ENABLED", "").lower() in ("1", "true", "yes"):
        try:
            gw_client = GatewayLLMClient()
            if gw_client._gw.is_available():
                _logger.info("[llm_client] 使用 GatewayLLMClient")
                return gw_client
            _logger.warning("[llm_client] Gateway 已启用但不可用，回退到直连")
        except Exception as e:
            _logger.warning("[llm_client] Gateway 初始化失败: %s，回退到直连", e)

    provider = os.environ.get("COHERENT_LLM_PROVIDER", "").strip().lower()

    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
        return OllamaLLMClient(model=model)

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return None
        try:
            return AnthropicLLMClient(api_key=key)
        except Exception:
            return None

    # 自动探测
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if _ollama_available(ollama_url):
        model = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
        return OllamaLLMClient(model=model)

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        try:
            return AnthropicLLMClient(api_key=key)
        except Exception:
            return None

    return None
