"""xinyi — launcher for `python -m src` or `briefcase`."""
import os
import sys
import webbrowser

# Ensure HOME is set — without it the bundled Python crashes silently
if not os.environ.get("HOME"):
    os.environ["HOME"] = os.path.expanduser("~")

# Prevent workers from re-entering launch() (uvicorn workers spawn via spawn()
# and re-execute this module; we detect that via the _LAUNCHED env var)
_launched_key = "_XINYI_LAUNCHED"

from src.app import build_ui, load_config


def main():
    # If a worker is re-entering, skip launch entirely
    if os.environ.get(_launched_key):
        return

    os.environ[_launched_key] = "1"

    load_config()
    app = build_ui()

    port = 7872
    base_url = f"http://127.0.0.1:{port}"

    if getattr(sys, "frozen", False):
        import threading

        def _open_browser():
            import time
            time.sleep(1.5)
            if sys.platform == "darwin":
                os.system(f'open "{base_url}"')
            elif sys.platform == "win32":
                os.system(f'start "" "{base_url}"')
            else:
                webbrowser.open(base_url)

        threading.Thread(target=_open_browser, daemon=True).start()
        # Frozen bundle: no queue to avoid workers re-entering __main__
        app.launch(show_api=False, server_port=port, inbrowser=False)
    else:
        app.queue(api_open=False, max_threads=1)
        app.launch(show_api=False, server_port=port, inbrowser=True)


if __name__ == "__main__":
    main()
