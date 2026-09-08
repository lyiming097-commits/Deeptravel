from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from backend.app.config import get_settings
from backend.mcp_servers.search_server.fetcher import build_page_fetcher
from backend.mcp_servers.search_server.provider import (
    DuckDuckGoProvider,
    MockSearchProvider,
    TavilyProvider,
)

settings = get_settings()
internal_key = settings.search_mcp_internal_api_key
if settings.search_mocked:
    provider = MockSearchProvider()
elif settings.search_provider == "tavily":
    provider = TavilyProvider(settings.tavily_api_key)
else:
    provider = DuckDuckGoProvider(
        settings.duckduckgo_region,
        settings.duckduckgo_safesearch,
        settings.duckduckgo_timeout_seconds,
    )
fetcher = build_page_fetcher(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await fetcher.close()


app = FastAPI(title="DeepTravel Search MCP", version="0.1.0", lifespan=lifespan)


def auth(value: str | None) -> None:
    if internal_key and value != internal_key:
        raise HTTPException(401, "Search MCP 鉴权失败")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


class FetchRequest(BaseModel):
    url: str
    max_chars: int = Field(default=20000, ge=1000, le=20000)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "provider": provider.__class__.__name__,
        "renderer": settings.web_fetch_renderer,
    }


@app.post("/mcp/tools/web_search")
async def web_search(
    request: SearchRequest, x_search_key: str | None = Header(default=None)
) -> dict:
    auth(x_search_key)
    try:
        results = await provider.search(request.query, request.max_results)
        return {"tool": "web_search", "query": request.query, "results": results}
    except Exception as exc:
        raise HTTPException(502, f"搜索服务失败：{exc}") from exc


@app.post("/mcp/tools/web_fetch")
async def web_fetch(request: FetchRequest, x_search_key: str | None = Header(default=None)) -> dict:
    auth(x_search_key)
    try:
        result = await fetcher.fetch(request.url, request.max_chars)
        result.update({"tool": "web_fetch", "fetched_at": datetime.now(UTC).isoformat()})
        return result
    except Exception as exc:
        raise HTTPException(400, f"网页抓取失败：{exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.mcp_servers.search_server.server:app",
        host="127.0.0.1",
        port=8100,
        reload=settings.app_env == "local",
    )
