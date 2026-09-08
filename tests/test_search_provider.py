import sys
from types import SimpleNamespace

from backend.mcp_servers.search_server.provider import DuckDuckGoProvider


def test_duckduckgo_provider_normalises_and_filters_results(monkeypatch) -> None:
    class FakeDDGS:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def text(self, *args, **kwargs):
            return [
                {
                    "title": "成都旅游攻略",
                    "href": "https://example.com/chengdu",
                    "body": "宽窄巷子和武侯祠。",
                },
                {
                    "title": "不安全结果",
                    "href": "http://example.com/plain-http",
                    "body": "应被过滤",
                },
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))
    provider = DuckDuckGoProvider(timeout=5)

    results = provider._search_sync("成都旅游", 5)

    assert len(results) == 1
    assert results[0]["provider"] == "duckduckgo"
    assert results[0]["url"] == "https://example.com/chengdu"
