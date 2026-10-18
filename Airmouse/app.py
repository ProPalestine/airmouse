"""Local-only AirMouse Flask API. Browser-side hand data is never persisted."""
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from typing import Any, Optional

from flask import Flask, jsonify, render_template, request

# ─── Backend detection ──────────────────────────────────────────────
SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "unknown").lower()
IS_WAYLAND = SESSION_TYPE == "wayland"

# ─── PyAutoGUI (X11/XWayland) ──────────────────────────────────────
_pyautogui = None
_pyautogui_error: Optional[str] = None
_pyautogui_attempted = False


def _load_pyautogui():
    global _pyautogui, _pyautogui_error, _pyautogui_attempted
    if _pyautogui_attempted:
        return _pyautogui
    _pyautogui_attempted = True
    try:
        import pyautogui as backend
        backend.size()
        _pyautogui = backend
        _pyautogui_error = None
        try:
            _pyautogui.FAILSAFE = True
            _pyautogui.PAUSE = 0
        except Exception:
            pass
    except Exception as exc:
        _pyautogui_error = f"{type(exc).__name__}: {exc}"
    return _pyautogui


# ─── python-uinput (Wayland / uinput) ──────────────────────────────
_uinput_device = None
_uinput_error: Optional[str] = None
_uinput_attempted = False
_uinput_lock = threading.Lock()

# Screen dimensions cache for uinput (absolute coordinates need screen size)
_uinput_screen_size: Optional[tuple[int, int]] = None

# ydotool talks to ydotoold over its Unix socket. The user's systemd user unit
# creates /run/user/$UID/.ydotool_socket; the client must run as that same user.
_ydotool_path = shutil.which("ydotool") or ("/usr/local/bin/ydotool" if os.path.exists("/usr/local/bin/ydotool") else None)
_ydotool_socket = os.environ.get("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")
_ydotool_error: Optional[str] = None
_ydotool_client: Optional[socket.socket] = None
_ydotool_lock = threading.RLock()
_ydotool_events_sent = 0
_ydotool_last_action_at: Optional[float] = None


def _ydotool_send_event(event_type: int, code: int, value: int) -> None:
    """Send one Linux input_event datagram to ydotoold without spawning a process."""
    global _ydotool_client, _ydotool_error, _ydotool_events_sent
    if not _ydotool_ready():
        raise RuntimeError(_ydotool_error or "ydotoold is unavailable")
    now = time.time()
    payload = struct.pack("@llHHi", int(now), int((now % 1) * 1_000_000), event_type, code, value)
    with _ydotool_lock:
        for attempt in range(2):
            try:
                if _ydotool_client is None:
                    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                    client.connect(_ydotool_socket)
                    _ydotool_client = client
                sent = _ydotool_client.send(payload)
                if sent != len(payload):
                    raise OSError(f"short ydotool datagram write ({sent}/{len(payload)})")
                _ydotool_events_sent += 1
                _ydotool_error = None
                return
            except OSError as exc:
                if _ydotool_client is not None:
                    _ydotool_client.close()
                    _ydotool_client = None
                _ydotool_error = f"ydotoold socket send failed: {type(exc).__name__}: {exc}"
                if attempt:
                    raise RuntimeError(_ydotool_error) from exc


def _ydotool_emit(events: list[tuple[int, int, int, bool]]) -> None:
    """Send (type, code, value, syn_after) events, matching ydotool's frames."""
    # Keep each logical action contiguous; Flask serves multiple gesture
    # requests concurrently, and interleaved SYN frames corrupt pointer events.
    global _ydotool_last_action_at
    with _ydotool_lock:
        for event_type, code, value, syn_after in events:
            _ydotool_send_event(event_type, code, value)
            if syn_after:
                _ydotool_send_event(0, 0, 0)  # EV_SYN / SYN_REPORT
        _ydotool_last_action_at = time.time()


def _ydotool_ready() -> bool:
    """Check that ydotoold accepts a socket connection; do not inject input."""
    global _ydotool_error, _ydotool_client
    if not _ydotool_path:
        _ydotool_error = "ydotool executable not found"
        return False
    if not os.path.exists(_ydotool_socket):
        _ydotool_error = f"ydotoold socket not found: {_ydotool_socket}"
        return False
    with _ydotool_lock:
        if _ydotool_client is not None:
            try:
                _ydotool_client.send(b"")
                return True
            except OSError:
                try:
                    _ydotool_client.close()
                except OSError:
                    pass
                _ydotool_client = None
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            client.connect(_ydotool_socket)
            _ydotool_client = client
            _ydotool_error = None
            return True
        except OSError as exc:
            error_text = f"ydotoold socket is not accepting connections: {type(exc).__name__}: {exc}"
            try:
                client.close()
            except (OSError, UnboundLocalError):
                pass
            _ydotool_error = error_text
            return False


def _load_uinput():
    """Initialize uinput virtual mouse device. Requires /dev/uinput access (user in 'input' group)."""
    global _uinput_device, _uinput_error, _uinput_attempted, _uinput_screen_size
    if _uinput_attempted:
        return _uinput_device
    _uinput_attempted = True

    try:
        import uinput
    except Exception as exc:
        _uinput_error = f"python-uinput import failed: {type(exc).__name__}: {exc}"
        return None

    # Get screen dimensions for absolute coordinate mapping
    try:
        if IS_WAYLAND:
            # On Wayland, try to get screen size from environment or use defaults
            # We'll use a reasonable default and update if we get actual size
            _uinput_screen_size = (1920, 1080)
        else:
            # On X11, we could use PyAutoGUI, but for uinput we'll use defaults
            _uinput_screen_size = (1920, 1080)
    except Exception:
        _uinput_screen_size = (1920, 1080)

    # Define uinput device capabilities
    events = (
        uinput.REL_X, uinput.REL_Y, uinput.REL_WHEEL, uinput.REL_HWHEEL,
        uinput.BTN_LEFT, uinput.BTN_RIGHT, uinput.BTN_MIDDLE,
        uinput.ABS_X, uinput.ABS_Y,
    )

    try:
        with _uinput_lock:
            _uinput_device = uinput.Device(events, name="AirMouse Virtual Mouse", version=0x100)
        _uinput_error = None
    except PermissionError:
        _uinput_error = "Permission denied: /dev/uinput not accessible. Add user to 'input' group and reload udev rules."
    except FileNotFoundError:
        _uinput_error = "/dev/uinput not found. Enable uinput kernel module: sudo modprobe uinput"
    except Exception as exc:
        _uinput_error = f"uinput device creation failed: {type(exc).__name__}: {exc}"

    return _uinput_device


def _get_screen_size() -> tuple[int, int]:
    """Get screen dimensions for coordinate mapping."""
    # Try PyAutoGUI first (works on X11)
    pyautogui = _load_pyautogui()
    if pyautogui:
        try:
            size = pyautogui.size()
            return (int(size.width), int(size.height))
        except Exception:
            pass

    # Fallback to cached uinput size or defaults
    if _uinput_screen_size:
        return _uinput_screen_size

    # Try to get from environment (some Wayland compositors expose this)
    try:
        import subprocess
        result = subprocess.run(["xdpyinfo"], capture_output=True, text=True, timeout=2)
        for line in result.stdout.splitlines():
            if "dimensions:" in line:
                parts = line.split()
                for p in parts:
                    if "x" in p and p.replace("x", "").isdigit():
                        w, h = p.split("x")
                        return (int(w), int(h))
    except Exception:
        pass

    return (1920, 1080)  # Safe default


# ─── Unified Mouse Backend ─────────────────────────────────────────
class MouseBackend:
    """Unified interface for mouse control across X11 and Wayland."""

    def __init__(self):
        self._backend_type: Optional[str] = None  # "ydotool" | "pyautogui" | "uinput" | None
        self._screen_size: Optional[tuple[int, int]] = None

    def _ensure_backend(self) -> bool:
        """Initialize the appropriate backend for the current session."""
        if self._backend_type:
            return True

        if IS_WAYLAND:
            # GNOME/Mutter ignores direct python-uinput injection. ydotoold is
            # the supported user-session broker for virtual input on Wayland.
            if _ydotool_ready():
                self._backend_type = "ydotool"
                self._screen_size = _get_screen_size()
                return True
            # Try uinput first on Wayland
            device = _load_uinput()
            if device:
                self._backend_type = "uinput"
                self._screen_size = _get_screen_size()
                return True
            # Fallback to PyAutoGUI (might work on XWayland)
            pyautogui = _load_pyautogui()
            if pyautogui:
                self._backend_type = "pyautogui"
                self._screen_size = _get_screen_size()
                return True
        else:
            # X11 session - use PyAutoGUI
            pyautogui = _load_pyautogui()
            if pyautogui:
                self._backend_type = "pyautogui"
                self._screen_size = _get_screen_size()
                return True
            # Fallback to uinput
            device = _load_uinput()
            if device:
                self._backend_type = "uinput"
                self._screen_size = _get_screen_size()
                return True

        return False

    def is_available(self) -> tuple[bool, Optional[str]]:
        if not self._ensure_backend():
            errors = []
            if _pyautogui_error:
                errors.append(f"PyAutoGUI: {_pyautogui_error}")
            if _uinput_error:
                errors.append(f"uinput: {_uinput_error}")
            if _ydotool_error:
                errors.append(f"ydotool: {_ydotool_error}")
            return False, "; ".join(errors) if errors else "No mouse backend available"

        # Verify the backend actually works by testing it
        try:
            if self._backend_type in {"uinput", "ydotool"}:
                # uinput device creation already succeeded in _load_uinput
                if self._backend_type == "ydotool" and not _ydotool_ready():
                    raise RuntimeError(_ydotool_error or "ydotoold is unavailable")
            else:
                # Test PyAutoGUI by calling size()
                _pyautogui.size()
        except Exception as exc:
            self._backend_type = None
            self._screen_size = None
            return False, f"{type(exc).__name__}: {exc}"

        return True, None

    def get_screen_size(self) -> tuple[int, int]:
        if self._screen_size:
            return self._screen_size
        self._screen_size = _get_screen_size()
        return self._screen_size

    def move(self, x: int, y: int) -> tuple[int, int]:
        if not self._ensure_backend():
            raise RuntimeError("No mouse backend available")

        width, height = self.get_screen_size()
        clamped_x = max(0, min(int(round(x)), width - 1))
        clamped_y = max(0, min(int(round(y)), height - 1))

        if self._backend_type == "ydotool":
            # Match ydotool mousemove --absolute, but write directly to the
            # daemon socket to avoid fork/exec overhead on every camera frame.
            _ydotool_emit([
                (2, 0, -2147483648, False),  # EV_REL / REL_X absolute-mode marker
                (2, 1, -2147483648, True),  # ydotool SYN_REPORT after marker pair
                (2, 0, clamped_x, False),
                (2, 1, clamped_y, True),
            ])
        elif self._backend_type == "uinput":
            import uinput
            with _uinput_lock:
                # uinput uses absolute coordinates (0 to width/height)
                _uinput_device.emit(uinput.ABS_X, clamped_x, syn=False)
                _uinput_device.emit(uinput.ABS_Y, clamped_y, syn=True)
        else:
            _pyautogui.moveTo(clamped_x, clamped_y, _pause=False)

        return clamped_x, clamped_y

    def click(self, button: str) -> str:
        if not self._ensure_backend():
            raise RuntimeError("No mouse backend available")

        if self._backend_type == "ydotool":
            button_code = 0x110 if button == "left" else 0x111
            _ydotool_emit([(1, button_code, 1, True), (1, button_code, 0, True)])
        elif self._backend_type == "uinput":
            import uinput
            btn = uinput.BTN_LEFT if button == "left" else uinput.BTN_RIGHT
            with _uinput_lock:
                _uinput_device.emit(btn, 1)
                _uinput_device.emit(btn, 0)
        else:
            _pyautogui.click(button=button, _pause=False)

        return button

    def scroll(self, amount: int) -> int:
        if not self._ensure_backend():
            raise RuntimeError("No mouse backend available")

        if self._backend_type == "ydotool":
            _ydotool_emit([(2, 6, 0, False), (2, 8, int(amount), True)])  # REL_HWHEEL, REL_WHEEL
        elif self._backend_type == "uinput":
            import uinput
            with _uinput_lock:
                _uinput_device.emit(uinput.REL_WHEEL, amount)
        else:
            _pyautogui.scroll(int(amount), _pause=False)

        return amount

    def get_backend_info(self) -> dict[str, Any]:
        available, error = self.is_available()
        return {
            "backend": self._backend_type,
            "available": available,
            "error": error,
            "screen": {"width": self.get_screen_size()[0], "height": self.get_screen_size()[1]} if available else None,
        }


# ─── Flask App ─────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096
LOCAL_ORIGINS = {"http://127.0.0.1:5000", "http://localhost:5000"}
RATE_LIMIT = 90  # all mouse actions combined, per second
_request_times: deque[float] = deque()
_rate_lock = threading.Lock()
_mouse_lock = threading.Lock()

mouse = MouseBackend()


def _desktop_status() -> dict[str, Any]:
    display = os.environ.get("DISPLAY")
    wayland = os.environ.get("WAYLAND_DISPLAY")
    info = mouse.get_backend_info()

    if info["available"]:
        control = "available"
        detail = f"Mouse control active via {info['backend']}."
        if IS_WAYLAND and info["backend"] == "pyautogui":
            control = "limited"
            detail = "Running on Wayland with XWayland fallback. Reliability depends on compositor."
    else:
        control = "unavailable"
        detail = f"Mouse control unavailable: {info['error']}"

    return {
        "screen": info["screen"],
        "sessionType": SESSION_TYPE,
        "display": bool(display),
        "waylandDisplay": bool(wayland),
        "mouseControl": control,
        "mouseError": info["error"],
        "detail": detail,
        "inputMethod": info["backend"],
        "eventPacketsSent": _ydotool_events_sent if info["backend"] == "ydotool" else None,
        "lastInputAt": _ydotool_last_action_at,
    }


def _origin_allowed() -> bool:
    origin = request.headers.get("Origin")
    if origin:
        if origin not in LOCAL_ORIGINS:
            return False
    elif request.headers.get("Sec-Fetch-Site") == "cross-site":
        return False
    referer = request.headers.get("Referer")
    if referer:
        from urllib.parse import urlsplit
        parts = urlsplit(referer)
        if f"{parts.scheme}://{parts.netloc}" not in LOCAL_ORIGINS:
            return False
    return True


@app.before_request
def protect_local_api():
    if request.path.startswith("/api/"):
        remote = request.remote_addr
        if remote not in {"127.0.0.1", "::1"}:
            return jsonify(error="Local requests only"), 403
        if not _origin_allowed():
            return jsonify(error="Request origin is not allowed"), 403
        if request.method not in {"GET", "POST"}:
            return jsonify(error="Method not allowed"), 405
        if request.method == "POST":
            if not request.is_json:
                return jsonify(error="Content-Type must be application/json"), 415
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(error="Request body must be a JSON object"), 400


def _rate_limited() -> bool:
    now = time.monotonic()
    with _rate_lock:
        while _request_times and now - _request_times[0] >= 1:
            _request_times.popleft()
        if len(_request_times) >= RATE_LIMIT:
            return True
        _request_times.append(now)
        return False


def _action_error(exc: Exception):
    return jsonify(error="Desktop mouse action failed", detail=f"{type(exc).__name__}: {exc}"[:300]), 503


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok", backend="connected", desktop=_desktop_status())


@app.get("/api/screen")
def screen():
    result = _desktop_status()
    return jsonify(result), (200 if result["screen"] else 503)


@app.post("/api/move")
def move():
    data = request.get_json()
    x, y = data.get("x"), data.get("y")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return jsonify(error="x and y must be numbers"), 400
    if not (float("-inf") < float(x) < float("inf") and float("-inf") < float(y) < float("inf")):
        return jsonify(error="Coordinates must be finite"), 400
    if _rate_limited():
        return jsonify(error="Mouse action rate limit exceeded"), 429

    available, error = mouse.is_available()
    if not available:
        return jsonify(error="Desktop mouse control unavailable", detail=error), 503

    try:
        clamped_x, clamped_y = mouse.move(x, y)
        return jsonify(ok=True, x=clamped_x, y=clamped_y)
    except Exception as exc:
        return _action_error(exc)


@app.post("/api/click")
def click():
    data = request.get_json()
    button = data.get("button")
    if button not in {"left", "right"}:
        return jsonify(error="button must be 'left' or 'right'"), 400
    if _rate_limited():
        return jsonify(error="Mouse action rate limit exceeded"), 429

    available, error = mouse.is_available()
    if not available:
        return jsonify(error="Desktop mouse control unavailable", detail=error), 503

    try:
        btn = mouse.click(button)
        return jsonify(ok=True, button=btn)
    except Exception as exc:
        return _action_error(exc)


@app.post("/api/scroll")
def scroll():
    amount = request.get_json().get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return jsonify(error="amount must be a number"), 400
    if int(amount) != amount or amount == 0 or abs(amount) > 10:
        return jsonify(error="amount must be a non-zero whole number from -10 to 10"), 400
    if _rate_limited():
        return jsonify(error="Mouse action rate limit exceeded"), 429

    available, error = mouse.is_available()
    if not available:
        return jsonify(error="Desktop mouse control unavailable", detail=error), 503

    try:
        amt = mouse.scroll(int(amount))
        return jsonify(ok=True, amount=amt)
    except Exception as exc:
        return _action_error(exc)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
