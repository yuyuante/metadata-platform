"""Test-environment compatibility hooks."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

if os.name == "nt" and sys.version_info >= (3, 13):
    _original_mkdir: Callable[..., None] = Path.mkdir

    def _mkdir_without_restrictive_windows_acl(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Keep pytest temporary directories accessible to the test process.

        Python 3.13 applies a restrictive Windows ACL for mode ``0o700``.
        Pytest uses that mode for every ``tmp_path`` directory, which can make
        the directory inaccessible under a managed Windows execution token.
        Other modes retain the pre-3.13 Windows behavior.
        """

        compatible_mode = 0o755 if mode == 0o700 else mode
        _original_mkdir(
            self,
            mode=compatible_mode,
            parents=parents,
            exist_ok=exist_ok,
        )

    Path.mkdir = _mkdir_without_restrictive_windows_acl
