"""
Single entry point.

One command, one terminal, one window:

    python main.py

It starts three things and ties their lifetimes together:

    1. bootstrap.py            the sync service and the REST API, unchanged
    2. npm run dev             the Vite dev server that serves the front end
    3. a browser window        opened on the app once Vite is actually listening

Closing the browser window shuts the other two down. So does Ctrl+C in the terminal.
Either way nothing is left holding a port.

    python main.py --no-browser   start the servers, open the browser yourself
    python main.py --keep-alive   ignore the browser closing, exit on Ctrl+C only

Nothing here waits on the backend. bootstrap.py is launched and left to run: its sync,
its first training pass and the 24/7 scheduler all proceed while the front end is
already up. The only thing waited on is Vite's port, which takes seconds. Until the
models finish, the API answers {"status": "training"} and the GUI shows that - which is
the whole reason the API comes up before the models are ready.

A note on what closing the window can and cannot mean. The browser is launched in
application mode with a private profile, which gives one window with no tabs and, more
importantly, its own process - so "the window was closed" is a real signal rather than
a guess. Reading it from inside the page instead (a beforeunload handler, a heartbeat
that stops arriving) cannot distinguish a close from a refresh, and would take the
system down every time someone pressed F5.

If no Chrome-family browser is found, the default browser is opened instead. That path
cannot report when its window closes, so the run falls back to ending on Ctrl+C.

The full development pipeline stays separate: python ai/runners/run_pipeline.py
"""

from __future__ import annotations

import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent

from backend.utils.ConfigLoader import ConfigLoader
from backend.utils.ConsoleLogger import ConsoleLogger

logger = ConsoleLogger(caller="main")

GUI_HOST = "localhost"   # by NAME, not 127.0.0.1 - see wait_for_port
GUI_PORT = 5173          # Vite's default; change here and in gui/vite.config.js together
GUI_READY_TIMEOUT = 90   # seconds to wait for Vite, generous for a first cold start

# Chrome-family executables, in the order they are tried. Application mode is a Chrome
# feature, so a non-Chrome default browser falls through to the plain-open path below.
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser",
    "microsoft-edge", "msedge", "brave-browser",
]
CHROME_WINDOWS_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


# ----------------------------------------------------------------------------------
# Process handling
# ----------------------------------------------------------------------------------
def spawn(command: list[str], cwd: pathlib.Path) -> subprocess.Popen:
    """
    Start a process in its own process group.

    The group is what makes shutdown reliable. bootstrap.py starts children of its own,
    and terminating only the process we hold a handle to leaves those children running
    and still holding their ports - measurably so. Owning the group lets one signal
    reach the whole tree.
    """
    if os.name == "nt":
        return subprocess.Popen(command, cwd=str(cwd),
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(command, cwd=str(cwd), start_new_session=True)


def kill_tree(process: subprocess.Popen | None) -> None:
    """Stop a process and everything it started. Never raises - shutdown must finish."""
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def wait_for_port(host: str, port: int, timeout: int) -> bool:
    """
    Block until something accepts connections on the port, or the timeout expires.

    Waiting on the port rather than sleeping a fixed number of seconds is what keeps the
    browser from opening on a page that is not being served yet - a cold Vite start with
    an empty cache is much slower than a warm one, and any fixed guess is wrong on one
    of them.

    The host is resolved by NAME through create_connection, which tries every address
    getaddrinfo returns. Node binds "localhost" to whatever the OS resolves first, and
    on Windows that is often the IPv6 loopback - so a hardcoded IPv4 probe to 127.0.0.1
    waits out the full timeout against a server that has been up the whole time.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


# ----------------------------------------------------------------------------------
# Browser
# ----------------------------------------------------------------------------------
def find_chrome() -> str | None:
    """Locate a Chrome-family browser, or None."""
    for name in CHROME_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_WINDOWS_PATHS:
        if pathlib.Path(path).exists():
            return path
    return None


def open_browser(url: str) -> subprocess.Popen | None:
    """
    Open the app in a dedicated window and return its process, or None if the window
    cannot be owned.

    The private profile directory is not optional. Without it Chrome hands the URL to an
    already-running instance and the process we launched exits immediately, which would
    read as "the user closed the window" a second after startup.
    """
    chrome = find_chrome()
    if chrome is None:
        logger.warning("No Chrome-family browser found - opening the default browser. "
                       "Closing its window will not stop the system; use Ctrl+C.")
        webbrowser.open(url)
        return None

    profile_dir = pathlib.Path(tempfile.gettempdir()) / "algotrade-browser-profile"
    logger.info(f"Opening {url}")
    return subprocess.Popen(
        [chrome, f"--app={url}", f"--user-data-dir={profile_dir}",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def start_gui() -> subprocess.Popen | None:
    """Start the Vite dev server. A missing toolchain warns rather than stops: the API
    is the system and the front end is a client of it."""
    gui_dir = ROOT / "gui"

    npm = shutil.which("npm")   # on Windows this resolves npm.cmd, which a bare
    if npm is None:             # "npm" in Popen would not find
        logger.error("npm not found on PATH. Install Node 18+, then run again.")
        return None
    if not (gui_dir / "node_modules").is_dir():
        logger.error("gui/node_modules is missing. Run 'npm install' inside gui/ once.")
        return None

    logger.info("Starting the GUI dev server")
    return spawn([npm, "run", "dev"], cwd=gui_dir)


# ----------------------------------------------------------------------------------
def main() -> None:
    # No banner here: bootstrap.py prints it, and printing it in both places puts two
    # of them in one terminal and reads like the backend started twice.
    want_browser = "--no-browser" not in sys.argv
    keep_alive = "--keep-alive" in sys.argv
    host, port = ConfigLoader.load_rest_settings()
    url = f"http://localhost:{GUI_PORT}"

    backend_process = gui_process = browser_process = None
    try:
        logger.section("Starting Backend")
        backend_process = spawn(
            [sys.executable, "-u", str(ROOT / "bootstrap.py")], cwd=ROOT)
        logger.info(f"Sync service and REST API starting on {host}:{port}")

        logger.section("Starting GUI")
        gui_process = start_gui()
        if gui_process is None:
            logger.warning("Continuing without the GUI - the REST API is still coming up")

        if gui_process is not None and want_browser:
            logger.info(f"Waiting for the dev server on port {GUI_PORT}")
            if wait_for_port(GUI_HOST, GUI_PORT, GUI_READY_TIMEOUT):
                browser_process = open_browser(url)
            else:
                logger.warning(f"Vite did not come up within {GUI_READY_TIMEOUT}s. "
                               f"Try {url} manually once it does.")

        logger.section("Running")
        logger.success(f"Open at {url}")
        logger.info("On a fresh machine the first forecast waits for the initial sync "
                    "and training. The GUI shows a waiting state until then.")

        if browser_process is not None and not keep_alive:
            logger.info("Close the browser window (or press Ctrl+C) to stop everything")
            browser_process.wait()
            logger.info("Browser window closed")
        else:
            logger.info("Press Ctrl+C to stop everything")
            while True:
                # Stop early if the backend dies on its own, rather than sitting in a
                # loop next to a system that is no longer running.
                if backend_process.poll() is not None:
                    logger.error("The backend exited - shutting down")
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        print()
        logger.info("Interrupted")
    finally:
        logger.section("Shutting Down")
        for name, process in (("browser", browser_process),
                              ("GUI", gui_process),
                              ("backend", backend_process)):
            if process is not None and process.poll() is None:
                logger.info(f"Stopping {name}")
                kill_tree(process)
        logger.success("Stopped")


if __name__ == "__main__":
    main()