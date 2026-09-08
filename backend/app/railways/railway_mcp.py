"""Python mcp-server-12306 的 Streamable HTTP 适配器。

``mcp-server-12306`` 作为独立进程运行，本项目只负责通过标准 MCP
Streamable HTTP 协议调用它。这样可以避免把 12306 服务的运行依赖（以及
它要求的 MCP SDK 版本）混入主后端环境。
"""

import json
from typing import Any, Protocol

from backend.app.mcp.client import StreamableHttpMcpClient


class RailwayMcpClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class RailwayMcpProvider:
    """12306 MCP 工具适配器，保留真实车票/余票/经停/换乘数据。"""

    source_name = "12306 MCP"
    tool_names = frozenset(
        {
            "query-tickets",
            "query-ticket-price",
            "search-stations",
            "query-transfer",
            "get-train-route-stations",
            "get-train-no-by-train-code",
            "get-current-time",
        }
    )

    def __init__(
        self,
        endpoint: str,
        timeout: float = 30,
        client: RailwayMcpClient | None = None,
    ) -> None:
        self.endpoint = endpoint.strip()
        # The official server does not require an API key.  Its endpoint is
        # still protected by the caller's network boundary or reverse proxy.
        self.client = client or StreamableHttpMcpClient(
            self.endpoint,
            require_api_key=False,
            timeout=timeout,
        )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.tool_names:
            raise RuntimeError(f"12306 MCP 不支持工具：{name}")
        if not self.configured:
            raise RuntimeError("12306 MCP Endpoint 未配置")
        payload = await self.client.call_tool(name, arguments)
        result = self._decode_payload(payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"12306 MCP 工具 {name} 返回格式错误")  # noqa: TRY004
        return result

    async def query_tickets(
        self, from_station: str, to_station: str, train_date: str
    ) -> dict[str, Any]:
        return await self.call_tool(
            "query-tickets",
            {
                "from_station": from_station,
                "to_station": to_station,
                "train_date": train_date,
            },
        )

    async def query_transfer(
        self, from_station: str, to_station: str, train_date: str
    ) -> dict[str, Any]:
        return await self.call_tool(
            "query-transfer",
            {
                "from_station": from_station,
                "to_station": to_station,
                "train_date": train_date,
                "isShowWZ": "N",
                "purpose_codes": "00",
            },
        )

    async def query_price(
        self,
        from_station: str,
        to_station: str,
        train_date: str,
        train_code: str = "",
    ) -> dict[str, Any]:
        arguments = {
            "from_station": from_station,
            "to_station": to_station,
            "train_date": train_date,
            "purpose_codes": "ADULT",
        }
        if train_code:
            arguments["train_code"] = train_code
        return await self.call_tool("query-ticket-price", arguments)

    async def search_stations(self, query: str, limit: int = 10) -> dict[str, Any]:
        return await self.call_tool(
            "search-stations", {"query": query, "limit": max(1, min(limit, 50))}
        )

    async def train_stops(
        self,
        train_no: str,
        from_station: str,
        to_station: str,
        train_date: str,
    ) -> dict[str, Any]:
        return await self.call_tool(
            "get-train-route-stations",
            {
                "train_no": train_no,
                "from_station": from_station,
                "to_station": to_station,
                "train_date": train_date,
            },
        )

    async def current_time(self) -> dict[str, Any]:
        return await self.call_tool(
            "get-current-time", {"timezone": "Asia/Shanghai", "format": "YYYY-MM-DD"}
        )

    @staticmethod
    def _decode_payload(value: Any) -> Any:
        """Decode SDK output and tolerate old HTTP proxy wrappers."""
        if isinstance(value, dict):
            # Some reverse proxies return the JSON-RPC result envelope instead
            # of the SDK's already-decoded tool payload.
            if isinstance(value.get("result"), dict):
                value = value["result"]
            if "structuredContent" in value and isinstance(
                value["structuredContent"], dict
            ):
                value = value["structuredContent"]
            if isinstance(value.get("content"), list):
                text = "\n".join(
                    str(item.get("text"))
                    for item in value["content"]
                    if isinstance(item, dict) and item.get("text")
                )
                if text:
                    return RailwayMcpProvider._decode_payload(text)
            return value
        if isinstance(value, list):
            text = "\n".join(
                str(item.get("text"))
                for item in value
                if isinstance(item, dict) and item.get("text")
            )
            return RailwayMcpProvider._decode_payload(text) if text else value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
