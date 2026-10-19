from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..settings import get_settings
from .tracing import TraceContext
from ..observability import LLM_CALLS


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int

    @property
    def usage(self) -> dict[str, int]:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


class DeepSeekProvider:
    """OpenAI-compatible DeepSeek adapter with explicit model and cost metadata."""

    pricing_per_million = {
        "deepseek-chat": {"input": 0.27, "output": 1.10},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    }

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if self.settings.deepseek_api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self.settings.deepseek_api_key,
                    base_url=self.settings.deepseek_base_url,
                    timeout=self.settings.deepseek_timeout_seconds,
                )
            except Exception:
                self._client = None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def complete(
        self,
        *,
        system: str,
        user: str,
        trace: TraceContext,
        complex_reasoning: bool = False,
    ) -> LLMResult:
        if self._client is None:
            raise LLMUnavailable("DEEPSEEK_API_KEY is not configured")
        model = self.settings.deepseek_reasoner_model if complex_reasoning else self.settings.deepseek_chat_model
        started = time.perf_counter()
        trace.event("llm", model=model, status="started")
        response = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    temperature=0.1,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                break
            except Exception as exc:
                last_error = exc
                trace.event("llm", model=model, status="retry", attempt=attempt + 1, error=str(exc)[:240])
                if attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
        if response is None:
            LLM_CALLS.labels(model, "failed").inc()
            raise LLMUnavailable(str(last_error or "DeepSeek request failed")) from last_error
        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        pricing = self.pricing_per_million.get(model, {"input": 0.0, "output": 0.0})
        cost = prompt_tokens / 1_000_000 * pricing["input"] + completion_tokens / 1_000_000 * pricing["output"]
        latency_ms = round((time.perf_counter() - started) * 1000)
        trace.model = model
        LLM_CALLS.labels(model, "ok").inc()
        trace.event("llm", model=model, status="ok", latency_ms=latency_ms, usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}, cost_usd=cost)
        return LLMResult(
            text=str(response.choices[0].message.content or "").strip(),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

