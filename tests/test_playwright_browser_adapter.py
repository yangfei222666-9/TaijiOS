from aios.gui_agent.actions import Action
from aios.gui_agent.playwright_browser_adapter import PlaywrightReadOnlyBrowserAdapter
from aios.gui_agent.redaction import contains_secret


def fake_token() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def fake_api_key() -> str:
    return "api" + "_key=" + "sk-demo-" + "secret-00000000"


class FakeResponse:
    status = 200


class FakePage:
    def __init__(self):
        self.url = ""
        self.goto_calls = []
        self.default_timeout = None

    def goto(self, url, wait_until, timeout):
        self.url = url
        self.goto_calls.append({
            "url": url,
            "wait_until": wait_until,
            "timeout": timeout,
        })
        return FakeResponse()

    def title(self):
        return f"Console {fake_token()}"

    def inner_text(self, selector, timeout):
        assert selector == "body"
        assert timeout == 10000
        return f"Visible body {fake_api_key()}"

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout


class FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


class FakeRoute:
    def __init__(self, method, url):
        self.request = FakeRequest(method, url)
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


def test_playwright_readonly_adapter_reads_allowed_page_with_fake_page():
    page = FakePage()
    adapter = PlaywrightReadOnlyBrowserAdapter(
        allowed_hosts={"example.taijios.local"},
        page_factory=lambda: page,
    )

    result = adapter.open("https://example.taijios.local/report")

    assert result.status == "completed"
    assert result.side_effect is False
    assert result.metadata["network"] is True
    assert result.metadata["blocked_mutating_requests"] is True
    assert result.metadata["response_status"] == 200
    assert page.goto_calls == [{
        "url": "https://example.taijios.local/report",
        "wait_until": "domcontentloaded",
        "timeout": 10000,
    }]
    assert result.page is not None
    assert contains_secret(result.page.title) is False
    assert contains_secret(result.page.text) is False
    assert "[REDACTED_SECRET]" in result.page.text


def test_playwright_readonly_adapter_blocks_disallowed_host_before_navigation():
    page = FakePage()
    adapter = PlaywrightReadOnlyBrowserAdapter(
        allowed_hosts={"example.taijios.local"},
        page_factory=lambda: page,
    )

    result = adapter.open("https://other.example/report")

    assert result.status == "blocked"
    assert "host is not allowed" in result.reason
    assert page.goto_calls == []


def test_playwright_readonly_adapter_execute_blocks_side_effect_actions():
    adapter = PlaywrightReadOnlyBrowserAdapter(
        allowed_hosts={"example.taijios.local"},
        page_factory=FakePage,
    )

    result = adapter.execute(Action("click", {"start_box": "[1, 1, 2, 2]"}))

    assert result.status == "blocked"
    assert result.side_effect is False
    assert "blocks action" in result.reason


def test_playwright_readonly_adapter_execute_supports_read_actions():
    adapter = PlaywrightReadOnlyBrowserAdapter(
        allowed_hosts={"example.taijios.local"},
        page_factory=FakePage,
    )

    navigate = adapter.execute(Action("navigate", {"url": "https://example.taijios.local/report"}))
    read = adapter.execute(Action("read_current_page"))

    assert navigate.status == "completed"
    assert read.status == "completed"
    assert read.page is not None
    assert read.page.url == "https://example.taijios.local/report"


def test_playwright_readonly_adapter_route_guard_allows_safe_allowed_request():
    adapter = PlaywrightReadOnlyBrowserAdapter(allowed_hosts={"example.taijios.local"})
    route = FakeRoute("GET", "https://example.taijios.local/report")

    adapter.handle_route(route)

    assert route.continued is True
    assert route.aborted is False


def test_playwright_readonly_adapter_route_guard_blocks_mutating_request():
    adapter = PlaywrightReadOnlyBrowserAdapter(allowed_hosts={"example.taijios.local"})
    route = FakeRoute("POST", "https://example.taijios.local/report")

    adapter.handle_route(route)

    assert route.aborted is True
    assert route.continued is False


def test_playwright_readonly_adapter_route_guard_blocks_cross_host_request():
    adapter = PlaywrightReadOnlyBrowserAdapter(allowed_hosts={"example.taijios.local"})
    route = FakeRoute("GET", "https://tracker.example/pixel")

    adapter.handle_route(route)

    assert route.aborted is True
    assert route.continued is False


def test_playwright_readonly_adapter_route_guard_blocks_secret_url():
    adapter = PlaywrightReadOnlyBrowserAdapter(allowed_hosts={"example.taijios.local"})
    route = FakeRoute("GET", f"https://example.taijios.local/pixel?{fake_token()}")

    adapter.handle_route(route)

    assert route.aborted is True
    assert route.continued is False


def test_playwright_readonly_adapter_requires_allowed_hosts():
    try:
        PlaywrightReadOnlyBrowserAdapter(allowed_hosts=set())
    except ValueError as exc:
        assert "requires allowed_hosts" in str(exc)
    else:
        raise AssertionError("expected ValueError")
