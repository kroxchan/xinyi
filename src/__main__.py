"""xinyi — launcher for `python -m src` or `briefcase`."""
from __future__ import annotations

import os

from src.app import build_ui, load_config


def _inbrowser_enabled() -> bool:
    """Allow CI/package smoke tests to disable auto-opening the browser."""
    value = os.getenv("XINYI_INBROWSER", "1").strip().lower()
    return value not in {"0", "false", "no"}

def main():
    load_config()
    app = build_ui()
    app.queue()
    # 双击 .app / .exe 自动打开浏览器访问 dashboard
    app.launch(
        show_api=False,
        server_port=7872,
        inbrowser=_inbrowser_enabled(),
    )

if __name__ == "__main__":
    main()
