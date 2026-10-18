# AirMouse

Control your Linux desktop with simple hand gestures. AirMouse uses your webcam for hand tracking and moves the system pointer from a small web dashboard running on your computer.

> **Linux desktop app · Python + Flask · MediaPipe hand tracking**

## What AirMouse does

AirMouse has two parts:

1. **The browser dashboard** asks for webcam access when you press **Start camera**. It runs MediaPipe hand tracking locally and translates gestures into mouse actions.
2. **The local Flask server** receives those actions and passes them to your Linux desktop’s input backend. The server listens on `127.0.0.1:5000`, so it is intended for use on your own computer.

AirMouse does not upload webcam frames or hand landmarks. The browser downloads the MediaPipe JavaScript/WASM runtime and hand model from their configured hosts on first use.

## Gesture controls

| Action | Gesture |
| --- | --- |
| Move pointer | Raise your index and middle fingers; curl your ring and pinky fingers. |
| Right-click | Raise only your index finger. Lower a finger or relax your hand to re-arm the gesture. |
| Scroll | Make a fist and move your hand vertically. Open a finger to stop scrolling. |
| Pause gestures | Raise your thumb, index, and middle fingers for about 0.7 seconds. |
| Emergency stop | Press `Esc` or use the dashboard button. Resume explicitly when ready. |

The dashboard also has pause/resume and stop-camera controls, camera selection when multiple cameras are available, and adjustable pointer sensitivity, smoothing, dead zone, and scroll amount.

## Requirements

- A Linux desktop with Python 3.10 or newer.
- A webcam and a recent version of Firefox or Chromium.
- An internet connection the first time you start the camera so the browser can download MediaPipe’s runtime and model.

## Install and run on Ubuntu or Debian

Clone the repository, enter the project folder, install the Python packages, and start AirMouse:

```bash
git clone https://github.com/ProPalestine/airmouse.git
cd airmouse/Airmouse
./install.sh
./run.sh
install.sh creates a .venv inside the project and installs the packages listed in requirements.txt. It does not install Python packages system-wide.

If the installer reports that Python’s virtual-environment support is missing, install the Ubuntu/Debian packages and run the installer again:

Copy code block
sudo apt update
sudo apt install python3-venv python3-dev
./install.sh
When the server starts, open http://127.0.0.1:5000 in your browser. Allow camera access for the site, then click Start camera.

Keep the AirMouse dashboard tab visible while using gestures. Browsers may slow down camera processing in background tabs. To stop the server, return to the terminal and press Ctrl+C.

Keep the server private to your machine. AirMouse binds to localhost. Do not forward port 5000 or expose it to your network.

Desktop input backends
AirMouse selects a backend based on the Linux desktop session:

X11/Xorg: PyAutoGUI.
GNOME/Wayland: ydotool and the user-session ydotoold daemon are used for pointer input.
Other Wayland sessions: input support depends on the compositor and available backend.
Wayland desktops restrict how applications send input to other apps, so extra setup may be needed. Follow the Wayland Setup (GNOME) section in 
Airmouse/README.md

 for the ydotool installation and user-service instructions. After setup, verify actual cursor movement; a successful API response alone does not guarantee that the compositor accepted the input.

Run the tests
From the Airmouse project directory:

Copy code block
.venv/bin/python -m pytest -q
The tests use a fake mouse driver. They check the API and frontend without moving or clicking your real mouse.

Privacy and safety
The webcam starts only after you click Start camera.
Camera frames and hand landmarks are processed in the browser and are not uploaded by AirMouse.
The Flask server listens on loopback at 127.0.0.1:5000; it is not intended to be exposed to other devices.
MediaPipe’s browser runtime and hand model are downloaded from the static asset hosts configured by the project.
Project files
Copy code block
Airmouse/
├── app.py
├── install.sh
├── run.sh
├── requirements.txt
├── static/
│   ├── app.js
│   └── style.css
├── templates/
│   └── index.html
├── tests/
│   ├── test_api.py
│   └── test_frontend.py
└── docs/
    └── github-setup-linux.md
For detailed installation, troubleshooting, testing, and manual checks, see 
Airmouse/README.md

. The GitHub publishing guide is in 
Airmouse/docs/github-setup-linux.md

. ```
