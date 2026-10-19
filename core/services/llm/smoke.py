"""Live deployment check, invoked explicitly: python -m services.llm.smoke --live."""
import argparse
import asyncio
import json
from pathlib import Path

from . import ConfigurationError, LLMSettings, complete_json


async def run(*, live=False):
    try:
        settings = LLMSettings.from_env()
    except ConfigurationError:
        return {"status": "missing_configuration", "required": ["HUAWEI_MAAS_API_KEY", "HUAWEI_MAAS_MODEL"]}, 2
    if not live:
        return {"status": "configured", "model": settings.model, "live_call": False}, 0
    try:
        result = await complete_json(
            [{"role": "system", "content": 'Return valid JSON only: {"ok": true}.'}, {"role": "user", "content": "Confirm readiness."}],
            operation="extraction", max_tokens=1024,
            schema={"type": "object", "properties": {"ok": {"const": True}}, "required": ["ok"], "additionalProperties": False},
        )
        return {"status": "passed", "model": settings.model, "result": result}, 0
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    result, code = asyncio.run(run(live=args.live))
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
