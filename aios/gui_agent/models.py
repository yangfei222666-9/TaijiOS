"""Visual model adapters for TaijiOS GUI agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .operators import Screenshot


@dataclass(frozen=True)
class ModelResult:
    """Raw visual model response plus optional accounting metadata."""

    prediction: str
    response_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = field(default_factory=dict)


class VisualModel(Protocol):
    """Model interface consumed by the GUI agent loop."""

    def invoke(
        self,
        instruction: str,
        screenshot: Screenshot,
        history: list[dict],
        previous_response_id: str | None = None,
    ) -> ModelResult:
        """Return the next UI-TARS style action prediction."""


class TaijiGatewayVisualModel:
    """OpenAI-compatible VLM adapter backed by the TaijiOS Gateway."""

    def __init__(
        self,
        model: str,
        gateway_client=None,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ):
        from aios.gateway.client import GatewayClient

        self.model = model
        self.gateway_client = gateway_client or GatewayClient()
        self.system_prompt = system_prompt or (
            "You are a GUI agent. Return output in UI-TARS format with "
            "Thought: ... and Action: ..."
        )
        self.max_tokens = max_tokens
        self.temperature = temperature

    def invoke(
        self,
        instruction: str,
        screenshot: Screenshot,
        history: list[dict],
        previous_response_id: str | None = None,
    ) -> ModelResult:
        image_url = f"data:{screenshot.mime};base64,{screenshot.base64}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            *history,
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        result = self.gateway_client.chat_completions(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=False,
            **({"previous_response_id": previous_response_id} if previous_response_id else {}),
        )
        if not result.success:
            raise RuntimeError(f"gateway model call failed: {result.reason_code} {result.error}")
        return ModelResult(
            prediction=result.content,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            raw=result.raw,
        )
