"""Entry point for ``python -m innereye``."""

from __future__ import annotations

import sys

from innereye.cli import main

if __name__ == "__main__":
    sys.exit(main())
