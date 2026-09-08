"""Small, text-only adapter for a configured Chat Completions endpoint."""

from __future__ import annotations

import asyncio
import json
import math
from urllib.parse import urlsplit

import httpx


class ProviderError(RuntimeError):
    """Only a stable code escapes the adapter, never provider bodies or secrets."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OpenAICompatibleProvider:
    """Configuration belongs to the server, not individual chat requests.

    Token limit fields vary between providers and model families. The configured
    field is restricted to the two supported names. An injected AsyncClient
    remains owned by its caller. No request is retried.
    """

    RESPONSE_BYTE_LIMIT = 65536
    TEXT_LIMIT = 4000

    def __init__(
        self, base_url: str, model: str, api_key: str = "", timeout: float = 20,
        client: httpx.AsyncClient | None = None,
        token_limit_field: str = "max_tokens",
    ):
        if not isinstance(base_url, str) or not isinstance(model, str):
            raise ValueError("Provider endpoint and model must be strings")
        if not isinstance(api_key, str) or any(ord(c) < 32 for c in api_key):
            raise ValueError("Invalid provider API key configuration")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("Provider timeout must be a number")
        if not 0 < timeout <= 120 or not math.isfinite(timeout):
            raise ValueError("Provider timeout must be greater than 0 and at most 120")
        if not isinstance(token_limit_field, str) or token_limit_field not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Unsupported provider token limit field")
        if len(model) > 128 or any(ord(c) < 32 for c in model):
            raise ValueError("Invalid provider model configuration")
        self._url = ""
        self._local = False
        if base_url.strip():
            try:
                parsed = urlsplit(base_url.strip())
                valid_port = parsed.port  # Forces validation without logging the URL.
                del valid_port
                self._local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                valid = (
                    parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                    and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment
                    and (parsed.scheme == "https" or self._local)
                    and not any(c.isspace() for c in base_url.strip())
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Provider URL must be HTTPS, or HTTP on loopback, without credentials or query")
            self._url = base_url.strip().rstrip("/") + "/chat/completions"
        self._model = model.strip()
        self._api_key = api_key.strip()
        self._timeout = timeout
        self._token_limit_field = token_limit_field
        self._owns_client = client is None
        self._client = client
        self._closed = False

    @property
    def available(self) -> bool:
        return bool(self._url and self._model and (self._api_key or self._local)) and not self._closed

    async def complete(self, messages: list[dict]) -> str:
        if not self.available:
            raise ProviderError("provider_not_configured")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 14:
            raise ValueError("Provider messages must contain 1 to 14 items")
        for item in messages:
            if not isinstance(item, dict) or set(item) != {"role", "content"}:
                raise ValueError("Invalid provider message")
            if not isinstance(item["role"], str) or item["role"] not in {"system", "user", "assistant"}:
                raise ValueError("Invalid provider message role")
            if not isinstance(item["content"], str) or not 1 <= len(item["content"]) <= 8000:
                raise ValueError("Invalid provider message content")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, trust_env=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        payload = {
            "model": self._model, "messages": messages, "stream": False,
            self._token_limit_field: 384,
        }
        try:
            # The total deadline also bounds a provider that drips response bytes.
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST", self._url, headers=headers, json=payload,
                    timeout=self._timeout, follow_redirects=False,
                ) as response:
                    status = response.status_code
                    if status in {401, 403}:
                        raise ProviderError("provider_authentication")
                    if status == 429:
                        raise ProviderError("provider_rate_limited")
                    if not 200 <= status < 300:
                        raise ProviderError("provider_http_error")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.RESPONSE_BYTE_LIMIT:
                            raise ProviderError("provider_response_too_large")
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError("provider_timeout") from None
        except httpx.HTTPError:
            raise ProviderError("provider_connection_error") from None
        try:
            result = json.loads(body)
            choices = result["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if message.get("tool_calls") or message.get("function_call"):
                raise ProviderError("provider_tools_not_allowed")
            if choice.get("finish_reason") in {"tool_calls", "function_call"}:
                raise ProviderError("provider_tools_not_allowed")
            if choice.get("finish_reason") != "stop":
                raise ProviderError("provider_incomplete_response")
            content = message["content"]
            if message.get("role") != "assistant" or not isinstance(content, str):
                raise ValueError
            text = content.strip()
            if not text or len(text) > self.TEXT_LIMIT:
                raise ValueError
            return text
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise ProviderError("provider_invalid_response") from None

    async def close(self) -> None:
        self._closed = True
        if self._client is not None and self._owns_client:
            await self._client.aclose()
