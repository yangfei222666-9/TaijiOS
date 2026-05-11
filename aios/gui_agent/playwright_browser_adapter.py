"""Playwright-backed read-only browser adapter.

The adapter intentionally exposes only navigation and text extraction. It does
not provide click, type, submit, download, upload, or form helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from .actions import Action
from .browser_adapter import BrowserActionResult, BrowserPage, ReadOnlyBrowserAdapter
from .redaction import contains_secret, redact_secrets


SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class PlaywrightReadOnlyConfig:
    """Runtime configuration for the Playwright read-only adapter."""

    allowed_hosts: frozenset[str]
    browser_type: str = "chromium"
    headless: bool = True
    timeout_ms: int = 10_000
    block_mutating_requests: bool = True


class PlaywrightReadOnlyBrowserAdapter:
    """Read browser pages through Playwright without exposing GUI actions."""

    READ_ACTIONS = ReadOnlyBrowserAdapter.READ_ACTIONS
    NAVIGATE_ACTIONS = ReadOnlyBrowserAdapter.NAVIGATE_ACTIONS
    BLOCKED_ACTIONS = ReadOnlyBrowserAdapter.BLOCKED_ACTIONS

    def __init__(
        self,
        allowed_hosts: set[str] | frozenset[str],
        *,
        browser_type: str = "chromium",
        headless: bool = True,
        timeout_ms: int = 10_000,
        block_mutating_requests: bool = True,
        page_factory: Callable[[], Any] | None = None,
    ):
        if not allowed_hosts:
            raise ValueError("PlaywrightReadOnlyBrowserAdapter requires allowed_hosts")
        self.config = PlaywrightReadOnlyConfig(
            allowed_hosts=frozenset(allowed_hosts),
            browser_type=browser_type,
            headless=headless,
            timeout_ms=timeout_ms,
            block_mutating_requests=block_mutating_requests,
        )
        self.page_factory = page_factory
        self.current_page: BrowserPage | None = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def open(self, url: str) -> BrowserActionResult:
        """Navigate to an allowed URL and return sanitized page text."""
        if contains_secret(url):
            return BrowserActionResult(
                status="blocked",
                reason="browser url contains secret-like value",
                metadata={"url": "[REDACTED_SECRET]", "network": True},
            )
        if not self._host_allowed(url):
            return BrowserActionResult(
                status="blocked",
                reason="browser host is not allowed",
                metadata={"url": url, "network": True},
            )

        try:
            page = self._ensure_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.timeout_ms,
            )
            title = self._read_title(page)
            text = self._read_body_text(page)
        except ImportError as exc:
            return BrowserActionResult(
                status="blocked",
                reason=str(exc),
                metadata={"url": url, "network": True},
            )
        except Exception as exc:
            return BrowserActionResult(
                status="error",
                reason=f"playwright read-only navigation failed: {exc}",
                metadata={"url": url, "network": True},
            )

        page_state = BrowserPage(
            url=getattr(page, "url", url) or url,
            title=redact_secrets(title),
            text=redact_secrets(text),
        )
        self.current_page = page_state
        return BrowserActionResult(
            status="completed",
            reason="read-only page opened through Playwright",
            page=page_state,
            side_effect=False,
            metadata={
                "url": url,
                "network": True,
                "blocked_mutating_requests": self.config.block_mutating_requests,
                "response_status": self._response_status(response),
            },
        )

    def read_current_page(self) -> BrowserActionResult:
        """Return the last sanitized page state."""
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
            metadata={"url": self.current_page.url, "network": True},
        )

    def execute(self, action: Action) -> BrowserActionResult:
        """Apply only read-only browser actions."""
        action_type = action.action_type
        if action_type in self.NAVIGATE_ACTIONS:
            url = action.inputs.get("url") or action.inputs.get("target")
            if not isinstance(url, str) or not url:
                return BrowserActionResult(
                    status="blocked",
                    reason="navigate action missing url",
                    metadata={"action_type": action_type, "network": True},
                )
            return self.open(url)

        if action_type in self.READ_ACTIONS:
            return self.read_current_page()

        if action_type in self.BLOCKED_ACTIONS:
            return BrowserActionResult(
                status="blocked",
                reason=f"playwright read-only adapter blocks action: {action_type}",
                side_effect=False,
                metadata={"action_type": action_type, "network": True},
            )

        return BrowserActionResult(
            status="blocked",
            reason=f"browser action is not supported: {action_type}",
            side_effect=False,
            metadata={"action_type": action_type, "network": True},
        )

    def handle_route(self, route) -> None:
        """Abort disallowed network requests before the page sees them."""
        request = route.request
        method = getattr(request, "method", "").upper()
        url = getattr(request, "url", "")
        if contains_secret(url) or method not in SAFE_HTTP_METHODS or not self._host_allowed(url):
            route.abort()
            return
        route.continue_()

    def close(self) -> None:
        """Close Playwright resources owned by the adapter."""
        for resource in (self._context, self._browser):
            if resource is not None:
                close = getattr(resource, "close", None)
                if close is not None:
                    close()
        if self._playwright is not None:
            stop = getattr(self._playwright, "stop", None)
            if stop is not None:
                stop()
        self._context = None
        self._browser = None
        self._page = None
        self._playwright = None

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        if self.page_factory is not None:
            self._page = self.page_factory()
            return self._page

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "playwright is not installed; install taijios[browser] and run playwright install"
            ) from exc

        self._playwright = sync_playwright().start()
        browser_launcher = getattr(self._playwright, self.config.browser_type)
        self._browser = browser_launcher.launch(headless=self.config.headless)
        self._context = self._browser.new_context()
        if self.config.block_mutating_requests:
            self._context.route("**/*", self.handle_route)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.config.timeout_ms)
        return self._page

    def _host_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme in {"http", "https"} and parsed.netloc in self.config.allowed_hosts)

    def _read_title(self, page) -> str:
        title = page.title()
        return title if isinstance(title, str) else ""

    def _read_body_text(self, page) -> str:
        if hasattr(page, "inner_text"):
            text = page.inner_text("body", timeout=self.config.timeout_ms)
        else:
            text = page.locator("body").inner_text(timeout=self.config.timeout_ms)
        return text if isinstance(text, str) else ""

    @staticmethod
    def _response_status(response) -> int | None:
        if response is None:
            return None
        return getattr(response, "status", None)
