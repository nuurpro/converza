"""Legacy streaming import preserved while inference uses Huawei MaaS."""
from typing import AsyncGenerator
from services.llm import ConfigurationError, stream


async def stream_gemini(messages: list[dict], system_prompt: str | None = None, model: str | None = None, max_tokens: int = 4096, *, operation: str = "reasoning") -> AsyncGenerator[str, None]:
    """Yield visible text tokens using the configured Huawei deployment.

    The historical function name is retained for callers; a provider/model
    override is rejected so an old caller cannot silently change deployments.
    """
    if model is not None:
        raise ConfigurationError("Set HUAWEI_MAAS_MODEL to select the text deployment")
    context = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + list(messages)
    async for chunk in stream(context, operation=operation, max_tokens=max_tokens):
        for choice in chunk.choices:
            if choice.delta.content:
                yield choice.delta.content
