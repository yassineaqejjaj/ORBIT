"""The mypy ratchet (``scripts/mypy_baseline.py``): errors may go down per file and code, never up."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

BACKEND = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mypy_baseline", BACKEND / "scripts" / "mypy_baseline.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OUTPUT = """\
app/a.py:10: error: Incompatible types in assignment  [assignment]
app/a.py:12: error: Incompatible types in assignment  [assignment]
app/a.py:12: note: Revealed type is "builtins.int"
app/b.py:3:7: error: Item "None" of "X | None" has no attribute "y"  [union-attr]
"""


def test_parse_counts_errors_by_file_and_code_and_ignores_notes() -> None:
    counts = _load().parse_errors(OUTPUT + "Found 3 errors in 2 files (checked 5 source files)\n")
    assert counts == {("app/a.py", "assignment"): 2, ("app/b.py", "union-attr"): 1}


def test_regressions_flag_new_files_new_codes_and_higher_counts_only() -> None:
    module = _load()
    baseline = module.parse_baseline(module.render_baseline(module.parse_errors(OUTPUT)))
    assert module.regressions(module.parse_errors(OUTPUT), baseline) == []
    fewer = module.parse_errors(OUTPUT.replace("app/a.py:12: error", "app/a.py:12: note"))
    assert module.regressions(fewer, baseline) == []  # a cleanup never fails
    more = OUTPUT + "app/a.py:20: error: x  [assignment]\n"
    assert len(module.regressions(module.parse_errors(more), baseline)) == 1
    new_file = OUTPUT + "app/c.py:1: error: x  [arg-type]\n"
    assert "app/c.py [arg-type]" in module.regressions(module.parse_errors(new_file), baseline)[0]
    new_code = OUTPUT + "app/b.py:9: error: x  [attr-defined]\n"
    assert "app/b.py [attr-defined]" in module.regressions(module.parse_errors(new_code), baseline)[0]


def test_committed_baseline_is_well_formed() -> None:
    module = _load()
    baseline = module.parse_baseline((BACKEND / "mypy-baseline.txt").read_text())
    assert baseline and all(
        file.startswith("app/") and not file.startswith("app/../") for file, _ in baseline
    )
