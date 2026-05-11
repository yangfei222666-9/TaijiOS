from aios.gui_agent import Action, Screenshot, TaijiWindowsOperator


class FakeWindowsBackend:
    def __init__(self):
        self.calls = []

    def capture_screen(self):
        self.calls.append(("capture_screen",))
        return Screenshot(base64="iVBORw0KGgo=", width=100, height=100)

    def move_to(self, x, y):
        self.calls.append(("move_to", x, y))

    def left_click(self):
        self.calls.append(("left_click",))

    def double_click(self):
        self.calls.append(("double_click",))

    def right_click(self):
        self.calls.append(("right_click",))

    def scroll(self, direction, amount=5):
        self.calls.append(("scroll", direction, amount))

    def type_text(self, text):
        self.calls.append(("type_text", text))

    def hotkey(self, key_spec):
        self.calls.append(("hotkey", key_spec))


def test_windows_operator_maps_click_to_backend():
    backend = FakeWindowsBackend()
    operator = TaijiWindowsOperator(backend=backend)

    result = operator.execute(
        Action("click", {"start_coords": (12.3, 45.6)})
    )

    assert result.status == "executed"
    assert backend.calls == [("move_to", 12.3, 45.6), ("left_click",)]


def test_windows_operator_types_text_and_submit_without_clipboard():
    backend = FakeWindowsBackend()
    operator = TaijiWindowsOperator(backend=backend)

    result = operator.execute(Action("type", {"content": "hello\\n"}))

    assert result.status == "executed"
    assert backend.calls == [("type_text", "hello"), ("hotkey", "enter")]


def test_windows_operator_screenshots_via_backend():
    backend = FakeWindowsBackend()
    operator = TaijiWindowsOperator(backend=backend)

    screenshot = operator.screenshot()

    assert screenshot.width == 100
    assert backend.calls == [("capture_screen",)]


def test_windows_operator_reports_unsupported_actions():
    backend = FakeWindowsBackend()
    operator = TaijiWindowsOperator(backend=backend)

    result = operator.execute(Action("navigate", {"content": "example.com"}))

    assert result.status == "unsupported"
    assert backend.calls == []
