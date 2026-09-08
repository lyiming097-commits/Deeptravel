from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    test_mode: bool = False
    mock_llm: bool | None = None
    mock_amap: bool | None = None
    mock_search: bool | None = None
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_reasoning_model: str = "deepseek-reasoner"
    deepseek_timeout_seconds: float = 60
    deepseek_max_retries: int = 1
    database_url: str = ""
    database_connect_timeout_seconds: float = 5
    embedding_provider: Literal["local_hash", "ollama", "openai_compatible"] = "local_hash"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = 1024
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_timeout_seconds: float = 60
    embedding_batch_size: int = 16
    embedding_keep_alive: str = "10m"
    embedding_query_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.72
    rag_min_reliable_chunks: int = 2
    web_fetch_max_pages: int = 3
    web_rerank_top_k: int = 5
    web_fetch_renderer: Literal["static", "auto", "playwright"] = "auto"
    web_fetch_timeout_seconds: float = 12
    web_fetch_min_content_chars: int = 400
    playwright_timeout_seconds: float = 15
    playwright_max_concurrency: int = 2
    agent_max_tool_calls: int = 4
    agent_timeout_seconds: float = 120
    agent_graph_recursion_limit: int = 12
    short_memory_messages: int = 12
    max_chat_sessions_per_scene: int = 5
    amap_provider: Literal["mcp"] = "mcp"
    amap_mcp_endpoint: str = "https://mcp.amap.com/mcp"
    amap_mcp_api_key: str = ""
    amap_mcp_timeout_seconds: float = 30
    # Python mcp-server-12306 runs separately and exposes a Streamable HTTP
    # endpoint. Keep it empty by default until that service is started.
    railway_mcp_endpoint: str = ""
    railway_mcp_timeout_seconds: float = 30
    railway_result_limit: int = 9
    search_mcp_endpoint: str = "http://127.0.0.1:8100/mcp"
    search_mcp_internal_api_key: str = ""
    search_provider: Literal["duckduckgo", "tavily"] = "duckduckgo"
    duckduckgo_region: str = "cn-zh"
    duckduckgo_safesearch: Literal["on", "moderate", "off"] = "moderate"
    duckduckgo_timeout_seconds: float = 10
    tavily_api_key: str = ""
    auth_token_ttl_days: int = 7
    admin_username: str = "admin"
    admin_initial_password: str = ""
    # 微信小程序登录配置。留空时接口会明确提示需要配置，不会伪造登录成功。
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_login_timeout_seconds: float = 10
    max_upload_bytes: int = 50 * 1024 * 1024

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        """Use asyncpg for managed PostgreSQL connection strings.

        Render and several other platforms expose ``postgres://`` or
        ``postgresql://`` URLs.  The application uses SQLAlchemy's async
        engine, so normalize those provider URLs without changing an
        explicitly selected SQLAlchemy driver.
        """

        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @property
    def psql_database_url(self) -> str:
        """Return the libpq-compatible URL used by psql and Alembic."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    def configuration_status(self) -> dict[str, bool]:
        return {
            "database": bool(self.database_url),
            "deepseek": bool(self.deepseek_api_key),
            "embedding": self.embedding_provider == "local_hash"
            or (
                self.embedding_provider == "ollama"
                and bool(self.embedding_base_url and self.embedding_model)
            )
            or bool(self.embedding_base_url and self.embedding_api_key),
            "amap": self.amap_configured,
            "amap_mcp": self.amap_configured,
            "railway_mcp": bool(self.railway_mcp_endpoint),
            "search_mcp": bool(self.search_mcp_endpoint),
            "duckduckgo": self.search_provider == "duckduckgo",
            "tavily": bool(self.tavily_api_key),
            "wechat": bool(self.wechat_app_id and self.wechat_app_secret),
        }

    @property
    def llm_mocked(self) -> bool:
        return self.test_mode if self.mock_llm is None else self.mock_llm

    @property
    def amap_mocked(self) -> bool:
        return self.test_mode if self.mock_amap is None else self.mock_amap

    @property
    def amap_configured(self) -> bool:
        return bool(self.amap_mcp_endpoint and self.amap_mcp_api_key)

    @property
    def search_mocked(self) -> bool:
        return self.test_mode if self.mock_search is None else self.mock_search

    @property
    def any_mocked(self) -> bool:
        return self.llm_mocked or self.amap_mocked or self.search_mocked


@lru_cache
def get_settings() -> Settings:
    return Settings()
