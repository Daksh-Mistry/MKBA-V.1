"""No real API calls, keys or robot connections are used by these tests."""

import asyncio
import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat.provider import OpenAICompatibleProvider, ProviderError


MESSAGES = [{"role": "system", "content": "Be friendly"}, {"role": "user", "content": "Hi"}]


def completion(text="Hi!", **message_fields):
    return {"choices": [{
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": text, **message_fields},
    }]}


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_wire_request_uses_only_server_configuration(self):
        observed = []

        def handler(req):
            observed.append(req)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider("https://chat.example/v1/", "configured-model", "secret-test-key", client=client)
            self.assertEqual(await provider.complete(MESSAGES), "Hi!")
            request = observed[0]
            self.assertEqual(str(request.url), "https://chat.example/v1/chat/completions")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"], "Bearer secret-test-key")
            body = json.loads(request.content)
            self.assertEqual(body, {"model": "configured-model", "messages": MESSAGES, "stream": False, "max_tokens": 384})
            await provider.close()
            self.assertFalse(client.is_closed)
            self.assertFalse(provider.available)

    async def test_local_ollama_needs_no_api_key(self):
        def handler(req):
            self.assertNotIn("authorization", req.headers)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider("http://localhost:11434/v1", "local-model", client=client)
            self.assertTrue(provider.available)
            self.assertEqual(await provider.complete(MESSAGES), "Hi!")

    async def test_modern_token_limit_field_is_configurable_but_allowlisted(self):
        def handler(req):
            payload = json.loads(req.content)
            self.assertEqual(payload["max_completion_tokens"], 384)
            self.assertNotIn("max_tokens", payload)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                "https://chat.example/v1", "model", "key", client=client,
                token_limit_field="max_completion_tokens",
            )
            self.assertEqual(await provider.complete(MESSAGES), "Hi!")
        for field in ("tools", "messages", "temperature", ["max_tokens"]):
            with self.subTest(field=field), self.assertRaises(ValueError):
                OpenAICompatibleProvider("https://chat.example/v1", "model", "key", token_limit_field=field)

    async def test_missing_configuration_never_sends_request(self):
        def handler(req):
            self.fail("unconfigured provider must not contact the network")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for url, model, key in (("https://example.com/v1", "model", ""), ("", "model", "key"), ("https://example.com/v1", "", "key")):
                provider = OpenAICompatibleProvider(url, model, key, client=client)
                self.assertFalse(provider.available)
                with self.assertRaisesRegex(ProviderError, "provider_not_configured"):
                    await provider.complete(MESSAGES)

    async def test_http_errors_are_redacted_and_not_retried(self):
        for status, code in ((401, "provider_authentication"), (403, "provider_authentication"), (429, "provider_rate_limited"), (500, "provider_http_error"), (302, "provider_http_error")):
            calls = []

            def handler(req):
                calls.append(req)
                return httpx.Response(status, headers={"location": "https://leak.example"}, text="SECRET exception body")

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
                provider = OpenAICompatibleProvider("https://chat.example/v1", "model", "SECRET", client=client)
                with self.subTest(status=status), self.assertRaises(ProviderError) as error:
                    await provider.complete(MESSAGES)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("SECRET", str(error.exception))
                self.assertEqual(len(calls), 1)

    async def test_timeout_and_connection_errors_do_not_expose_details(self):
        for error, code in ((httpx.ReadTimeout("SECRET"), "provider_timeout"), (httpx.ConnectError("SECRET"), "provider_connection_error")):
            def handler(req):
                raise error

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                provider = OpenAICompatibleProvider("https://chat.example/v1", "model", "key", client=client)
                with self.assertRaises(ProviderError) as caught:
                    await provider.complete(MESSAGES)
                self.assertEqual(str(caught.exception), code)

    async def test_total_timeout_bounds_slow_provider(self):
        async def handler(req):
            await asyncio.sleep(.05)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider("https://chat.example/v1", "model", "key", timeout=.005, client=client)
            with self.assertRaisesRegex(ProviderError, "provider_timeout"):
                await provider.complete(MESSAGES)

    async def test_tools_and_malformed_responses_are_rejected(self):
        tool_result = completion(tool_calls=[{"function": {"name": "move", "arguments": "{}"}}])
        function_result = completion(function_call={"name": "pump_on", "arguments": "{}"})
        for data, code in (
            (tool_result, "provider_tools_not_allowed"),
            (function_result, "provider_tools_not_allowed"),
            ({"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "tool_calls"}]}, "provider_tools_not_allowed"),
            ({"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "length"}]}, "provider_incomplete_response"),
            ({"choices": []}, "provider_invalid_response"),
            ({"choices": "invalid"}, "provider_invalid_response"),
            ({"choices": [{"message": "invalid"}]}, "provider_invalid_response"),
            (completion(text=""), "provider_invalid_response"),
            (completion(text=[{"type": "text", "text": "Hi"}]), "provider_invalid_response"),
            (completion(text="x" * 4001), "provider_invalid_response"),
            (completion(role="user"), "provider_invalid_response"),
        ):
            with self.subTest(code=code, data=str(data)[:100]):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))) as client:
                    provider = OpenAICompatibleProvider("https://chat.example/v1", "model", "key", client=client)
                    with self.assertRaises(ProviderError) as caught:
                        await provider.complete(MESSAGES)
                    self.assertEqual(caught.exception.code, code)

    async def test_invalid_json_and_oversized_body_are_rejected(self):
        for content, code in ((b"not json", "provider_invalid_response"), (b"x" * 65537, "provider_response_too_large")):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=content))) as client:
                provider = OpenAICompatibleProvider("https://chat.example/v1", "model", "key", client=client)
                with self.assertRaisesRegex(ProviderError, code):
                    await provider.complete(MESSAGES)

    async def test_invalid_endpoints_and_input_never_send(self):
        for url in ("ftp://example.com", "http://example.com/v1", "https://user:key@example.com/v1", "https://example.com/v1?key=secret", "https://example.com/v1#fragment", "https://example.com:bad/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OpenAICompatibleProvider(url, "model", "key")
        provider = OpenAICompatibleProvider("http://localhost:11434/v1", "model")
        for messages in ([], MESSAGES * 8, [{"role": "tool", "content": "Hi"}], [{"role": [], "content": "Hi"}], [{"role": "user", "content": "Hi", "url": "https://other"}]):
            with self.assertRaises(ValueError):
                await provider.complete(messages)
        await provider.close()


if __name__ == "__main__":
    unittest.main()
