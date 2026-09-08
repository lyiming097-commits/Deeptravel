import asyncio
import ipaddress
import re
import socket
from contextlib import suppress
from typing import Any, ClassVar, Protocol
from urllib.parse import urljoin, urlparse, urlsplit

import httpx
import trafilatura
from bs4 import BeautifulSoup

from backend.app.config import Settings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("只允许抓取 HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("网页 URL 不允许携带用户凭据")
    host = parsed.hostname.lower()
    blocked = host == "localhost" or host.endswith(".localhost")
    try:
        address = ipaddress.ip_address(host)
        blocked = blocked or not address.is_global
    except ValueError:
        pass
    if blocked:
        raise ValueError("禁止访问本地或内网地址")


async def validate_resolved_host(url: str) -> None:
    """拒绝解析到内网、回环或保留地址的域名。"""
    validate_url(url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("禁止访问本地或内网地址")
        return
    except ValueError as exc:
        if "禁止访问" in str(exc):
            raise

    loop = asyncio.get_running_loop()
    try:
        addresses = await asyncio.wait_for(
            loop.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM),
            timeout=3,
        )
    except (OSError, TimeoutError) as exc:
        raise ValueError("网页域名解析失败") from exc
    if not addresses:
        raise ValueError("网页域名未解析到可用地址")
    if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("域名解析到本地或内网地址")


def _image_identity(url: str) -> str:
    """Return a stable identity for image URL de-duplication."""

    try:
        parsed = urlsplit(url)
        if not parsed.netloc or not parsed.path:
            return ""
        return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except (TypeError, ValueError):
        return url.lower().split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _normalise_image_url(value: Any, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate.startswith(("data:", "blob:", "javascript:", "#")):
        return ""
    # srcset entries may contain width/density descriptors; choose the largest
    # declared rendition so the UI does not receive a blurry thumbnail.
    if "," in candidate:
        options = [part.strip() for part in candidate.split(",") if part.strip()]
        candidate = max(
            options,
            key=lambda part: float(
                (re.search(r"(\d+(?:\.\d+)?)(?:w|x)\s*$", part) or ["", "0"])[1]
            ),
        )
    candidate = candidate.split(" ", 1)[0]
    resolved = urljoin(base_url, candidate)
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return resolved


def extract_images(source: str, url: str, max_images: int = 12) -> list[dict[str, str]]:
    """Extract meaningful page images without downloading them.

    Search results previously carried only text, so a page that clearly
    described West Lake (or another landmark) could never contribute a photo
    to a POI card.  Keep the extraction deliberately metadata-only: the image
    is fetched later by the same-origin API proxy after a POI/name match.
    ``og:image``/Twitter cards are preferred, followed by lazy-loaded and
    regular ``img``/``source`` attributes.  Alt/title text is retained for
    strict landmark matching and to avoid attaching a hotel banner to a
    scenic spot.
    """

    if not source or max_images <= 0:
        return []
    soup = BeautifulSoup(source, "html.parser")
    candidates: list[tuple[str, str, int]] = []

    def add(raw: Any, node: Any = None, priority: int = 0) -> None:
        image_url = _normalise_image_url(raw, url)
        if not image_url:
            return
        alt = ""
        if node is not None and hasattr(node, "get"):
            alt = str(
                node.get("alt")
                or node.get("title")
                or node.get("data-alt")
                or node.get("aria-label")
                or ""
            ).strip()
        candidates.append((image_url, alt[:300], priority))

    # OpenGraph/Twitter images are usually the page's main, high-resolution
    # image and should win over recommendation widgets and avatars.
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").lower()
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            add(meta.get("content"), meta, 100)

    for node in soup.find_all(["img", "source"]):
        if node.name == "source":
            raw_values = [node.get("src"), node.get("data-src"), node.get("srcset")]
        else:
            raw_values = [
                node.get("src"), node.get("data-src"), node.get("data-original"),
                node.get("data-original-src"), node.get("data-lazy-src"),
                node.get("data-url"), node.get("data-image"), node.get("srcset"),
            ]
        # Keep the first usable source for one DOM node; a srcset rendition is
        # still preferred to a tiny placeholder when it is the only source.
        for raw in raw_values:
            if raw:
                add(raw, node, 70 if raw == node.get("srcset") else 60)
                break

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for image_url, alt, priority in sorted(candidates, key=lambda item: -item[2]):
        identity = _image_identity(image_url)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        results.append({"url": image_url, "alt": alt, "title": alt, "priority": str(priority)})
        if len(results) >= max_images:
            break
    return results


def extract_content(source: str, url: str, max_chars: int) -> tuple[str, str]:
    """BeautifulSoup 清洗 DOM，Trafilatura 提取主体正文。"""
    soup = BeautifulSoup(source, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    for tag in soup.select(
        "script, style, noscript, template, svg, canvas, nav, footer, aside, form"
    ):
        tag.decompose()
    cleaned_html = str(soup)
    extracted = trafilatura.extract(
        cleaned_html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    fallback = soup.get_text("\n", strip=True)
    text = extracted or fallback
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title[:500], text[:max_chars]


class PageFetcher(Protocol):
    async def fetch(self, url: str, max_chars: int = 20000) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class StaticPageFetcher:
    """低成本、不执行 JavaScript 的 HTTPX 抓取器。"""

    def __init__(self, timeout: float = 12) -> None:
        self.timeout = timeout

    async def fetch(self, url: str, max_chars: int = 20000) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers={"User-Agent": "DeepTravelBot/1.0"},
        ) as client:
            current_url = url
            for _ in range(4):
                await validate_resolved_host(current_url)
                async with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("网页重定向缺少 Location")
                        current_url = urljoin(str(response.url), location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(SUPPORTED_CONTENT_TYPES):
                        raise ValueError("网页内容类型不支持")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ValueError("网页响应超过大小限制")
                    final_url = str(response.url)
                    charset = response.charset_encoding or "utf-8"
                    break
            else:
                raise ValueError("网页重定向次数过多")
        try:
            source = bytes(body).decode(charset, errors="replace")
        except LookupError:
            source = bytes(body).decode("utf-8", errors="replace")
        title, content = extract_content(source, final_url, max_chars)
        return {
            "final_url": final_url,
            "title": title,
            "content": content,
            "images": extract_images(source, final_url),
            "content_type": content_type,
            "renderer": "static",
        }

    async def close(self) -> None:
        return None


class PlaywrightPageFetcher:
    """隔离 BrowserContext 的动态页面渲染回退抓取器。"""

    blocked_resource_types: ClassVar[frozenset[str]] = frozenset(
        {"image", "media", "font"}
    )

    def __init__(self, timeout: float = 15, max_concurrency: int = 2) -> None:
        self.timeout_ms = int(timeout * 1000)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._start_lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def _ensure_browser(self) -> Any:
        if self._browser:
            return self._browser
        async with self._start_lock:
            if self._browser:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError("未安装 Playwright") from exc
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-first-run"],
            )
        return self._browser

    async def fetch(self, url: str, max_chars: int = 20000) -> dict[str, Any]:
        await validate_resolved_host(url)
        async with self._semaphore:
            browser = await self._ensure_browser()
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
                ignore_https_errors=False,
            )
            page = await context.new_page()
            validated_hosts: set[str] = set()

            async def guard_request(route: Any) -> None:
                request = route.request
                if request.resource_type in self.blocked_resource_types:
                    await route.abort("blockedbyclient")
                    return
                try:
                    parsed = urlparse(request.url)
                    host = parsed.hostname or ""
                    if host not in validated_hosts:
                        await validate_resolved_host(request.url)
                        validated_hosts.add(host)
                    await route.continue_()
                except (OSError, RuntimeError, ValueError):
                    await route.abort("blockedbyclient")

            await page.route("**/*", guard_request)
            try:
                from playwright.async_api import TimeoutError as PlaywrightTimeoutError

                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=2500)
                except PlaywrightTimeoutError:
                    pass
                final_url = page.url
                await validate_resolved_host(final_url)
                source = await page.content()
                if len(source.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ValueError("动态网页响应超过大小限制")
                title, content = extract_content(source, final_url, max_chars)
                return {
                    "final_url": final_url,
                    "title": title,
                    "content": content,
                    "images": extract_images(source, final_url),
                    "content_type": "text/html; rendered=playwright",
                    "renderer": "playwright",
                }
            finally:
                with suppress(Exception):
                    await context.close()

    async def close(self) -> None:
        if self._browser:
            with suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright:
            with suppress(Exception):
                await self._playwright.stop()
            self._playwright = None


class SmartPageFetcher:
    """静态优先，正文不足或指定时回退 Playwright。"""

    def __init__(
        self,
        static: StaticPageFetcher,
        dynamic: PlaywrightPageFetcher,
        renderer: str = "auto",
        min_content_chars: int = 400,
    ) -> None:
        self.static = static
        self.dynamic = dynamic
        self.renderer = renderer
        self.min_content_chars = min_content_chars

    async def fetch(self, url: str, max_chars: int = 20000) -> dict[str, Any]:
        if self.renderer == "playwright":
            result = await self.dynamic.fetch(url, max_chars)
            if len(result["content"]) < self.min_content_chars:
                raise ValueError("Playwright 未提取到足够正文")
            return result
        static_result: dict[str, Any] | None = None
        try:
            static_result = await self.static.fetch(url, max_chars)
            if self.renderer == "static" or len(static_result["content"]) >= self.min_content_chars:
                return static_result
        except httpx.HTTPError:
            if self.renderer == "static":
                raise
        try:
            dynamic_result = await self.dynamic.fetch(url, max_chars)
            if static_result and len(static_result["content"]) > len(dynamic_result["content"]):
                best_result = static_result
            else:
                best_result = dynamic_result
            # Static and rendered DOMs can expose different image attributes.
            # Keep the longer正文 result while merging their de-duplicated
            # image observations so a JS page does not lose its hero image.
            merged_images: list[dict[str, str]] = []
            for candidate in [
                *(static_result.get("images", []) if static_result else []),
                *(dynamic_result.get("images", []) if dynamic_result else []),
            ]:
                if not isinstance(candidate, dict) or not candidate.get("url"):
                    continue
                identity = _image_identity(str(candidate["url"]))
                if identity and not any(_image_identity(str(item.get("url"))) == identity for item in merged_images):
                    merged_images.append(candidate)
            if merged_images:
                best_result = {**best_result, "images": merged_images[:12]}
            if len(best_result["content"]) < self.min_content_chars:
                raise ValueError("静态与动态抓取均未提取到足够正文")
            return best_result
        except Exception:
            if static_result and len(static_result["content"]) >= self.min_content_chars:
                return static_result
            raise

    async def close(self) -> None:
        await self.static.close()
        await self.dynamic.close()


def build_page_fetcher(settings: Settings) -> SmartPageFetcher:
    return SmartPageFetcher(
        StaticPageFetcher(settings.web_fetch_timeout_seconds),
        PlaywrightPageFetcher(
            settings.playwright_timeout_seconds,
            settings.playwright_max_concurrency,
        ),
        settings.web_fetch_renderer,
        settings.web_fetch_min_content_chars,
    )


async def fetch_page(url: str, max_chars: int = 20000) -> dict[str, Any]:
    """保留给现有调用方的静态抓取兼容入口。"""
    return await StaticPageFetcher().fetch(url, max_chars)
