"""Ratchet for ``mypy app``: errors may only go down, per file and per error code.

    uv run mypy app --no-error-summary | uv run python scripts/mypy_baseline.py          # check
    uv run mypy app --no-error-summary | uv run python scripts/mypy_baseline.py --update # rewrite

``mypy-baseline.txt`` holds one ``<count> <file> <code>`` line per group. A file or code that is not in
the baseline must be clean, so new code starts at zero. Fewer errors than the baseline never fail the
check, but the script asks for ``--update`` so that the gain is locked in.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "mypy-baseline.txt"
ERROR = re.compile(r"^(?P<file>[^:\s]+):\d+(?::\d+)?: error: .*\[(?P<code>[a-z-]+)\]\s*$")

Key = tuple[str, str]


def parse_errors(output: str) -> Counter[Key]:
    """Count mypy errors by (file, code); notes and the summary line are ignored."""
    counts: Counter[Key] = Counter()
    for line in output.splitlines():
        match = ERROR.match(line)
        if match:
            counts[(match["file"], match["code"])] += 1
    return counts


def parse_baseline(text: str) -> Counter[Key]:
    counts: Counter[Key] = Counter()
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            count, file, code = line.split()
            counts[(file, code)] = int(count)
    return counts


def render_baseline(counts: Counter[Key]) -> str:
    rows = [f"{count} {file} {code}" for (file, code), count in sorted(counts.items())]
    header = "# mypy baseline: <count> <file> <code>. Regenerate with scripts/mypy_baseline.py --update.\n"
    return header + "\n".join(rows) + "\n"


def regressions(current: Counter[Key], baseline: Counter[Key]) -> list[str]:
    return [
        f"{file} [{code}]: {count} error(s), baseline allows {baseline.get((file, code), 0)}"
        for (file, code), count in sorted(current.items())
        if count > baseline.get((file, code), 0)
    ]


def main(argv: list[str]) -> int:
    current = parse_errors(sys.stdin.read())
    if "--update" in argv:
        BASELINE.write_text(render_baseline(current))
        print(f"Baseline written: {sum(current.values())} error(s) in {len(current)} group(s).")
        return 0
    baseline = parse_baseline(BASELINE.read_text()) if BASELINE.exists() else Counter()
    failures = regressions(current, baseline)
    if failures:
        print("mypy regressions against mypy-baseline.txt:")
        print("\n".join(f"  {line}" for line in failures))
        return 1
    total, allowed = sum(current.values()), sum(baseline.values())
    print(f"mypy: {total} error(s), baseline {allowed}.")
    if total < allowed:
        print("The count went down: run scripts/mypy_baseline.py --update and commit mypy-baseline.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
