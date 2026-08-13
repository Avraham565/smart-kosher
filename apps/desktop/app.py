"""Smart Kosher desktop app — entry point.

Starts the local bridge server and opens the UI in a native window
(pywebview / Edge WebView2). Without pywebview installed it falls back
to the default browser.

Usage:
    python apps/desktop/app.py [--port N] [--no-window]

--port N      bind the bridge to a fixed port (default: any free port)
--no-window   run the bridge headless (no window/browser) — for testing

Also runs frozen (PyInstaller): the ui/ directory is bundled and
resolved via sys._MEIPASS.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# desktop/ -> apps/ -> repo root, then src.
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
# The bridge resolves REST paths against the hub's own route table
# (smart_kosher.web.route_table), so the core package has to be importable.
# Frozen, PyInstaller has already bundled it as modules; from a checkout it
# lives in ../../src, which nothing else here puts on the path.
sys.path[:0] = [_HERE] if getattr(sys, "frozen", False) else [_HERE, _SRC]

from bridge import LinkError  # noqa: E402  (needs the path setup above)
from server import Manager, serve  # noqa: E402


def _ui_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "ui")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def _parse_args(argv):
    port = 0
    headless = False
    i = 0
    while i < len(argv):
        if argv[i] == "--no-window":
            headless = True
        elif argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
            i += 1
        i += 1
    return port, headless


def _wait_forever():
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main():
    port_arg, headless = _parse_args(sys.argv[1:])

    manager = Manager()
    try:
        info = manager.connect_serial()
        print("connected over USB:", info["port"])
    except LinkError:
        print("no USB device found - connect via the app's connection tab")

    httpd, port = serve(manager, _ui_dir(), port=port_arg)
    url = "http://127.0.0.1:{}/".format(port)
    print("bridge running at", url)

    if headless:
        _wait_forever()
        httpd.shutdown()
        return

    try:
        import webview
    except ImportError:
        webview = None

    if webview is not None:
        webview.create_window(
            "Smart Kosher", url, width=520, height=840, min_size=(400, 600))
        webview.start()
    else:
        import webbrowser
        webbrowser.open(url)
        print("pywebview not installed - opened in the browser instead.")
        print("(pip install pywebview for a native window)")
        print("Press Ctrl+C to quit.")
        _wait_forever()

    httpd.shutdown()


if __name__ == "__main__":
    main()
