from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
LEGACY_SCRIPTS = tuple(sorted((PROJECT_DIR / "scripts").glob("test_*.py")))


def test_legacy_script_inventory_is_discoverable() -> None:
    assert len(LEGACY_SCRIPTS) >= 73


class LegacyScriptDiscoveryCompatibilityTest(unittest.TestCase):
    def test_legacy_script_inventory_is_discoverable(self) -> None:
        self.assertGreaterEqual(len(LEGACY_SCRIPTS), 73)


@pytest.mark.parametrize("script", LEGACY_SCRIPTS, ids=lambda script: script.stem)
def test_legacy_script_contract(script: Path, tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["TEMP"] = str(tmp_path)
    environment["TMP"] = str(tmp_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(script)],
        cwd=PROJECT_DIR,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"Legacy script failed: {script.name}\n"
        f"STDOUT:\n{completed.stdout}\n"
        f"STDERR:\n{completed.stderr}"
    )
