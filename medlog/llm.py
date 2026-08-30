"""Claude access. One place so model choice, effort and token accounting are
consistent, and so the eval harness can measure every call the same way."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from medlog.config import get_settings

T = TypeVar("T", bound=BaseModel)


@lru_cache
def client() -> anthropic.Anthropic:
    s = get_settings()
    s.require("anthropic_api_key")
    return anthropic.Anthropic(api_key=s.anthropic_api_key)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: float = 0.0

    # $ per 1M tokens, from the published rates for the models we use.
    PRICES: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0)},
        repr=False,
    )

    @property
    def cost_usd(self) -> float:
        pin, pout = self.PRICES.get(self.model, (5.0, 25.0))
        return self.input_tokens / 1e6 * pin + self.output_tokens / 1e6 * pout


def _usage(resp: Any, model: str, ms: float) -> Usage:
    u = getattr(resp, "usage", None)
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        model=model,
        latency_ms=ms,
    )


def _text(resp: Any) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def complete(
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 16000,
    effort: str = "high",
    thinking: bool = True,
) -> tuple[str, Usage]:
    """Plain text completion."""
    import time

    m = model or get_settings().medlog_reasoning_model
    kwargs: dict[str, Any] = {
        "model": m,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort},
    }
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}

    t0 = time.perf_counter()
    resp = client().messages.create(**kwargs)
    ms = (time.perf_counter() - t0) * 1000
    return _text(resp), _usage(resp, m, ms)


def parse(
    system: str,
    user: str,
    schema: type[T],
    model: str | None = None,
    max_tokens: int = 16000,
    effort: str = "high",
) -> tuple[T, Usage]:
    """Structured output. Validation happens server-side against the schema, so
    there is no JSON to salvage from prose -- which matters because assistant
    prefill was removed on the Claude 5 models."""
    import time

    m = model or get_settings().medlog_reasoning_model
    t0 = time.perf_counter()
    resp = client().messages.parse(
        model=m,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    )
    ms = (time.perf_counter() - t0) * 1000
    return resp.parsed_output, _usage(resp, m, ms)


def count_tokens(system: str, user: str, model: str | None = None) -> int:
    """Exact prompt size via the API. Used by the ablation -- an approximation
    would undercut the one number the whole comparison rests on."""
    m = model or get_settings().medlog_chat_model
    r = client().messages.count_tokens(
        model=m, system=system, messages=[{"role": "user", "content": user}]
    )
    return int(r.input_tokens)
