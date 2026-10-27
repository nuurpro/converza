"""Deterministic Huawei contract tests: no network or secrets."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from openai import AsyncOpenAI, APIStatusError

from services.llm import HuaweiLLM, LLMSettings, ConfigurationError, StructuredOutputError, UnsupportedCapabilityError

MESSAGES = [{"role": "user", "content": "private buyer message"}]


def completion(content="hello", tool_calls=None):
    return {"id": "test", "object": "chat.completion", "created": 1, "model": "deployment", "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}


class HuaweiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = LLMSettings(api_key="test-key", model="deployment")
        self.sleep = AsyncMock()
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()

    def make(self, handler):
        sdk = AsyncOpenAI(api_key="test-key", base_url=self.settings.base_url, max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        self.clients.append(sdk)
        return HuaweiLLM(self.settings, client=sdk, sleep=self.sleep, jitter=lambda: 0)

    def test_requires_key_and_model_and_default_base(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ConfigurationError):
                LLMSettings.from_env()
        with patch.dict("os.environ", {"HUAWEI_MAAS_API_KEY": "test-key"}, clear=True):
            with self.assertRaises(ConfigurationError):
                LLMSettings.from_env()
        self.assertEqual(self.settings.base_url, "https://api.modelarts-maas.ap-southeast-1.myhuaweicloud.com/v1")

    async def test_request_uses_deployment_temperatures_and_sdk_response(self):
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            return httpx.Response(200, json=completion())
        client = self.make(handler)
        for operation in ("extraction", "tools", "reasoning", "creative"):
            result = await client.complete(MESSAGES, operation=operation)
            self.assertEqual(result.choices[0].message.content, "hello")
        self.assertEqual([r["temperature"] for r in requests], [.1, .1, .1, .7])
        self.assertTrue(all(r["model"] == "deployment" for r in requests))

    async def test_retry_only_429_and_503_initial_plus_three(self):
        for status in (429, 503, 400, 401, 500):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"error": {"message": "failure"}})
            client = self.make(handler)
            with self.assertRaises(APIStatusError):
                await client.complete(MESSAGES)
            self.assertEqual(len(calls), 4 if status in (429, 503) else 1)
        self.assertEqual([c.args[0] for c in self.sleep.await_args_list], [1, 2, 4, 1, 2, 4])

    async def test_retry_after_is_bounded_and_success_logs_no_content(self):
        calls = []
        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "9999"}, json={"error": {"message": "failure"}})
            return httpx.Response(200, json=completion())
        client = self.make(handler)
        with self.assertLogs("services.llm", level="INFO") as logs:
            self.assertEqual(await client.complete_text(MESSAGES), "hello")
        self.assertEqual(self.sleep.await_args.args[0], 30)
        output = " ".join(logs.output)
        for sensitive in ("private buyer message", "test-key"):
            self.assertNotIn(sensitive, output)
        for field in ("operation=reasoning", "model=deployment", "retries=1", "usage=", "latency_ms="):
            self.assertIn(field, output)

    async def test_json_parse_and_schema_validation_fail_closed(self):
        for content in ("not json", '"scalar"', '{"name": 3}'):
            client = self.make(lambda request: httpx.Response(200, json=completion(content)))
            with self.assertRaises(StructuredOutputError):
                await client.complete_json(MESSAGES, schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
        client = self.make(lambda request: httpx.Response(200, json=completion('{"name":"valid"}')))
        self.assertEqual(await client.complete_json(MESSAGES), {"name": "valid"})

    async def test_json_contract_reaches_model_without_mutating_caller_messages(self):
        schema = {"type": "object", "properties": {"kind": {"enum": ["customer_copy", "internal_recommendation"]}}, "required": ["kind"], "additionalProperties": False}
        messages = [{"role": "system", "content": "Classify the requested output."}, {"role": "user", "content": "Draft a launch email."}]
        original = json.loads(json.dumps(messages))
        def handler(request):
            sent = json.loads(request.content)["messages"]
            instructions = "\n".join(row["content"] for row in sent if row["role"] == "system")
            self.assertIn("JSON", instructions)
            self.assertIn(json.dumps(schema, ensure_ascii=False), instructions)
            self.assertIn("Classify the requested output.", instructions)
            self.assertEqual(sent[-1], messages[-1])
            return httpx.Response(200, json=completion('{"kind":"customer_copy"}'))
        client = self.make(handler)
        self.assertEqual(await client.complete_json(messages, schema=schema), {"kind": "customer_copy"})
        self.assertEqual(messages, original)

    async def test_rejects_vision_and_provider_override_without_network(self):
        handler = AsyncMock()
        client = self.make(handler)
        with self.assertRaises(UnsupportedCapabilityError):
            await client.complete([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}]}])
        with self.assertRaises(ConfigurationError):
            await client.complete(MESSAGES, model="other-provider")
        handler.assert_not_called()

    async def test_tools_keep_sdk_interface_and_validate_arguments(self):
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}}]
        for arguments, valid in (('{"sku":"A"}', True), ('{"sku":2}', False), ("broken", False)):
            calls = [{"id": "tool-1", "type": "function", "function": {"name": "lookup", "arguments": arguments}}]
            client = self.make(lambda request: httpx.Response(200, json=completion(None, calls)))
            if valid:
                result = await client.complete(MESSAGES, tools=tools)
                self.assertEqual(result.choices[0].message.tool_calls[0].id, "tool-1")
            else:
                with self.assertRaises(StructuredOutputError):
                    await client.complete(MESSAGES, tools=tools)

    async def test_stream_retries_before_token_but_never_after_visible_output(self):
        def chunk(text):
            return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)
        async def first_failure():
            yield chunk(None)
            raise APIStatusError("busy", response=httpx.Response(503, request=httpx.Request("POST", "https://example.com")), body=None)
        async def success():
            yield chunk("hello")
        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=[first_failure(), success()]))))
        client = HuaweiLLM(self.settings, client=sdk, sleep=self.sleep, jitter=lambda: 0)
        chunks = [part async for part in client.stream(MESSAGES)]
        self.assertEqual([part.choices[0].delta.content for part in chunks], ["hello"])
        self.assertEqual(sdk.chat.completions.create.await_count, 2)
        async def partial_failure():
            yield chunk("visible")
            raise APIStatusError("busy", response=httpx.Response(429, request=httpx.Request("POST", "https://example.com")), body=None)
        sdk.chat.completions.create = AsyncMock(return_value=partial_failure())
        seen = []
        with self.assertRaises(APIStatusError):
            async for part in client.stream(MESSAGES):
                seen.append(part.choices[0].delta.content)
        self.assertEqual(seen, ["visible"])
        sdk.chat.completions.create.assert_awaited_once()

    async def test_sdk_retries_disabled_on_owned_client(self):
        with patch("services.llm.client.AsyncOpenAI") as sdk:
            HuaweiLLM(self.settings)
        self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_engine_preserves_text_contract_and_operation(self):
        from lib.engine import call_engine
        with patch("services.llm.complete_text", AsyncMock(return_value="copy")) as complete_text:
            result = await call_engine("system", "request", operation="creative")
        self.assertEqual(result, "copy")
        complete_text.assert_awaited_once_with([{"role": "system", "content": "system"}, {"role": "user", "content": "request"}], operation="creative", max_tokens=4096)

    async def test_legacy_adapter_roundtrips_tool_history_and_validates_response(self):
        from services.llm import legacy_complete
        from openai.types.chat import ChatCompletion
        calls = [{"id": "tool-1", "type": "function", "function": {"name": "lookup", "arguments": '{"sku":"A"}'}}]
        response = ChatCompletion.model_validate(completion(None, calls))
        tools = [{"name": "lookup", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}]
        history = [{"role": "assistant", "content": [SimpleNamespace(type="tool_use", name="lookup", id="old", input={"sku": "old"})]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old", "content": "found"}]}]
        with patch("services.llm.client.complete", AsyncMock(return_value=response)) as call:
            result = await legacy_complete(system="system", messages=history, tools=tools, tool_choice={"type": "any"})
        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0].input, {"sku": "A"})
        messages = call.await_args.args[0]
        self.assertEqual(messages[1]["tool_calls"][0]["id"], "old")
        self.assertEqual(messages[2], {"role": "tool", "tool_call_id": "old", "content": "found"})
        self.assertEqual(call.await_args.kwargs["tool_choice"], "required")

class AdditionalContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_http_date_and_jitter(self):
        from services.llm.client import _retry_delay
        from email.utils import format_datetime
        from datetime import datetime, timedelta, timezone
        error = APIStatusError("busy", response=httpx.Response(503, headers={"Retry-After": format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20))}, request=httpx.Request("POST", "https://example.com")), body=None)
        self.assertGreater(_retry_delay(error, 0, lambda: .5), 18)
        self.assertLessEqual(_retry_delay(error, 0, lambda: .5), 20)
        error.response.headers["Retry-After"] = "garbage"
        self.assertEqual(_retry_delay(error, 1, lambda: .5), 2.5)

    async def test_truncated_and_empty_outputs_are_not_used(self):
        from openai.types.chat import ChatCompletion
        for reason in ("length", "content_filter"):
            payload = completion("partial")
            payload["choices"][0]["finish_reason"] = reason
            sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=ChatCompletion.model_validate(payload)))))
            client = HuaweiLLM(LLMSettings(api_key="test", model="deployment"), client=sdk)
            with self.assertRaises(StructuredOutputError):
                await client.complete(MESSAGES)
        payload = completion("")
        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=ChatCompletion.model_validate(payload)))))
        client = HuaweiLLM(LLMSettings(api_key="test", model="deployment"), client=sdk)
        with self.assertRaises(StructuredOutputError):
            await client.complete_text(MESSAGES)

    async def test_stream_tool_fragments_are_visible_and_not_replayed(self):
        async def chunks():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[{"index": 0, "id": "t1"}]))], usage=None)
            raise APIStatusError("busy", response=httpx.Response(503, request=httpx.Request("POST", "https://example.com")), body=None)
        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=chunks()))))
        client = HuaweiLLM(LLMSettings(api_key="test", model="deployment"), client=sdk)
        seen = []
        with self.assertRaises(APIStatusError):
            async for part in client.stream(MESSAGES):
                seen.append(part)
        self.assertEqual(len(seen), 1)
        sdk.chat.completions.create.assert_awaited_once()

    async def test_live_smoke_reports_missing_config_without_call(self):
        from services.llm.smoke import run
        with patch.dict("os.environ", {}, clear=True), patch("services.llm.smoke.complete_json", AsyncMock()) as call:
            result, code = await run(live=True)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "missing_configuration")
        call.assert_not_called()

    def test_extraction_eval_fixtures_detect_invented_quotes_and_stale_prices(self):
        from services.llm.evals import load_cases, score_case
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            self.assertTrue(score_case(case, case["expected"]))
            self.assertFalse(score_case(case, {"invented": "answer"}))


class DeploymentImportTests(unittest.TestCase):
    def test_manager_standalone_launch_can_find_shared_client(self):
        import os
        import subprocess
        from pathlib import Path
        script = '''import sys, types
stub = types.ModuleType("db.client")
for name in ("sb", "SALES_BOT_TOKEN", "get_org_by_owner", "get_org_by_group", "get_passport", "get_stats", "create_org", "update_connection", "update_passport", "update_org_name", "send_telegram"):
    setattr(stub, name, None)
sys.modules["db.client"] = stub
import agents.manager
print("imported")
'''
        env = {**os.environ, "PYTHONPATH": ""}
        result = subprocess.run([__import__("sys").executable, "-c", script], cwd=Path(__file__).resolve().parents[1] / "manager", env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("imported", result.stdout)

    def test_settings_repr_does_not_expose_credentials(self):
        self.assertNotIn("secret-value", repr(LLMSettings(api_key="secret-value", model="deployment")))

class StreamOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_empty_or_truncated_response_fails_explicitly(self):
        for finish_reason in ("stop", "length", "content_filter"):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason=finish_reason)], usage=None)
            sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=chunks()))))
            client = HuaweiLLM(LLMSettings(api_key="test", model="deployment"), client=sdk)
            with self.assertRaises(StructuredOutputError):
                async for _ in client.stream(MESSAGES):
                    pass

class EvalCliTests(unittest.TestCase):
    def test_eval_cli_loads_core_env_and_has_paid_call_gate(self):
        from pathlib import Path
        from services.llm import evals
        import io
        with patch("sys.argv", ["evals"]), patch("services.llm.evals.evaluate", AsyncMock()) as run, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(evals.main(), 0)
            run.assert_not_called()
        with patch("sys.argv", ["evals", "--live"]), patch("dotenv.load_dotenv") as dotenv, patch("services.llm.evals.evaluate", AsyncMock(return_value={"score": 1.0})), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(evals.main(), 0)
        self.assertEqual(dotenv.call_args.args[0], Path(__file__).resolve().parents[1] / ".env")
