"""Smart Kosher desktop app — entry point.

Starts the local bridge server and opens the UI in a native window
(pywebview / Edge WebView2). Without pywebview installed it falls back
to the default browser.

Usage:  python client/app.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bridge import LinkError
from server import Manager, serve

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def main():
    manager = Manager()
    try:
        info = manager.connect_serial()
        print("connected over USB:", info["port"])
    except LinkError:
        print("no USB device found - connect via the app's connection tab")

    httpd, port = serve(manager, UI_DIR)
    url = "http://127.0.0.1:{}/".format(port)
    print("bridge running at", url)

    try:
        import webview
    except ImportError:
        webview = None

    if webview is not None:
        window = webview.create_window(
            "Smart Kosher", url, width=520, height=840, min_size=(400, 600))
        webview.start()
    else:
        import webbrowser
        webbrowser.open(url)
        print("pywebview not installed - opened in the browser instead.")
        print("(pip install pywebview for a native window)")
        print("Press Ctrl+C to quit.")
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass

    httpd.shutdown()


if __name__ == "__main__":
    main()
