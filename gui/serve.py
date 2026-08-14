"""
Serve the built GUI without Node.

    python gui/serve.py

Two jobs, both small:

    1. serve gui/dist as static files on port 5173
    2. forward every /api request to the REST API on 127.0.0.1:8000

The forwarding is the point. The page and the API then answer on the same origin, so the
browser has no cross origin call to block and the backend needs no CORS headers. It is
the same arrangement Vite provides in development, rebuilt in the standard library so a
machine with no Node installed still gets a working front end.

main.py picks between this and the Vite dev server automatically: node_modules present
means development, absent means this file. Nothing else changes.

dist is a build artifact that is committed on purpose. Anyone who clones the repository
gets a runnable GUI. Rebuild it with 'npm run build' inside gui/ after changing the
source, otherwise this serves the previous build.
"""

from __future__ import annotations

import http.server
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE / "dist"

API_ORIGIN = "http://127.0.0.1:8000"
HOST = "localhost"
PORT = 5173          # must match GUI_PORT in main.py and server.port in vite.config.js
API_TIMEOUT = 60     # a forecast on a cold machine is slow, so do not cut it short


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files out of dist, with /api forwarded to the REST API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.forward_to_api()
            return
        super().do_GET()

    def end_headers(self):
        """
        Never let a static file be cached.

        The bundle and the icons are replaced by a rebuild while their names stay the
        same, so a cached copy means the previous version keeps being served with no way
        for a person to tell. Nothing here is large enough for caching to be worth that.
        """
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def forward_to_api(self):
        """
        Pass the request through and return the response as it came back.

        Status codes are preserved deliberately. The GUI reads 503 as a sync in progress
        and 500 as a model that is not ready yet, and both drive what the user sees, so
        flattening them into a generic failure would break the waiting screens.
        """
        try:
            with urllib.request.urlopen(API_ORIGIN + self.path, timeout=API_TIMEOUT) as response:
                body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as error:
            body = error.read()
            status = error.code
            content_type = error.headers.get("Content-Type", "application/json")
        except Exception:
            # The API is not up yet. 503 is what the GUI already knows how to wait on.
            body = b'{"status":"error","message":"backend unavailable"}'
            status = 503
            content_type = "application/json"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Silence per request logging. main.py owns the terminal."""
        return


def main() -> None:
    if not (DIST / "index.html").is_file():
        print("gui/dist is missing or empty. Run 'npm install' then 'npm run build' "
              "inside gui/ once, and commit the result.", file=sys.stderr)
        sys.exit(1)

    # Threading matters: the GUI opens several requests at once on load, and a single
    # threaded server would answer them one at a time behind the slowest one.
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
