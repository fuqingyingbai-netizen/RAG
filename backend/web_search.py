import os
import re
import threading
import time
import base64
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._title = ""
        self._metadata: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = {str(key).lower(): str(value or "").strip() for key, value in attrs}
        if tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = attrs_dict.get("content", "")
            if content and name in {"description", "og:description", "twitter:description"}:
                self._metadata.append(content)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "div", "section", "article", "main", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "section", "article", "main", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def readable_text(self) -> str:
        parts = self._metadata + self._chunks
        text = " ".join(parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n\s*", "\n\n", text)
        return text.strip()


class WebSearchProvider:
    def __init__(self):
        self._exa_lock = threading.Lock()
        self._exa_last_request_at = 0.0
        self._engine_state_lock = threading.Lock()
        self._disabled_engines: set[str] = set()
        self.engines = [
            ("tavily", self._search_tavily),
            ("serper", self._search_serper),
            ("exa", self._search_exa),
            ("serpapi", self._search_serpapi),
            ("brave", self._search_brave),
            ("bocha", self._search_bocha),
        ]
        self._desktop_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        self._mobile_user_agent = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        category: str | None = None,
        preferred_providers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        if provider == "tavily":
            return self._search_tavily(query, limit, include_domains, exclude_domains)
        if provider == "serper":
            return self._search_serper(self._query_with_sites(query, include_domains), limit)
        if provider == "exa":
            return self._search_exa(query, limit, include_domains, exclude_domains, category)
        if provider == "serpapi":
            return self._search_serpapi(self._query_with_sites(query, include_domains), limit)
        if provider == "brave":
            return self._search_brave(self._query_with_sites(query, include_domains), limit)
        if provider == "bocha":
            return self._search_bocha(query, limit, include_domains, exclude_domains)
        return self.multi_engine_search(query, limit, include_domains, exclude_domains, category, preferred_providers)

    def search_single(self, provider: str, query: str, limit: int = 6,
                      include_domains=None, category=None) -> list[dict[str, Any]]:
        """An auditable single paid request with lightweight person recall.

        Errors propagate to the run audit. Original pages are fetched later,
        after identity filtering and URL deduplication, under a separate budget.
        """
        if not os.getenv(f"{provider.upper()}_API_KEY"):
            raise RuntimeError("search_provider_not_configured")
        if provider == "bocha":
            return self._search_bocha(query, limit, include_domains, lightweight=True)
        if provider == "tavily":
            return self._search_tavily(query, limit, include_domains, lightweight=True)
        if provider == "exa":
            return self._search_exa(query, limit, include_domains, category=category, lightweight=True)
        engine = dict(self.engines).get(provider)
        if engine is None:
            raise ValueError("unknown_search_provider")
        return engine(self._query_with_sites(query, include_domains), limit)

    def multi_engine_search(
        self,
        query: str,
        limit: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        category: str | None = None,
        preferred_providers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        futures: dict[Any, str] = {}

        with ThreadPoolExecutor(max_workers=len(self.engines)) as executor:
            allowed = set(preferred_providers or [])
            for name, engine_func in self.engines:
                if allowed and name not in allowed:
                    continue
                with self._engine_state_lock:
                    if name in self._disabled_engines:
                        continue
                api_key_env = f"{name.upper()}_API_KEY"
                if os.getenv(api_key_env):
                    if name == "tavily":
                        future = executor.submit(engine_func, query, limit, include_domains, exclude_domains)
                    elif name == "exa":
                        future = executor.submit(engine_func, query, limit, include_domains, exclude_domains, category)
                    elif name == "bocha":
                        future = executor.submit(engine_func, query, limit, include_domains, exclude_domains)
                    else:
                        future = executor.submit(engine_func, self._query_with_sites(query, include_domains), limit)
                    futures[future] = name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    all_results.extend(future.result())
                except Exception as exc:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    if status_code in {401, 403}:
                        # An invalid/expired credential will fail identically for every
                        # query. Quarantine that provider for this process and continue
                        # with the remaining configured engines instead of flooding the
                        # backend with repeated errors.
                        with self._engine_state_lock:
                            self._disabled_engines.add(name)
                    suffix = f" HTTP {status_code}" if status_code else f" {type(exc).__name__}"
                    print(f"Search engine {name} unavailable:{suffix}; continuing with fallback engines")

        seen_urls = set()
        unique_results = []
        for result in all_results:
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)

        unique_results.sort(key=lambda item: item.get("credibility_score", 0), reverse=True)
        return unique_results[:limit]

    def _search_tavily(
        self,
        query: str,
        limit: int,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        *, lightweight: bool = False,
    ) -> list[dict[str, Any]]:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return []
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": limit,
                "search_depth": "basic" if lightweight else "advanced",
                "include_answer": False,
                "include_raw_content": not lightweight,
                "include_images": not lightweight,
                "include_image_descriptions": not lightweight,
                "include_domains": list(include_domains or [])[:300],
                "exclude_domains": list(exclude_domains or [])[:150],
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("results", [])
        images = payload.get("images", []) or []
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("raw_content") or item.get("content") or "",
                "summary": item.get("content", ""),
                "source_type": "web",
                "metadata": {
                    "provider": "tavily",
                    "score": item.get("score"),
                    "published_date": item.get("published_date"),
                    "images": images,
                },
                "credibility_score": int(float(item.get("score") or 0.5) * 100),
            }
            for item in rows
        ]

    def _search_serper(self, query: str, limit: int) -> list[dict[str, Any]]:
        api_key = os.getenv("SERPER_API_KEY", "")
        if not api_key:
            return []
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": limit},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("organic", [])[:limit]
        fetch_enabled = os.getenv("SERPER_FETCH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        max_fetch = self._env_int("SERPER_FETCH_LIMIT", min(limit, 5), 0, max(0, limit))
        results = []
        for index, item in enumerate(rows):
            url = item.get("link", "")
            snippet = item.get("snippet", "")
            fetched = self.fetch_url(url, allow_browser=False) if fetch_enabled and index < max_fetch else {}
            content = fetched.get("content") or snippet
            metadata = {
                "provider": "serper",
                "position": item.get("position"),
                "fetch_status": fetched.get("status", "skipped" if not fetch_enabled or index >= max_fetch else "empty"),
                "fetch_error": fetched.get("error", ""),
                "fetched_chars": len(fetched.get("content") or ""),
            }
            results.append(
                {
                "title": item.get("title", ""),
                "url": url,
                "content": content,
                "summary": snippet or content[:500],
                "source_type": "web",
                "metadata": metadata,
                "credibility_score": 60,
            }
            )
        return results

    def _search_exa(
        self,
        query: str,
        limit: int,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        category: str | None = None,
        *, lightweight: bool = False,
    ) -> list[dict[str, Any]]:
        api_key = os.getenv("EXA_API_KEY", "")
        if not api_key:
            return []
        self._wait_for_exa_slot()
        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": max(1, min(limit, 100)),
                "type": os.getenv("EXA_SEARCH_TYPE", "fast").strip() or "fast",
                **({} if lightweight else {"contents": {"text": True, "summary": True}}),
                **({"includeDomains": list(include_domains or [])} if include_domains else {}),
                **({"excludeDomains": list(exclude_domains or [])} if exclude_domains and category not in {"company", "people"} else {}),
                **({"category": category} if category else {}),
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("results", [])
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("text", "") or item.get("content", "") or item.get("snippet", ""),
                "summary": item.get("summary", "") or item.get("text", "") or item.get("content", "") or item.get("snippet", ""),
                "source_type": "web",
                "metadata": {"provider": "exa", "score": item.get("score")},
                "credibility_score": 65,
            }
            for item in rows
        ]

    def _search_serpapi(self, query: str, limit: int) -> list[dict[str, Any]]:
        api_key = os.getenv("SERPAPI_API_KEY", "").strip()
        if not api_key:
            return []
        response = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": api_key, "num": max(1, min(limit, 100))},
            timeout=30,
        )
        response.raise_for_status()
        return [
            {
                "title": item.get("title", ""), "url": item.get("link", ""),
                "content": item.get("snippet", ""), "summary": item.get("snippet", ""),
                "source_type": "web", "metadata": {"provider": "serpapi", "position": item.get("position")},
                "credibility_score": 62,
            }
            for item in (response.json().get("organic_results") or [])[:limit]
        ]

    def _search_brave(self, query: str, limit: int) -> list[dict[str, Any]]:
        api_key = os.getenv("BRAVE_API_KEY", "").strip()
        if not api_key:
            return []
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": max(1, min(limit, 20)), "search_lang": "zh-hans"},
            timeout=30,
        )
        response.raise_for_status()
        return [
            {
                "title": item.get("title", ""), "url": item.get("url", ""),
                "content": item.get("description", ""), "summary": item.get("description", ""),
                "source_type": "web", "metadata": {"provider": "brave"}, "credibility_score": 62,
            }
            for item in ((response.json().get("web") or {}).get("results") or [])[:limit]
        ]

    @staticmethod
    def _query_with_sites(query: str, domains: list[str] | None) -> str:
        clean = [str(domain or "").strip() for domain in (domains or []) if str(domain or "").strip()]
        if not clean:
            return query
        site_filter = " OR ".join(f"site:{domain}" for domain in clean)
        return f"{query} ({site_filter})"

    def _search_bocha(
        self, query: str, limit: int,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        *, lightweight: bool = False,
    ) -> list[dict[str, Any]]:
        api_key = os.getenv("BOCHA_API_KEY", "").strip()
        if not api_key:
            return []
        # Bocha's native domain filters are required: site: operators in the
        # query did not constrain results in the live source-coverage audit.
        body = {"query": query, "count": max(1, min(limit, 50)), "freshness": "noLimit", "summary": True}
        for field, domains in (("include", include_domains), ("exclude", exclude_domains)):
            clean = list(dict.fromkeys(str(domain).strip() for domain in (domains or []) if str(domain).strip()))
            if clean:
                body[field] = ",".join(clean)
        response = requests.post(
            os.getenv("BOCHA_SEARCH_URL", "https://api.bocha.cn/v1/web-search"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()
        payload = raw.get("data", raw)
        rows = (payload.get("webPages") or {}).get("value") or []
        fetch_enabled = not lightweight and os.getenv("BOCHA_FETCH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        max_fetch = self._env_int("BOCHA_FETCH_LIMIT", min(limit, 5), 0, max(0, limit))
        results: list[dict[str, Any]] = []
        for index, item in enumerate(rows[:limit]):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            snippet = item.get("summary") or item.get("snippet") or ""
            fetched = self.fetch_url(url, allow_browser=False) if fetch_enabled and index < max_fetch else {}
            content = fetched.get("content") or snippet
            results.append(
                {
                    "title": item.get("name", ""),
                    "url": url,
                    "content": content,
                    "summary": snippet or content[:500],
                    "source_type": "web",
                    "metadata": {
                        "provider": "bocha",
                        "site_name": item.get("siteName"),
                        "published_date": item.get("datePublished"),
                        "fetch_status": fetched.get("status", "skipped" if not fetch_enabled or index >= max_fetch else "empty"),
                        "fetch_error": fetched.get("error", ""),
                        "fetched_chars": len(fetched.get("content") or ""),
                    },
                    "credibility_score": 65,
                }
            )
        return results

    def _wait_for_exa_slot(self) -> None:
        interval = max(1.0, float(os.getenv("EXA_REQUEST_INTERVAL_SECONDS", "1.05") or "1.05"))
        with self._exa_lock:
            now = time.time()
            wait_seconds = self._exa_last_request_at + interval - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._exa_last_request_at = time.time()

    def fetch_url(self, url: str, allow_browser: bool = True, *, document_profile: str = '') -> dict[str, Any]:
        url = (url or "").strip()
        if not url or urlparse(url).scheme not in {"http", "https"}:
            return {"status": "skipped", "content": "", "error": "invalid_url"}
        timeout = self._env_int("WEB_FETCH_TIMEOUT_SECONDS", 12, 3, 60)
        max_chars = self._env_int("WEB_FETCH_MAX_CHARS", 30000, 1000, 200000)
        min_chars = self._env_int("WEB_FETCH_MIN_CHARS", 600, 80, 5000)
        attempts = [
            ("desktop", self._desktop_user_agent),
            ("mobile", self._mobile_user_agent),
        ]
        best: dict[str, Any] = {"status": "empty", "content": "", "error": ""}
        errors: list[str] = []
        for attempt_name, user_agent in attempts:
            options = {'document_profile': document_profile} if document_profile else {}
            result = self._fetch_url_once(url, timeout, max_chars, user_agent, attempt_name, **options)
            if result.get("error"):
                errors.append(f"{attempt_name}:{result.get('error')}")
            if len(result.get("content") or "") > len(best.get("content") or "") or (
                not best.get("content") and result.get("status") not in {"empty", "failed"}
            ):
                best = result
            if len(result.get("content") or "") >= min_chars:
                return result
            if document_profile == 'company' and result.get('document_extraction') is not None and result.get('document_pages') is not None:
                # A valid PDF with sparse/failed OCR is already an acquired
                # original. Retain its page-level gaps; do not OCR it again
                # with a mobile user-agent or replace the record with a reader
                # summary merely because the extracted body is short.
                return result
        reader_result = self._fetch_with_reader_proxy(url, timeout, max_chars)
        if len(reader_result.get("content") or "") > len(best.get("content") or "") or (
            not best.get("content") and reader_result.get("status") not in {"reader_disabled", "reader_empty", "reader_failed"}
        ):
            best = reader_result
        if allow_browser:
            render_result = self._fetch_with_browser(url, timeout, max_chars)
            if len(render_result.get("content") or "") > len(best.get("content") or "") or (
                not best.get("content") and render_result.get("status") not in {"browser_disabled", "browser_unavailable", "browser_empty", "browser_failed"}
            ):
                best = render_result
        if errors and not best.get("error"):
            best["error"] = "; ".join(errors[:3])
        return best

    def _fetch_url_once(self, url: str, timeout: int, max_chars: int, user_agent: str, attempt_name: str, *, document_profile: str = '') -> dict[str, Any]:
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": os.getenv("WEB_FETCH_USER_AGENT", user_agent),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,application/pdf,*/*;q=0.5",
                    "Accept-Language": os.getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"),
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Referer": self._referer_for_url(url),
                    **self._cookie_header_for_url(url),
                },
                timeout=(5, timeout),
                allow_redirects=True,
            )
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").lower()
            url_path = urlparse(resp.url or url).path.lower()
            has_pdf_signature = resp.content.startswith(b"%PDF-")
            claims_pdf = "application/pdf" in content_type or url_path.endswith(".pdf")
            # Some search results ending in .pdf return an HTML/JavaScript challenge
            # page (often beginning with <script>). Passing that body to pypdf emits a
            # large stream of "invalid pdf header / EOF marker" warnings and can then
            # trigger an equally invalid render attempt. Only parse bytes that are
            # actually a PDF; let the caller try the reader/browser fallbacks otherwise.
            if claims_pdf and not has_pdf_signature:
                prefix = resp.content[:512].lstrip().lower()
                return {
                    "status": "invalid_pdf_response",
                    "content": "",
                    "error": "pdf_url_returned_html" if prefix.startswith((b"<", b"<!doctype")) else "missing_pdf_signature",
                    "content_type": content_type,
                    "fetch_attempt": attempt_name,
                }
            is_pdf = has_pdf_signature
            if is_pdf:
                if document_profile == 'company':
                    from company_pdf import extract_company_pdf
                    document = extract_company_pdf(resp.content)
                    return {**document, 'status': 'done' if document['content'] else 'empty_pdf',
                            'error': '', 'content_type': content_type or 'application/pdf',
                            'fetch_attempt': attempt_name, 'images': []}
                text, pages = self._extract_pdf_text(resp.content)
                images = []
                if not text.strip():
                    images = self._render_pdf_images(resp.content)
                return {
                    "status": "done" if text else "empty_pdf",
                    "content": text[:max_chars],
                    "error": "",
                    "content_type": content_type or "application/pdf",
                    "pages": pages,
                    "images": images,
                    "fetch_attempt": attempt_name,
                }
            if "text/html" not in content_type and "text/plain" not in content_type and "application/xhtml" not in content_type:
                return {"status": "unsupported_content_type", "content": "", "error": content_type, "fetch_attempt": attempt_name}
            body = self._decode_web_text(resp)
            if "text/html" in content_type or "<html" in body[:500].lower():
                text = self._extract_html_text(body)
            else:
                text = body.strip()
            if self._looks_like_block_page(text):
                return {
                    "status": "blocked_or_challenge",
                    "content": "",
                    "error": _clip_for_error(text),
                    "content_type": content_type,
                    "fetch_attempt": attempt_name,
                }
            return {
                "status": "done" if text else "empty",
                "content": text[:max_chars],
                "error": "",
                "content_type": content_type,
                "fetch_attempt": attempt_name,
            }
        except Exception as exc:
            return {"status": "failed", "content": "", "error": str(exc), "fetch_attempt": attempt_name}

    @staticmethod
    def _decode_web_text(response: requests.Response) -> str:
        """Use the shared lossless decoder for every research route."""
        try:
            from .text_integrity import decode_http_text
        except ImportError:
            from text_integrity import decode_http_text
        return decode_http_text(response)

    def _extract_html_text(self, body: str) -> str:
        soup_text = self._extract_html_text_with_bs4(body)
        parser = _ReadableHTMLParser()
        parser.feed(body)
        parser_text = parser.readable_text()
        return soup_text if len(soup_text) >= len(parser_text) else parser_text

    def _extract_html_text_with_bs4(self, body: str) -> str:
        if BeautifulSoup is None:
            return ""
        soup = BeautifulSoup(body, "html.parser")
        metadata = []
        for key in ["description", "og:description", "twitter:description"]:
            tag = soup.find("meta", attrs={"name": key}) or soup.find("meta", attrs={"property": key})
            content = tag.get("content", "") if tag else ""
            if content:
                metadata.append(content.strip())
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "header"]):
            tag.decompose()
        candidates = []
        selectors = [
            "article",
            "main",
            "[role=main]",
            ".article",
            ".article-content",
            ".article_content",
            ".content",
            ".post-content",
            ".entry-content",
            ".news-content",
            ".detail-content",
            ".rich_media_content",
            "#js_content",
            "#article",
            "#content",
        ]
        for selector in selectors:
            for node in soup.select(selector):
                text = node.get_text("\n", strip=True)
                if len(text) >= 120:
                    candidates.append(text)
        body_text = soup.body.get_text("\n", strip=True) if soup.body else soup.get_text("\n", strip=True)
        candidates.append(body_text)
        best = max(candidates, key=len, default="")
        text = "\n".join(part for part in metadata + [best] if part)
        return self._normalize_text(text)

    def _fetch_with_reader_proxy(self, url: str, timeout: int, max_chars: int) -> dict[str, Any]:
        if os.getenv("WEB_READER_FALLBACK_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            return {"status": "reader_disabled", "content": "", "error": ""}
        base = os.getenv("WEB_READER_FALLBACK_BASE", "").strip()
        if not base:
            return {"status": "reader_disabled", "content": "", "error": ""}
        reader_url = base + url
        try:
            resp = requests.get(
                reader_url,
                headers={
                    "User-Agent": self._desktop_user_agent,
                    "Accept": "text/plain,text/markdown,*/*;q=0.8",
                    "Accept-Language": os.getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"),
                },
                timeout=(5, timeout),
                allow_redirects=True,
            )
            resp.raise_for_status()
            text = self._normalize_text(self._decode_web_text(resp))
            return {
                "status": "reader_done" if text else "reader_empty",
                "content": text[:max_chars],
                "error": "",
                "content_type": resp.headers.get("Content-Type", ""),
                "fetch_attempt": "reader_proxy",
            }
        except Exception as exc:
            return {"status": "reader_failed", "content": "", "error": str(exc), "fetch_attempt": "reader_proxy"}

    def _fetch_with_browser(self, url: str, timeout: int, max_chars: int) -> dict[str, Any]:
        if os.getenv("WEB_RENDER_FALLBACK_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return {"status": "browser_disabled", "content": "", "error": ""}
        if sync_playwright is None:
            return {"status": "browser_unavailable", "content": "", "error": "playwright_not_installed"}
        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=self._desktop_user_agent,
                    locale="zh-CN",
                    viewport={"width": 1366, "height": 900},
                )
                page.set_extra_http_headers(
                    {
                        "Accept-Language": os.getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"),
                        "Referer": self._referer_for_url(url),
                        **self._cookie_header_for_url(url),
                    }
                )
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout * 1000, 10000))
                except Exception:
                    pass
                self._auto_scroll_page(page)
                html = page.content()
                text = self._extract_html_text(html)
                if self._looks_like_block_page(text):
                    try:
                        page.wait_for_timeout(min(timeout * 1000, 15000))
                        self._auto_scroll_page(page)
                        html = page.content()
                        text = self._extract_html_text(html)
                    except Exception:
                        pass
                title = page.title()
                if self._looks_like_block_page(text):
                    return {
                        "status": "browser_blocked_or_challenge",
                        "content": "",
                        "error": _clip_for_error(text),
                        "content_type": "text/html; rendered=playwright",
                        "fetch_attempt": "browser",
                        "rendered_title": title,
                    }
                return {
                    "status": "browser_done" if text else "browser_empty",
                    "content": text[:max_chars],
                    "error": "",
                    "content_type": "text/html; rendered=playwright",
                    "fetch_attempt": "browser",
                    "rendered_title": title,
                }
        except Exception as exc:
            return {"status": "browser_failed", "content": "", "error": str(exc), "fetch_attempt": "browser"}
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    def _auto_scroll_page(self, page) -> None:
        try:
            page.evaluate(
                """
                async () => {
                  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
                  for (let i = 0; i < 4; i++) {
                    window.scrollTo(0, document.body.scrollHeight * (i + 1) / 4);
                    await delay(350);
                  }
                  window.scrollTo(0, 0);
                }
                """
            )
        except Exception:
            pass

    def _referer_for_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return "https://www.google.com/"
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _cookie_header_for_url(self, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        host_key = re.sub(r"[^A-Za-z0-9]+", "_", (parsed.netloc or "").upper()).strip("_")
        cookie = os.getenv(f"WEB_FETCH_COOKIE_{host_key}", "").strip() if host_key else ""
        cookie = cookie or os.getenv("WEB_FETCH_COOKIE", "").strip()
        return {"Cookie": cookie} if cookie else {}

    def _looks_like_block_page(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "").lower()
        if not normalized:
            return False
        block_markers = [
            "请稍候",
            "云防护",
            "安全验证",
            "正在进行安全检测",
            "正在检测当前网络环境",
            "访问验证",
            "验证码",
            "人机验证",
            "checkingyourbrowser",
            "justamoment",
            "accessdenied",
            "forbidden",
            "captcha",
        ]
        return len(normalized) < 500 and any(marker in normalized for marker in block_markers)

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"\r\n?", "\n", text or "")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        lines = [line.strip() for line in text.split("\n")]
        lines = [line for line in lines if line]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    def _extract_pdf_text(self, payload: bytes) -> tuple[str, int]:
        try:
            reader = PdfReader(BytesIO(payload))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    return "", len(reader.pages)
            max_pages = self._env_int("WEB_FETCH_PDF_MAX_PAGES", 40, 1, 300)
            texts = []
            page_count = len(reader.pages)
            for index in range(min(page_count, max_pages)):
                page = reader.pages[index]
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    texts.append(f"--- PDF page {index + 1} ---\n{page_text}")
            return "\n\n".join(texts).strip(), page_count
        except Exception:
            return "", 0

    def _render_pdf_images(self, payload: bytes) -> list[dict[str, str]]:
        if pdfium is None:
            return []
        max_pages = self._env_int("WEB_FETCH_PDF_OCR_MAX_PAGES", 3, 1, 20)
        scale = max(1, min(4, self._env_int("WEB_FETCH_PDF_RENDER_SCALE", 2, 1, 4)))
        images: list[dict[str, str]] = []
        try:
            pdf = pdfium.PdfDocument(BytesIO(payload))
            for index in range(min(len(pdf), max_pages)):
                page = pdf[index]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                buffer = BytesIO()
                pil_image.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                images.append(
                    {
                        "url": f"data:image/png;base64,{encoded}",
                        "mime_type": "image/png",
                        "page": str(index + 1),
                        "source": "pdf_render",
                    }
                )
        except Exception:
            return images
        return images

    def _env_int(self, name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.getenv(name, default))
        except Exception:
            value = default
        return max(minimum, min(maximum, value))


def _clip_for_error(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


web_search_provider = WebSearchProvider()
