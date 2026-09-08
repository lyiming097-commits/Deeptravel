import json
import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client


class McpClient:
    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        auth_header: str = "Authorization",
        timeout: float = 15,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.auth_header = auth_header
        self.timeout = timeout

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.endpoint:
            raise RuntimeError(f"MCP Endpoint 未配置：{name}")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header] = (
                f"Bearer {self.api_key}"
                if self.auth_header.lower() == "authorization"
                else self.api_key
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.endpoint}/tools/{name}", headers=headers, json=arguments
            )
            response.raise_for_status()
            return response.json()


class StreamableHttpMcpClient:
    """标准 MCP Streamable HTTP 客户端。"""

    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        *,
        api_key_query_name: str = "key",
        require_api_key: bool = True,
        timeout: float = 30,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.api_key_query_name = api_key_query_name
        self.require_api_key = require_api_key
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        if not self.endpoint:
            return False
        if not self.require_api_key:
            return True
        query = dict(parse_qsl(urlsplit(self.endpoint).query, keep_blank_values=True))
        return bool(self.api_key or query.get(self.api_key_query_name))

    async def list_tools(self) -> list[dict[str, Any]]:
        async def operation(session: ClientSession) -> list[dict[str, Any]]:
            result = await session.list_tools()
            return [tool.model_dump(by_alias=True) for tool in result.tools]

        return await self._run(operation)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        async def operation(session: ClientSession) -> Any:
            result = await session.call_tool(name, arguments)
            decoded = self._decode_result(result)
            if result.isError:
                message = decoded if isinstance(decoded, str) else json.dumps(
                    decoded, ensure_ascii=False
                )
                raise RuntimeError(f"MCP 工具调用失败（{name}）：{message}")
            return decoded

        return await self._run(operation)

    async def _run(self, operation):
        if not self.configured:
            raise RuntimeError("MCP Streamable HTTP Endpoint 或 API Key 未配置")
        url = self._authenticated_url()
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client,
                streamable_http_client(url, http_client=client) as (read, write, _),
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self.timeout),
                ) as session,
            ):
                await session.initialize()
                return await operation(session)
        except RuntimeError:
            raise
        except Exception as exc:
            # AnyIO wraps connection/protocol failures in an ExceptionGroup;
            # expose the useful leaf error instead of the opaque
            # "unhandled errors in a TaskGroup" message.
            safe_message = self._sanitise(self._leaf_error(exc))
            raise RuntimeError(f"MCP Streamable HTTP 调用失败：{safe_message}") from exc

    @staticmethod
    def _leaf_error(exc: BaseException) -> str:
        nested = getattr(exc, "exceptions", None)
        if nested:
            for child in nested:
                message = StreamableHttpMcpClient._leaf_error(child)
                if message:
                    return message
        return str(exc) or exc.__class__.__name__

    def _authenticated_url(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qsl(parts.query, keep_blank_values=True)
        if self.api_key:
            query = [(key, value) for key, value in query if key != self.api_key_query_name]
            query.append((self.api_key_query_name, self.api_key))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _sanitise(self, message: str) -> str:
        if self.api_key:
            message = message.replace(self.api_key, "<redacted>")
        return re.sub(r"([?&]key=)[^&\s]+", r"\1<redacted>", message)

    @staticmethod
    def _decode_result(result: types.CallToolResult) -> Any:
        if result.structuredContent is not None:
            return result.structuredContent
        text_parts = [
            content.text for content in result.content if isinstance(content, types.TextContent)
        ]
        if not text_parts:
            return {"content": [content.model_dump(by_alias=True) for content in result.content]}
        text = "\n".join(text_parts)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
