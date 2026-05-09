"""tools/web.py — minimal web access for AIM Generalist.

  web_fetch(url, *, max_chars=8000)  → str    HTML→readable text
  web_search(query, *, n=8)          → list   DuckDuckGo HTML scrape (no key)

No API keys required. Honours basic rate-limit + 10s timeout.
Stripped of JS/scripts; output is plain text suitable for LLM consumption.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Optional

import httpx

log = logging.getLogger("aim.web")

UA = ("AIM/7.0 (research-agent; +https://longevity.ge; contact: jaba@longevity.ge) "
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Lightweight politeness gate
_LAST_CALL: dict[str, float] = {}


def _throttle(host: str, min_interval: float = 0.5) -> None:
    last = _LAST_CALL.get(host, 0)
    delta = time.time() - last
    if delta < min_interval:
        time.sleep(min_interval - delta)
    _LAST_CALL[host] = time.time()


# ── HTML → text ────────────────────────────────────────────────────────────


_TAG_DROP = re.compile(
    r"<(script|style|noscript|svg|head|nav|footer|aside|form|iframe|template)"
    r"\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str, *, max_chars: int = 8000) -> str:
    if not html:
        return ""
    text = _TAG_DROP.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    # Decode common HTML entities
    for k, v in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(k, v)
    return text[:max_chars]


# ── Public ─────────────────────────────────────────────────────────────────


def web_fetch(url: str, *, max_chars: int = 8000,
              timeout: float = 10.0) -> str:
    """Fetch a URL, strip HTML, return plain text. ERROR string on failure."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = urllib.parse.urlparse(url).hostname or "?"
    _throttle(host)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": UA}) as c:
            r = c.get(url)
        if r.status_code >= 400:
            return f"ERROR: HTTP {r.status_code} from {host}"
        ct = r.headers.get("content-type", "")
        if "html" in ct.lower() or url.endswith((".html", ".htm")) or not ct:
            return _html_to_text(r.text, max_chars=max_chars)
        if "json" in ct.lower():
            return r.text[:max_chars]
        # plain text fallback
        return r.text[:max_chars]
    except httpx.RequestError as e:
        return f"ERROR: fetch failed ({type(e).__name__}: {e})"
    except Exception as e:
        return f"ERROR: {e}"


# ── Search via DuckDuckGo HTML ────────────────────────────────────────────


_DDG_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?(?:<a[^>]*class="result__snippet"[^>]*>(.*?)</a>'
    r'|<div[^>]*class="result__snippet"[^>]*>(.*?)</div>)',
    re.IGNORECASE | re.DOTALL,
)


def web_search(query: str, *, n: int = 8, timeout: float = 10.0) -> list[dict]:
    """Search the web (no API key). Returns list[{title, url, snippet}].

    Backed by DuckDuckGo's HTML endpoint — works without auth, modest
    rate-limits. Strips HTML tags from snippets.
    """
    q = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    _throttle("duckduckgo.com", 0.8)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": UA}) as c:
            r = c.get(url)
        if r.status_code >= 400:
            return []
        html = r.text
    except httpx.RequestError as e:
        log.warning(f"web_search failed: {e}")
        return []

    results = []
    for m in _DDG_RESULT_RE.finditer(html):
        href, title_html, snip1, snip2 = m.groups()
        title = _html_to_text(title_html, max_chars=200)
        snippet = _html_to_text(snip1 or snip2 or "", max_chars=300)
        # DDG wraps target in a redirect; unwrap
        parsed = urllib.parse.urlparse(href)
        if parsed.path == "/l/" and "uddg" in (parsed.query or ""):
            qs = urllib.parse.parse_qs(parsed.query)
            real = qs.get("uddg", [None])[0]
            if real:
                href = urllib.parse.unquote(real)
        if not href.startswith(("http://", "https://")):
            continue
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= n:
            break
    return results
