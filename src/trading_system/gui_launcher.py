from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:
        raise RuntimeError(
            "GUI requires Streamlit. Install project dependencies with: pip install -e ."
        ) from exc

    app_path = Path(__file__).with_name("gui.py")
    sys.argv = ["streamlit", "run", str(app_path)]
    return int(stcli.main())


if __name__ == "__main__":
    raise SystemExit(main())
