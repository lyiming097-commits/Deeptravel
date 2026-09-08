import socket

import pytest

from backend.mcp_servers.search_server.fetcher import (
    SmartPageFetcher,
    extract_content,
    extract_images,
    validate_resolved_host,
    validate_url,
)


def test_fetcher_blocks_non_https() -> None:
    with pytest.raises(ValueError):
        validate_url("http://example.com")


def test_fetcher_blocks_localhost() -> None:
    with pytest.raises(ValueError):
        validate_url("https://127.0.0.1/private")


@pytest.mark.asyncio
async def test_fetcher_blocks_domain_resolving_to_private_ip(monkeypatch) -> None:
    loop = __import__("asyncio").get_running_loop()

    async def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="内网"):
        await validate_resolved_host("https://example.com/private")


def test_beautifulsoup_cleanup_removes_navigation_and_scripts() -> None:
    title, content = extract_content(
        """
        <html><head><title>成都攻略</title><script>ignore()</script></head>
        <body><nav>导航</nav><main><h1>宽窄巷子</h1><p>适合慢游。</p></main></body></html>
        """,
        "https://example.com/chengdu",
        20000,
    )

    assert title == "成都攻略"
    assert "宽窄巷子" in content
    assert "ignore" not in content
    assert "导航" not in content


def test_extract_images_prefers_named_hero_and_lazy_loaded_sources() -> None:
    images = extract_images(
        """
        <html><head>
          <meta property="og:image" content="/media/west-lake-hero.jpg">
        </head><body>
          <img data-src="/media/lingyin.jpg" alt="灵隐寺大雄宝殿">
          <img src="/avatar.png" alt="作者头像">
        </body></html>
        """,
        "https://travel.example.com/hangzhou/guide",
    )

    assert images[0]["url"] == "https://travel.example.com/media/west-lake-hero.jpg"
    assert images[1]["url"] == "https://travel.example.com/media/lingyin.jpg"
    assert images[1]["alt"] == "灵隐寺大雄宝殿"


def test_extract_images_chooses_largest_srcset_rendition() -> None:
    images = extract_images(
        '<img srcset="/small.jpg 320w, /large.jpg 1200w" alt="西湖全景">',
        "https://travel.example.com/hangzhou",
    )
    assert images[0]["url"] == "https://travel.example.com/large.jpg"


class FakePageFetcher:
    def __init__(self, content: str, renderer: str) -> None:
        self.content = content
        self.renderer = renderer
        self.calls = 0

    async def fetch(self, url: str, max_chars: int = 20000) -> dict:
        self.calls += 1
        return {"url": url, "content": self.content, "renderer": self.renderer}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_smart_fetcher_uses_playwright_only_when_static_content_is_short() -> None:
    static = FakePageFetcher("请启用 JavaScript", "static")
    dynamic = FakePageFetcher("动态渲染后的旅游正文" * 50, "playwright")
    fetcher = SmartPageFetcher(static, dynamic, renderer="auto", min_content_chars=100)

    result = await fetcher.fetch("https://example.com/dynamic")

    assert result["renderer"] == "playwright"
    assert static.calls == 1
    assert dynamic.calls == 1


@pytest.mark.asyncio
async def test_smart_fetcher_rejects_two_short_extractions() -> None:
    static = FakePageFetcher("请启用 JavaScript", "static")
    dynamic = FakePageFetcher("访问被拒绝", "playwright")
    fetcher = SmartPageFetcher(static, dynamic, renderer="auto", min_content_chars=100)

    with pytest.raises(ValueError, match="足够正文"):
        await fetcher.fetch("https://example.com/blocked")
