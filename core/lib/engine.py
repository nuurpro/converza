"""Stateless text engine backed exclusively by the shared Huawei client."""
from __future__ import annotations
from typing import Any
from services import llm


async def call_engine(system_prompt: str, user_input: str, tools: list[dict[str, Any]] | None = None, *, operation: str = "reasoning") -> str:
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    kwargs: dict[str, Any] = {"operation": operation, "max_tokens": 4096}
    if tools:
        kwargs["tools"] = tools
    return await llm.complete_text(messages, **kwargs)
