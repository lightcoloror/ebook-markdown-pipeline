from __future__ import annotations

import shutil
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from book_converter_ui import BookConverterUI  # noqa: E402


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def main() -> int:
    root = PROJECT_DIR / ".tmp-online-ui-contract"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    try:
        first = root / "one.txt"
        second = root / "two.pdf"
        ignored = root / "ignored.bin"
        first.write_text("hello", encoding="utf-8")
        second.write_bytes(b"%PDF-1.4\n")
        ignored.write_bytes(b"x")

        ui = BookConverterUI.__new__(BookConverterUI)
        ui.selected_input_files = [first, second, ignored]
        ui.recursive_var = Value(True)
        ui.include_hidden_var = Value(False)
        ui.input_var = Value("")
        ui.online_cost_limit_var = Value("1.25")

        input_root, sources = ui.resolve_online_sources()
        assert input_root == root
        assert sources == [first, second]
        assert ui.prompt_online_cost_limit() == 1.25
        assert hasattr(ui, "start_online_convert")
        assert hasattr(ui, "check_shared_api_health")
        print("Online-only UI contract test passed.")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
