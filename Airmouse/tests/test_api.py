import math

import pytest

import app as air


class FakeSize:
    width = 1920
    height = 1080


class FakePyAutoGUI:
    def __init__(self):
        self.calls = []

    def size(self):
        return FakeSize()

    def moveTo(self, x, y, **kwargs):
        self.calls.append(("move", x, y))

    def click(self, button, **kwargs):
        self.calls.append(("click", button))

    def scroll(self, amount, **kwargs):
        self.calls.append(("scroll", amount))


class FakeUInputDevice:
    def __init__(self):
        self.calls = []

    def emit(self, event, value, syn=True):
        self.calls.append((event, value, syn))


@pytest.fixture(autouse=True)
def setup_api(monkeypatch):
    # Reset the mouse backend singleton state
    air.mouse._backend_type = None
    air.mouse._screen_size = None
    air._pyautogui = None
    air._pyautogui_error = None
    air._pyautogui_attempted = False
    air._uinput_device = None
    air._uinput_error = None
    air._uinput_attempted = False
    air._uinput_screen_size = None
    monkeypatch.setattr(air, "_ydotool_path", None)
    monkeypatch.setattr(air, "_ydotool_error", None)

    # Mock PyAutoGUI
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(air, "_pyautogui", fake_pyautogui)
    monkeypatch.setattr(air, "_pyautogui_error", None)
    monkeypatch.setattr(air, "_pyautogui_attempted", True)

    # Mock uinput device
    fake_uinput = FakeUInputDevice()
    monkeypatch.setattr(air, "_uinput_device", fake_uinput)
    monkeypatch.setattr(air, "_uinput_error", None)
    monkeypatch.setattr(air, "_uinput_attempted", True)
    monkeypatch.setattr(air, "_uinput_screen_size", (1920, 1080))

    # Mock the uinput module
    class MockUInput:
        REL_X = 0x00
        REL_Y = 0x01
        REL_WHEEL = 0x08
        REL_HWHEEL = 0x09
        BTN_LEFT = 0x110
        BTN_RIGHT = 0x111
        BTN_MIDDLE = 0x112
        ABS_X = 0x00
        ABS_Y = 0x01

        class Device:
            def __init__(self, *args, **kwargs):
                pass

            def emit(self, event, value, syn=True):
                pass

    monkeypatch.setitem(__import__('sys').modules, 'uinput', MockUInput)

    with air._rate_lock:
        air._request_times.clear()

    yield fake_pyautogui


@pytest.fixture
def client():
    air.app.config.update(TESTING=True)
    return air.app.test_client()


def test_health_and_resolution(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["status"] == "ok"
    assert health.json["desktop"]["screen"] == {"width": 1920, "height": 1080}
    assert client.get("/api/screen").json["screen"]["width"] == 1920


@pytest.mark.parametrize("payload", [{}, {"x": "12", "y": 5}, {"x": True, "y": 0}, {"x": math.inf, "y": 0}, {"x": math.nan, "y": 0}])
def test_move_rejects_invalid_coordinates(client, payload):
    response = client.post("/api/move", json=payload)
    assert response.status_code == 400


def test_move_clamps_to_screen_edges(client, setup_api):
    # Force PyAutoGUI backend for this test
    air.mouse._backend_type = "pyautogui"
    air.mouse._screen_size = (1920, 1080)

    low = client.post("/api/move", json={"x": -20, "y": -3})
    high = client.post("/api/move", json={"x": 99999, "y": 99999})
    assert low.json == {"ok": True, "x": 0, "y": 0}
    assert high.json == {"ok": True, "x": 1919, "y": 1079}
    assert setup_api.calls == [("move", 0, 0), ("move", 1919, 1079)]


@pytest.mark.parametrize("payload", [{}, {"button": "middle"}, {"button": "LEFT"}])
def test_click_only_accepts_supported_buttons(client, payload):
    assert client.post("/api/click", json=payload).status_code == 400


@pytest.mark.parametrize("value", [0, 11, -11, 1.5, True, "3"])
def test_scroll_rejects_invalid_values(client, value):
    assert client.post("/api/scroll", json={"amount": value}).status_code == 400


def test_scroll_accepts_limited_values(client, setup_api):
    # Force PyAutoGUI backend for this test
    air.mouse._backend_type = "pyautogui"
    air.mouse._screen_size = (1920, 1080)

    for value in [-10, -1, 1, 10]:
        response = client.post("/api/scroll", json={"amount": value})
        assert response.status_code == 200
        assert setup_api.calls[-1] == ("scroll", value)


def test_request_shape_required(client):
    assert client.post("/api/move", data="[]", content_type="application/json").status_code == 400
    assert client.post("/api/move", data="{", content_type="application/json").status_code == 400
    assert client.post("/api/move", data="{}", content_type="text/plain").status_code == 415


def test_origin_guard(client):
    bad = client.post("/api/click", json={"button": "left"}, headers={"Origin": "https://example.com"})
    assert bad.status_code == 403
    good = client.post("/api/click", json={"button": "right"}, headers={"Origin": "http://127.0.0.1:5000"})
    assert good.status_code == 200


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(air, "RATE_LIMIT", 2)
    assert client.post("/api/scroll", json={"amount": 1}).status_code == 200
    assert client.post("/api/scroll", json={"amount": 1}).status_code == 200
    assert client.post("/api/scroll", json={"amount": 1}).status_code == 429


def test_mouse_errors_are_reported_without_crash(client, monkeypatch):
    class Broken:
        def size(self):
            raise RuntimeError("display refused")

    monkeypatch.setattr(air, "_pyautogui", Broken())
    monkeypatch.setattr(air, "_pyautogui_error", None)
    monkeypatch.setattr(air, "_pyautogui_attempted", True)
    monkeypatch.setattr(air, "_uinput_device", None)
    monkeypatch.setattr(air, "_uinput_error", "uinput not available")
    monkeypatch.setattr(air, "_uinput_attempted", True)
    air.mouse._backend_type = None
    air.mouse._screen_size = None

    assert client.post("/api/move", json={"x": 1, "y": 1}).status_code == 503


def test_page_and_static_assets_load(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"AirMouse" in page.data
    html = page.get_data(as_text=True)
    assert '/static/style.css' in html
    assert '/static/app.js' in html
    assert client.get('/static/style.css').status_code == 200
    assert client.get('/static/app.js').status_code == 200


def test_wayland_without_authorized_display_is_reported_unavailable(client, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")

    class DisplayDenied:
        def size(self):
            raise RuntimeError("display authorization denied")

    monkeypatch.setattr(air, "_pyautogui", DisplayDenied())
    monkeypatch.setattr(air, "_pyautogui_error", None)
    monkeypatch.setattr(air, "_pyautogui_attempted", True)
    monkeypatch.setattr(air, "_uinput_device", None)
    monkeypatch.setattr(air, "_uinput_error", "uinput not available")
    monkeypatch.setattr(air, "_uinput_attempted", True)
    air.mouse._backend_type = None
    air.mouse._screen_size = None

    status = client.get("/api/health").json["desktop"]
    assert status["mouseControl"] == "unavailable"
    assert status["screen"] is None


def test_move_failure_does_not_escape_api(client, monkeypatch):
    class FailsOnMove(FakePyAutoGUI):
        def moveTo(self, x, y, **kwargs):
            raise RuntimeError("input blocked")

    monkeypatch.setattr(air, "_pyautogui", FailsOnMove())
    monkeypatch.setattr(air, "_pyautogui_error", None)
    monkeypatch.setattr(air, "_pyautogui_attempted", True)
    monkeypatch.setattr(air, "_uinput_device", None)
    monkeypatch.setattr(air, "_uinput_error", "uinput not available")
    monkeypatch.setattr(air, "_uinput_attempted", True)
    air.mouse._backend_type = None
    air.mouse._screen_size = None

    response = client.post("/api/move", json={"x": 40, "y": 60})
    assert response.status_code == 503
    assert response.json["error"] == "Desktop mouse action failed"


def test_wayland_prefers_ydotool_and_uses_absolute_moves(client, monkeypatch):
    calls = []
    monkeypatch.setattr(air, "_ydotool_path", "/usr/local/bin/ydotool")
    monkeypatch.setattr(air, "_ydotool_ready", lambda: True)
    monkeypatch.setattr(air, "_ydotool_emit", lambda events: calls.append(events))
    monkeypatch.setattr(air, "IS_WAYLAND", True)
    air.mouse._backend_type = None
    air.mouse._screen_size = (1920, 1080)

    status = client.get("/api/health").json["desktop"]
    assert status["mouseControl"] == "available"
    assert status["inputMethod"] == "ydotool"
    response = client.post("/api/move", json={"x": 800, "y": 400})
    assert response.status_code == 200
    assert calls[-1] == [
        (2, 0, -2147483648, False), (2, 1, -2147483648, True),
        (2, 0, 800, False), (2, 1, 400, True),
    ]


def test_ydotool_click_and_scroll_commands(client, monkeypatch):
    calls = []
    monkeypatch.setattr(air, "_ydotool_path", "/usr/local/bin/ydotool")
    monkeypatch.setattr(air, "_ydotool_ready", lambda: True)
    monkeypatch.setattr(air, "_ydotool_emit", lambda events: calls.append(events))
    monkeypatch.setattr(air, "IS_WAYLAND", True)
    air.mouse._backend_type = None
    air.mouse._screen_size = (1920, 1080)

    assert client.post("/api/click", json={"button": "left"}).status_code == 200
    assert calls[-1] == [(1, 0x110, 1, True), (1, 0x110, 0, True)]
    assert client.post("/api/click", json={"button": "right"}).status_code == 200
    assert calls[-1] == [(1, 0x111, 1, True), (1, 0x111, 0, True)]
    assert client.post("/api/scroll", json={"amount": 3}).status_code == 200
    assert calls[-1] == [(2, 6, 0, False), (2, 8, 3, True)]


def test_ydotool_stale_socket_is_not_reported_ready(monkeypatch):
    class RefusedSocket:
        def connect(self, path):
            raise ConnectionRefusedError("daemon stopped")

        def close(self):
            pass

    monkeypatch.setattr(air, "_ydotool_path", "/usr/local/bin/ydotool")
    monkeypatch.setattr(air, "_ydotool_socket", "/run/user/1000/.ydotool_socket")
    monkeypatch.setattr(air, "_ydotool_client", None)
    monkeypatch.setattr(air.os.path, "exists", lambda path: True)
    monkeypatch.setattr(air.socket, "socket", lambda *args, **kwargs: RefusedSocket())
    assert air._ydotool_ready() is False
    assert "not accepting connections" in air._ydotool_error
