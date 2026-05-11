"""Read-only browser adapter for TaijiOS GUI agent POCs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from .actions import Action
from .redaction import redact_secrets


class TextExtractor(HTMLParser):
    """Small HTML text extractor for browser read-only tasks."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self._parts.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self._parts)


@dataclass(frozen=True)
class BrowserPage:
    """Sanitized page state returned by a read-only browser adapter."""

    url: str
    title: str
    text: str


@dataclass(frozen=True)
class BrowserActionResult:
    """Result of a browser adapter action."""

    status: str
    reason: str
    page: BrowserPage | None = None
    side_effect: bool = False
    metadata: dict = field(default_factory=dict)


class ReadOnlyBrowserAdapter:
    """Offline browser facade that can only open registered pages and read text."""

    READ_ACTIONS = frozenset({"read_page", "read_current_page"})
    NAVIGATE_ACTIONS = frozenset({"navigate", "open_url"})
    BLOCKED_ACTIONS = frozenset(
        {
            "click",
            "left_click",
            "left_single",
            "left_double",
            "double_click",
            "right_click",
            "right_single",
            "drag",
            "type",
            "hotkey",
            "press",
            "release",
            "submit",
            "checkout",
            "buy",
            "sell",
            "trade",
        }
    )

    def __init__(
        self,
        pages: dict[str, str],
        allowed_hosts: set[str] | None = None,
    ):
        self.pages = pages
        if allowed_hosts is None:
            self.allowed_hosts = {
                urlparse(url).netloc for url in pages if urlparse(url).netloc
            }
        else:
            self.allowed_hosts = set(allowed_hosts)
        self.current_page: BrowserPage | None = None

    def open(self, url: str) -> BrowserActionResult:
        """Open a registered page without using network access."""
        if not self._host_allowed(url):
            return BrowserActionResult(
                status="blocked",
                reason="browser host is not allowed",
                metadata={"url": url, "network": False},
            )
        if url not in self.pages:
            return BrowserActionResult(
                status="blocked",
                reason="browser page is not registered for read-only access",
                metadata={"url": url, "network": False},
            )

        page = self._parse_page(url, self.pages[url])
        self.current_page = page
        return BrowserActionResult(
            status="completed",
            reason="read-only page opened from registered content",
            page=page,
            side_effect=False,
            metadata={"url": url, "network": False},
        )

    def read_current_page(self) -> BrowserActionResult:
        """Return sanitized text for the current page."""
        if self.current_page is None:
            return BrowserActionResult(
                status="blocked",
                reason="no current page is open",
                side_effect=False,
            )
        return BrowserActionResult(
            status="completed",
            reason="read-only page text returned",
            page=self.current_page,
            side_effect=False,
            metadata={"url": self.current_page.url, "network": False},
        )

    def execute(self, action: Action) -> BrowserActionResult:
        """Apply a browser action using read-only semantics."""
        action_type = action.action_type
        if action_type in self.NAVIGATE_ACTIONS:
            url = action.inputs.get("url") or action.inputs.get("target")
            if not isinstance(url, str) or not url:
                return BrowserActionResult(
                    status="blocked",
                    reason="navigate action missing url",
                    metadata={"action_type": action_type},
                )
            return self.open(url)

        if action_type in self.READ_ACTIONS:
            return self.read_current_page()

        if action_type in self.BLOCKED_ACTIONS:
            return BrowserActionResult(
                status="blocked",
                reason=f"browser read-only adapter blocks action: {action_type}",
                side_effect=False,
                metadata={"action_type": action_type},
            )

        return BrowserActionResult(
            status="blocked",
            reason=f"browser action is not supported: {action_type}",
            side_effect=False,
            metadata={"action_type": action_type},
        )

    def _host_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme in {"http", "https"} and parsed.netloc in self.allowed_hosts)

    def _parse_page(self, url: str, html: str) -> BrowserPage:
        parser = TextExtractor()
        parser.feed(html)
        title_match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
        title = " ".join(title_match.group(1).split()) if title_match else Path(url).name
        return BrowserPage(
            url=url,
            title=redact_secrets(title),
            text=redact_secrets(parser.text),
        )
