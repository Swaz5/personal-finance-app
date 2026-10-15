"""System tray launcher. Starts the API+web server as a background
subprocess and sits in the tray — click "Open Dashboard" to launch the
browser, "Quit" to stop the server and exit.

Runs under pythonw.exe (no console window), which means stdout/stderr
go nowhere and a crash looks like "nothing happens" — so everything of
note gets logged to tray.log next to this file instead.

On this machine, Windows Defender's behavior monitoring transparently
re-executes every pythonw.exe launch as a parent+child pair (confirmed
with a bare `pythonw -c "time.sleep(10)"` — no pystray/PIL involved, so
it isn't this script's doing). That means main() can genuinely run
twice for one logical launch. start_server() checks for an
already-healthy server first so the second run doesn't spawn a
redundant, port-conflicting uvicorn.
"""

import logging
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
VENV_PYTHON = API_DIR / ".venv" / "Scripts" / "python.exe"
DASHBOARD_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{DASHBOARD_URL}/api/health"
LOG_PATH = Path(__file__).resolve().parent / "tray.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tray")

server_process: subprocess.Popen | None = None


def _server_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


def start_server() -> None:
    global server_process
    if _server_healthy():
        log.info("server already running (probably a duplicate launch) — not starting another")
        return
    log.info("starting server: %s -m uvicorn main:app --port 8000", VENV_PYTHON)
    try:
        server_process = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(API_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
        log.info("server subprocess pid=%s", server_process.pid)
    except Exception:
        log.exception("failed to start server subprocess")


def stop_server() -> None:
    if server_process and server_process.poll() is None:
        log.info("stopping server subprocess pid=%s", server_process.pid)
        server_process.terminate()


def make_icon_image() -> Image.Image:
    """A simple upward-trend mark in the app's own palette — no external
    asset file needed."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(15, 21, 30, 255))
    draw.line([(14, 42), (28, 28), (38, 36), (50, 16)], fill=(79, 178, 134, 255), width=5, joint="curve")
    draw.ellipse((46, 12, 54, 20), fill=(79, 178, 134, 255))
    return img


def open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    log.info("Open Dashboard clicked — waiting for server readiness")
    for _ in range(20):
        if _server_healthy():
            break
        time.sleep(0.25)
    webbrowser.open(DASHBOARD_URL)


def quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    log.info("Quit clicked")
    stop_server()
    icon.stop()


def main() -> None:
    log.info("=== tray launcher starting ===")
    try:
        start_server()
        icon = pystray.Icon(
            "personal_finance_os",
            make_icon_image(),
            "Personal Finance OS",
            menu=pystray.Menu(
                pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
                pystray.MenuItem("Quit", quit_app),
            ),
        )
        log.info("tray icon created, entering run loop")
        icon.run()
        log.info("tray icon run loop exited")
    except Exception:
        log.exception("tray launcher crashed")
        raise


if __name__ == "__main__":
    main()
