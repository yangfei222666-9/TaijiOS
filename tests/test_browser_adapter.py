from aios.gui_agent.actions import Action
from aios.gui_agent.browser_adapter import ReadOnlyBrowserAdapter
from aios.gui_agent.redaction import contains_secret


def fake_token() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def test_readonly_browser_adapter_opens_registered_page_without_network():
    url = "https://example.taijios.local/report"
    browser = ReadOnlyBrowserAdapter({
        url: f"<html><title>Report</title><body>{fake_token()} visible text</body></html>"
    })

    result = browser.open(url)

    assert result.status == "completed"
    assert result.side_effect is False
    assert result.metadata["network"] is False
    assert result.page is not None
    assert result.page.title == "Report"
    assert "visible text" in result.page.text
    assert contains_secret(result.page.text) is False


def test_readonly_browser_adapter_executes_only_read_actions():
    url = "https://example.taijios.local/report"
    browser = ReadOnlyBrowserAdapter({url: "<html><body>hello</body></html>"})

    navigate = browser.execute(Action("navigate", {"url": url}))
    read = browser.execute(Action("read_current_page"))
    click = browser.execute(Action("click", {"start_box": "[1, 1, 2, 2]"}))

    assert navigate.status == "completed"
    assert read.status == "completed"
    assert read.page is not None
    assert read.page.text == "hello"
    assert click.status == "blocked"
    assert click.side_effect is False


def test_readonly_browser_adapter_blocks_unregistered_pages():
    browser = ReadOnlyBrowserAdapter({"https://example.taijios.local/report": "<html />"})

    result = browser.open("https://other.example/report")

    assert result.status == "blocked"
    assert result.metadata["network"] is False


def test_readonly_browser_adapter_respects_explicit_empty_allowlist():
    browser = ReadOnlyBrowserAdapter(
        {"https://example.taijios.local/report": "<html />"},
        allowed_hosts=set(),
    )

    result = browser.open("https://example.taijios.local/report")

    assert result.status == "blocked"
    assert "host is not allowed" in result.reason


def test_readonly_browser_adapter_blocks_missing_navigation_url():
    browser = ReadOnlyBrowserAdapter({})

    result = browser.execute(Action("navigate", {}))

    assert result.status == "blocked"
    assert "missing url" in result.reason
