import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
        max_retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.timeout = timeout
        self.max_retries = max_retries
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        return await self._request(messages, temperature)

    async def chat_stream(
        self, messages: list[dict[str, str]], temperature: float = 0.2
    ) -> AsyncIterator[str]:
        """Yield DeepSeek Chat Completion tokens from its SSE response."""
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
        headers = self._headers()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                            content = event["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                            raise RuntimeError("DeepSeek 流式响应格式不正确") from exc
                        if content:
                            yield str(content)
            except httpx.TimeoutException as exc:
                raise RuntimeError("DeepSeek 请求超时，请稍后重试") from exc
            except httpx.HTTPStatusError as exc:
                raise self._status_error(exc.response.status_code) from exc

    async def chat_json(
        self, messages: list[dict[str, str]], temperature: float = 0.0
    ) -> dict[str, Any]:
        # DeepSeek's JSON output mode rejects a request with HTTP 400 unless
        # the prompt explicitly contains the word "JSON".  Enforce that
        # contract here so individual agents cannot accidentally disable all
        # structured extraction with a wording-only change.
        json_messages = [dict(message) for message in messages]
        if not any(
            "json" in str(message.get("content", "")).lower()
            for message in json_messages
        ):
            if json_messages and json_messages[0].get("role") == "system":
                json_messages[0]["content"] += "\n输出必须是有效的 JSON 对象。"
            else:
                json_messages.insert(
                    0,
                    {"role": "system", "content": "输出必须是有效的 JSON 对象。"},
                )
        content = await self._request(
            json_messages,
            temperature,
            response_format={"type": "json_object"},
        )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DeepSeek 未返回有效 JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("DeepSeek JSON 顶层必须是对象")  # noqa: TRY004
        return result

    async def _request(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
        headers = self._headers()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=payload
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError("DeepSeek 请求超时，请稍后重试") from exc
            except httpx.HTTPStatusError as exc:
                raise self._status_error(exc.response.status_code) from exc
            data: dict[str, Any] = response.json()
            try:
                return str(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError("DeepSeek 返回格式不正确") from exc

    def _client(self) -> httpx.AsyncClient:
        transport = self.transport or httpx.AsyncHTTPTransport(retries=self.max_retries)
        return httpx.AsyncClient(timeout=self.timeout, transport=transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _status_error(status: int) -> RuntimeError:
        if status == 401:
            message = "DeepSeek API Key 无效"
        elif status == 429:
            message = "DeepSeek 请求达到限流，请稍后重试"
        else:
            message = f"DeepSeek 服务返回错误（HTTP {status}）"
        return RuntimeError(message)
