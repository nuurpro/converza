"""Huawei MaaS text inference. All callers use this provider boundary."""
from .client import (
    ConfigurationError, HuaweiLLM, LLMSettings, StructuredOutputError,
    UnsupportedCapabilityError, complete, complete_json, complete_text, stream,
    legacy_complete,
)

__all__ = ["ConfigurationError", "HuaweiLLM", "LLMSettings", "StructuredOutputError", "UnsupportedCapabilityError", "complete", "complete_json", "complete_text", "stream", "legacy_complete"]
