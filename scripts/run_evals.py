"""Run the canonical continuous-eval selectors in one pytest process."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "evals" / "test-selectors.txt"


def main() -> int:
    selectors = [
        line
        for raw_line in CATALOG.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]
    if not selectors:
        print("Continuous-eval selector catalog is empty.")
        return 1
    return subprocess.run(
        [sys.executable, "-m", "pytest", *selectors], cwd=ROOT, check=False
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
