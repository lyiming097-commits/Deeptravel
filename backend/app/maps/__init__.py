"""地图服务 Provider。"""

from typing import Any, Protocol

from backend.app.maps.amap_mcp import AmapMcpProvider
from backend.app.maps.mock import MockMapProvider


class MapProvider(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


__all__ = ["AmapMcpProvider", "MapProvider", "MockMapProvider"]
