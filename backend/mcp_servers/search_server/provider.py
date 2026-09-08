import asyncio
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]: ...


class DuckDuckGoProvider:
    """无 API Key 的 DuckDuckGo 搜索 Provider。"""

    def __init__(
        self,
        region: str = "cn-zh",
        safesearch: str = "moderate",
        timeout: float = 10,
    ) -> None:
        self.region = region
        self.safesearch = safesearch
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        return await asyncio.wait_for(
            asyncio.to_thread(self._search_sync, query, max_results),
            timeout=self.timeout + 2,
        )

    def _search_sync(self, query: str, max_results: int) -> list[dict[str, Any]]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("未安装 ddgs，请重新安装后端依赖") from exc
        results = DDGS(timeout=self.timeout).text(
            query,
            region=self.region,
            safesearch=self.safesearch,
            max_results=max_results,
        )
        normalized: list[dict[str, Any]] = []
        for item in results or []:
            url = str(item.get("href") or item.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            normalized.append(
                {
                    "title": item.get("title") or url,
                    "url": url,
                    "snippet": item.get("body") or item.get("snippet") or "",
                    "domain": parsed.hostname,
                    "published_at": item.get("date") or item.get("published_at"),
                    "provider": "duckduckgo",
                }
            )
        return normalized[:max_results]


class TavilyProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.tavily.com") -> None:
        self.api_key, self.base_url = api_key, base_url.rstrip("/")

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未配置")
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                f"{self.base_url}/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        return [
            {
                "title": item.get("title") or item.get("url", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "domain": urlparse(item.get("url", "")).hostname,
                "published_at": item.get("published_date"),
                "provider": "tavily",
            }
            for item in results
            if item.get("url")
        ]


class MockSearchProvider:
    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "title": "国家文旅公开信息示例",
                "url": "https://example.com/travel",
                "snippet": f"关于{query}的 Mock 公开资料，仅用于验证开发链路。",
                "domain": "example.com",
                "published_at": None,
                "provider": "mock",
            }
        ][:max_results]
