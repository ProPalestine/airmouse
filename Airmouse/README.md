# AirMouse

AirMouse is a local-first, browser-based hand-gesture controller for a Linux desktop. The webcam stream and MediaPipe hand-landmark inference run in your browser; a small Flask API accepts tightly validated mouse actions on loopback and passes them to a **dual backend** (PyAutoGUI for X11, **python-uinput for Wayland**). No webcam frames or landmarks are uploaded by the app.

> **Desktop-session note:** Wayland intentionally restricts applications from injecting input into other desktop apps. AirMouse includes a **Wayland-native backend (python-uinput)** that works when `/dev/uinput` is accessible. See **Wayland Setup** below.

## Features

- Live webcam preview, mirrored landmark overlay, hand-detection state, and measured tracking FPS.
- Two-finger pointer movement; single-index right click; fist scroll; three-finger pause.
- Pause/resume, Stop Camera, and emergency stop (`Esc`). No click repeats during one held pinch.
- Adjustable pointer sensitivity, smoothing, dead zone, and scroll amount.
- Camera selection when the browser exposes more than one camera.
- Localhost-only Flask API, origin checks, request validation, action rate limiting.
- **Dual backend**: PyAutoGUI (X11/XWayland) + **python-uinput (Wayland native)**.
- Responsive dark dashboard with differentiated camera, tracking, and backend messages.

## Architecture

```text
Browser (HTML/CSS/JS)
  ├─ MediaDevices webcam stream
  ├─ MediaPipe Tasks Vision Hand Landmarker (local in-browser inference)
  └─ POST JSON actions → Flask at 127.0.0.1:5000 → [PyAutoGUI | python-uinput] → desktop
```

The UI obtains MediaPipe Tasks Vision **0.10.14** JavaScript/WASM bundle and the official hand-landmarker model from jsDelivr and Google Cloud Storage respectively. These are external *static asset* downloads, not a cloud inference backend. The CDN/model must be reachable on the first camera start; the browser may cache them locally. Camera frames and landmark coordinates are never sent to those hosts.

## Project layout

```text
.
├── app.py
├── install.sh
├── run.sh
├── requirements.txt
├── README.md
├── templates/index.html
├── static/app.js
├── static/style.css
└── tests/
    ├── test_api.py
    └── test_frontend.py
```

## Ubuntu installation

Requires Python 3.10+ (tested with Python 3.12.3). Installation creates a project-local `.venv`; it does not install Python packages system-wide.

```bash
git clone https://github.com/ProPalestine/airmouse.git
cd airmouse
./install.sh
```

If venv creation reports missing `ensurepip`/venv support, Ubuntu may need its packaged venv support (`python3-venv`). Install system packages only if you choose to; AirMouse does not modify system settings.

Then start AirMouse and open its local dashboard:

```bash
./run.sh
```

Visit **http://127.0.0.1:5000** in Firefox or Chromium, allow camera access, and click **Start camera**. The server stays on your own computer; do not expose or forward port 5000. For GNOME/Wayland, complete the additional setup below before expecting desktop pointer control.

## Wayland Setup (GNOME)

On GNOME/Wayland, AirMouse uses **ydotool + the user-session `ydotoold` daemon**. The daemon must be active in the same login session as AirMouse; an API `200` only means the local request was accepted, not that the compositor acted on it.

To build ydotool from source:

```bash
sudo apt-get install -y build-essential cmake pkg-config libevdev-dev libudev-dev scdoc
git clone https://github.com/ReimuNotMoe/ydotool.git
cd ydotool
mkdir -p build && cd build
cmake ..
make -j"$(nproc)"
sudo make install
```

The source install provides a **user** service named `ydotoold`, not a system service named `ydotool`. Enable it as your normal user (no sudo):

```bash
systemctl --user daemon-reload
systemctl --user enable --now ydotoold
systemctl --user status ydotoold --no-pager
ydotool mousemove 100 100
```

Check that `/run/user/$(id -u)/.ydotool_socket` exists. Then restart AirMouse from the same logged-in user session:

```bash
cd /path/to/airmouse
./run.sh
```

The health endpoint should report **`mouseControl: available`**, **`inputMethod: ydotool`**, and the screen size. The installed client supports absolute coordinates; AirMouse uses `mousemove --absolute --xpos X --ypos Y`. If absolute positioning is off on your compositor, calibrate against the reported screen size. A successful HTTP status alone does not prove visible cursor movement.

For lower pointer latency, AirMouse sends Linux input-event datagrams directly to the active ydotoold socket (instead of starting a new `ydotool` process on every sample), drops stale queued pointer samples, and defaults cursor smoothing to 40%. The webcam/MediaPipe loop still runs in the browser: keep the AirMouse dashboard tab visible while using other applications. Browsers throttle animation frames in background tabs, so minimizing the browser or switching away from its tab can make gesture control lag or pause. The injected cursor actions go through ydotoold and are not restricted to the AirMouse page.

The python-uinput backend remains a fallback, but GNOME/Mutter may ignore synthetic uinput events; successful uinput API responses are not proof of visible cursor movement.

## Run and stop

```bash
./run.sh
```

Open **http://127.0.0.1:5000** in a modern browser. Camera access is requested only when you click **Start camera**. Click **Stop** or press `Ctrl+C` in the terminal to stop. The app binds to loopback only, disables Flask debug/reload mode, and is not exposed to your LAN. Do not forward port 5000.

## Gestures

| Action | Gesture | Details |
|---|---|---|
| Move | Raise index + middle; curl ring and pinky | Midpoint between index and middle tips controls the system pointer. |
| Right click | Raise index only | One right click; lower a finger/relax hand to re-arm. |
| Pause | Raise thumb + index + middle for 0.7 seconds | Latches pause; press Resume to continue. Release the pose before resuming. |
| Scroll | Close all four fingers into a fist | Move fist vertically; open a finger to stop scroll. |
| Pause/resume | Dashboard button | Paused actions stop. Resume is explicit; tracking error doesn't auto-resume. |
| Emergency stop | Button or `Esc` | Disables gestures until explicit resume. Stop Camera releases webcam. |

For a simple start, face palm toward the camera and use one pose at a time. On GNOME/Wayland, ydotool injects pointer events system-wide; the browser page must remain active to keep processing camera frames. Use **Float preview** to keep the camera view in a movable picture-in-picture window while using other apps. Browsers can still throttle a hidden tab.

## Camera and tracking troubleshooting

- **Permission denied:** allow camera use for `127.0.0.1` in browser site permissions, then click Start camera again.
- **No camera:** reconnect/enable webcam, close apps holding it, reload. Camera selection appears when multiple devices available.
- **No hand detected:** improve lighting, keep whole hand in frame, face palm toward camera, use one hand.
- **MediaPipe/model load failed:** first start downloads JS/WASM runtime and model from URLs in `static/app.js`. Check network/CDN access and reload/retry. GPU falls back to CPU; CPU tracking may have lower FPS.
- **Backend disconnected:** ensure `./run.sh` is running at port 5000 and reload page.
- **Desktop control unavailable:** check tracking and desktop status separately. A functioning preview is independent of desktop input injection.
- **Wayland: "Permission denied: /dev/uinput"**: run the **Wayland Setup** commands above, log out/in, then restart.

## Backend Compatibility

| Session | Backend | Status |
|---|---|---|
| **GNOME/Wayland** | **ydotoold** (primary) | ✅ Requires active user daemon/socket |
| Wayland compositors | python-uinput (fallback) | ⚠️ Compositor may ignore synthetic input |
| Wayland + XWayland | PyAutoGUI (fallback) | ⚠️ Limited, compositor-dependent |
| **X11 / Xorg** | PyAutoGUI | ✅ Works |
| X11 + uinput | python-uinput | ✅ Works |

The app auto-detects the session type and prefers the appropriate backend.

## Privacy and security

- Webcam access begins only after user action; Stop and page close stop all camera tracks.
- Frames and hand coordinates processed in browser; not stored or uploaded.
- Static MediaPipe/model assets downloaded from external URLs listed above. Offline first-use tracking not guaranteed.
- Flask binds to `127.0.0.1`, no debug mode, rejects non-loopback API requests, checks Origin/Referer, requires JSON objects, validates action ranges, caps request bodies, rate-limits action calls.
- API contains only fixed move/click/scroll operations; no shell commands or Python code.
- Loopback is not authentication. Keep server private to the machine.

## Automated tests

```bash
.venv/bin/python -m pytest -q
```

Tests use a fake mouse driver and do not move the real mouse or click. They cover health/screen status, coordinate clamps, malformed requests, accepted/rejected click/scroll values, origin checks, action rate limiting, mouse backend errors, page/static asset responses, and frontend safety/mapping guardrails.

## Manual end-to-end checks

1. Start AirMouse and open http://127.0.0.1:5000 in Firefox/Chromium; allow webcam access.
2. Confirm live preview, landmarks, hand indicator, FPS. Move finger and watch gesture status.
3. With a safe desktop area selected, raise index only briefly for one right-click; lower it before retrying.
4. Try index-only right click, a closed-fist vertical scroll, and the thumb+index+middle pause pose. Confirm the live gesture label matches each pose.
5. Pause, move/pinch, confirm no desktop actions; resume explicitly. Stop camera, confirm indicator off.
6. Press `Esc`; verify emergency stop. Resume explicitly if desired.
7. On GNOME/Wayland, verify `inputMethod: ydotool` and actual cursor movement; a successful HTTP response alone is insufficient.

## GitHub publishing

For Git installation, account identity, authentication choices, and a careful publishing checklist, see [the Linux GitHub setup guide](docs/github-setup-linux.md).

```bash
git init
git add app.py install.sh run.sh requirements.txt README.md templates static tests .gitignore
git status --short
git commit -m "Build local AirMouse gesture controller with Wayland support"
```

Create an empty GitHub repository, add its URL as `origin`, and push. Do not commit `.venv`, webcam captures, tokens, or private environment files.
