"""WKF 应用入口。"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from wkf.gui.main_window import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
