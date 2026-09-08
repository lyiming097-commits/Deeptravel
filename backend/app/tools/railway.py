"""12306 MCP 的 Agent 工具边界。"""

from typing import Any

from backend.app.railways import RailwayMcpProvider


class RailwayMcpTool:
    """向路线 Agent 暴露语义化铁路工具，不泄露 MCP 协议细节。"""

    tickets_name = "railway_tickets"
    transfer_name = "railway_transfer"
    price_name = "railway_price"
    stops_name = "railway_stops"
    stations_name = "railway_stations"
    current_time_name = "railway_current_time"
    names = frozenset(
        {
            tickets_name,
            transfer_name,
            price_name,
            stops_name,
            stations_name,
            current_time_name,
        }
    )

    def __init__(self, provider: RailwayMcpProvider) -> None:
        self.provider = provider

    @property
    def configured(self) -> bool:
        return self.provider.configured

    async def tickets(
        self, from_station: str, to_station: str, train_date: str
    ) -> dict[str, Any]:
        return await self.provider.query_tickets(from_station, to_station, train_date)

    async def transfers(
        self, from_station: str, to_station: str, train_date: str
    ) -> dict[str, Any]:
        return await self.provider.query_transfer(from_station, to_station, train_date)

    async def prices(
        self,
        from_station: str,
        to_station: str,
        train_date: str,
        train_code: str = "",
    ) -> dict[str, Any]:
        return await self.provider.query_price(
            from_station, to_station, train_date, train_code
        )

    async def stops(
        self,
        train_no: str,
        from_station: str,
        to_station: str,
        train_date: str,
    ) -> dict[str, Any]:
        return await self.provider.train_stops(
            train_no, from_station, to_station, train_date
        )

    async def stations(self, query: str, limit: int = 10) -> dict[str, Any]:
        return await self.provider.search_stations(query, limit)

    async def current_time(self) -> dict[str, Any]:
        return await self.provider.current_time()

    def citation(self, title: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "railway_mcp",
            "chunk_id": None,
            "title": f"{self.provider.source_name} {title}",
            "url": None,
            "similarity": None,
            "metadata": metadata,
        }
