from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, AsyncIterator

from jsonschema import ValidationError, validate
from openai import AsyncOpenAI, APIStatusError

logger = logging.getLogger("services.llm")
DEFAULT_BASE_URL = "https://api.modelarts-maas.ap-southeast-1.myhuaweicloud.com/v1"


class ConfigurationError(RuntimeError):
    """The explicitly configured Huawei deployment is unavailable."""


class UnsupportedCapabilityError(RuntimeError):
    """This text deployment cannot perform the requested capability."""


class StructuredOutputError(ValueError):
    """The deployment returned empty, truncated, or invalid structured output."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)
    model: str
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self):
        if not self.api_key.strip() or not self.model.strip():
            raise ConfigurationError("HUAWEI_MAAS_API_KEY and HUAWEI_MAAS_MODEL are required")
        if not self.base_url.startswith("https://"):
            raise ConfigurationError("HUAWEI_MAAS_BASE_URL must use HTTPS")

    @classmethod
    def from_env(cls) -> LLMSettings:
        return cls(api_key=os.getenv("HUAWEI_MAAS_API_KEY", "").strip(), model=os.getenv("HUAWEI_MAAS_MODEL", "").strip(), base_url=os.getenv("HUAWEI_MAAS_BASE_URL", DEFAULT_BASE_URL).strip())


def _retry_delay(exc: APIStatusError, attempt: int, jitter) -> float:
    delay = 2 ** attempt + jitter()
    header = exc.response.headers.get("Retry-After")
    if header:
        try:
            requested = float(header)
        except ValueError:
            try:
                requested = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                requested = 0
        delay = max(delay, requested)
    return min(30.0, max(0.0, delay))


def _tools(tools: list[dict] | None) -> list[dict] | None:
    if tools is None:
        return None
    return [tool if tool.get("type") == "function" else {"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""), "parameters": tool.get("input_schema", {"type": "object"})}} for tool in tools]


def _validate_tool_calls(message, tools):
    schemas = {tool["function"]["name"]: tool["function"].get("parameters", {}) for tool in (tools or [])}
    for call in message.tool_calls or []:
        if call.function.name not in schemas:
            raise StructuredOutputError("Deployment returned an unrequested tool")
        try:
            data = json.loads(call.function.arguments)
            if not isinstance(data, dict):
                raise StructuredOutputError("Tool arguments must be an object")
            validate(data, schemas[call.function.name])
        except (ValueError, ValidationError) as exc:
            raise StructuredOutputError("Deployment returned invalid tool arguments") from exc


class HuaweiLLM:
    def __init__(self, settings: LLMSettings | None = None, *, client=None, sleep=asyncio.sleep, jitter=random.random):
        self.settings = settings or LLMSettings.from_env()
        self.client = client or AsyncOpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url, max_retries=0, timeout=120.0)
        self._sleep = sleep
        self._jitter = jitter

    def _request(self, messages, operation, tools, kwargs):
        forbidden = {"model", "base_url", "api_key", "temperature", "stream"} & kwargs.keys()
        if forbidden:
            raise ConfigurationError("Deployment, temperature, and streaming are controlled by the shared Huawei client")
        for message in messages:
            content = message.get("content")
            if isinstance(content, list) and any(not isinstance(block, dict) or block.get("type") != "text" for block in content):
                raise UnsupportedCapabilityError("The Huawei text deployment does not support vision/audio input")
        request = {"model": self.settings.model, "messages": messages, "temperature": .7 if operation == "creative" else .1, **kwargs}
        if tools:
            request["tools"] = _tools(tools)
        return request

    def _log(self, operation, started, retries, usage, status):
        usage_data = usage.model_dump() if hasattr(usage, "model_dump") else usage
        logger.info("llm operation=%s model=%s latency_ms=%.1f retries=%s usage=%s status=%s", operation, self.settings.model, (time.monotonic() - started) * 1000, retries, json.dumps(usage_data), status)

    async def complete(self, messages: list[dict], *, operation="reasoning", tools=None, **kwargs):
        request = self._request(messages, operation, tools, kwargs)
        started = time.monotonic()
        for attempt in range(4):
            try:
                response = await self.client.chat.completions.create(**request)
                if not response.choices:
                    raise StructuredOutputError("Deployment returned no choices")
                if response.choices[0].finish_reason in ("length", "content_filter"):
                    raise StructuredOutputError("Deployment returned an incomplete response")
                _validate_tool_calls(response.choices[0].message, request.get("tools"))
                self._log(operation, started, attempt, response.usage, "success")
                return response
            except APIStatusError as exc:
                if exc.status_code not in (429, 503) or attempt == 3:
                    self._log(operation, started, attempt, None, "failure")
                    raise
                await self._sleep(_retry_delay(exc, attempt, self._jitter))

    async def complete_text(self, messages, *, operation="reasoning", **kwargs) -> str:
        response = await self.complete(messages, operation=operation, **kwargs)
        text = response.choices[0].message.content
        if not text or not text.strip():
            raise StructuredOutputError("Deployment returned no visible text")
        return text.strip()

    async def complete_json(self, messages, *, operation="extraction", schema=None, validator=None, **kwargs):
        # Parse locally: JSON response_format support varies by Huawei deployment.
        contract = (
            "Return only valid JSON, without Markdown fences or surrounding commentary. "
            "When returning quoted source spans, copy their exact characters without translation, "
            "transliteration, spelling correction or Unicode normalization."
        )
        if schema is not None:
            contract += "\nThe JSON output must satisfy this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
        text = await self.complete_text([{"role": "system", "content": contract}, *messages], operation=operation, **kwargs)
        try:
            data = json.loads(text)
            if not isinstance(data, (dict, list)):
                raise StructuredOutputError("JSON output must be an object or array")
            if schema is not None:
                validate(data, schema)
            if validator is not None:
                return validator.model_validate(data) if hasattr(validator, "model_validate") else validator(data)
            return data
        except (ValueError, TypeError, ValidationError) as exc:
            raise StructuredOutputError("Deployment returned invalid structured JSON") from exc

    async def stream(self, messages, *, operation="reasoning", tools=None, **kwargs) -> AsyncIterator[Any]:
        request = self._request(messages, operation, tools, kwargs)
        started = time.monotonic()
        visible = False
        usage = None
        for attempt in range(4):
            source = None
            try:
                source = await self.client.chat.completions.create(**request, stream=True)
                async for chunk in source:
                    usage = getattr(chunk, "usage", None) or usage
                    if any(getattr(choice, "finish_reason", None) in ("length", "content_filter") for choice in chunk.choices):
                        raise StructuredOutputError("Deployment returned an incomplete stream")
                    emitted = any(getattr(choice.delta, "content", None) or getattr(choice.delta, "tool_calls", None) for choice in chunk.choices)
                    # Do not leak role-only chunks from attempts that may be retried.
                    if emitted or visible or getattr(chunk, "usage", None):
                        visible = visible or bool(emitted)
                        yield chunk
                if not visible:
                    raise StructuredOutputError("Deployment returned no visible stream content")
                self._log(operation, started, attempt, usage, "success")
                return
            except APIStatusError as exc:
                if visible or exc.status_code not in (429, 503) or attempt == 3:
                    self._log(operation, started, attempt, usage, "failure")
                    raise
                await self._sleep(_retry_delay(exc, attempt, self._jitter))
            finally:
                if source is not None and hasattr(source, "close"):
                    await source.close()


@lru_cache(maxsize=1)
def _get_client(settings: LLMSettings) -> HuaweiLLM:
    return HuaweiLLM(settings)


def get_client() -> HuaweiLLM:
    return _get_client(LLMSettings.from_env())


async def complete(messages, *, operation="reasoning", tools=None, **kwargs):
    return await get_client().complete(messages, operation=operation, tools=tools, **kwargs)


async def complete_text(messages, *, operation="reasoning", **kwargs):
    return await get_client().complete_text(messages, operation=operation, **kwargs)


async def complete_json(messages, *, operation="extraction", schema=None, validator=None, **kwargs):
    return await get_client().complete_json(messages, operation=operation, schema=schema, validator=validator, **kwargs)


async def stream(messages, *, operation="reasoning", tools=None, **kwargs):
    async for chunk in get_client().stream(messages, operation=operation, tools=tools, **kwargs):
        yield chunk


async def legacy_complete(*, system, messages, tools=None, tool_choice=None, operation="tools", **kwargs):
    """Anthropic-shaped compatibility boundary for existing manager/ReAct code.

    Tool results are converted into OpenAI role=tool messages; returned tool
    arguments have already been checked against the declared tool schema.
    """
    system_text = system if isinstance(system, str) else "\n".join(block["text"] for block in system)
    converted = [{"role": "system", "content": system_text}]
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            converted.append(message)
            continue
        text_parts, calls = [], []
        for block in content:
            value = block if isinstance(block, dict) else vars(block)
            if value["type"] == "text":
                text_parts.append(value["text"])
            elif value["type"] == "tool_use":
                calls.append({"id": value["id"], "type": "function", "function": {"name": value["name"], "arguments": json.dumps(value["input"])}})
            elif value["type"] == "tool_result":
                converted.append({"role": "tool", "tool_call_id": value["tool_use_id"], "content": value["content"]})
            else:
                raise UnsupportedCapabilityError("Unsupported legacy message block")
        if calls or text_parts:
            converted.append({"role": message["role"], "content": "\n".join(text_parts) or None, **({"tool_calls": calls} if calls else {})})
    if tool_choice:
        kwargs["tool_choice"] = "required" if tool_choice.get("type") == "any" else "auto"
    response = await complete(converted, operation=operation, tools=tools, **kwargs)
    message = response.choices[0].message
    blocks = [SimpleNamespace(type="text", text=message.content)] if message.content else []
    blocks.extend(SimpleNamespace(type="tool_use", id=call.id, name=call.function.name, input=json.loads(call.function.arguments)) for call in (message.tool_calls or []))
    return SimpleNamespace(content=blocks, stop_reason="tool_use" if message.tool_calls else "end_turn")
