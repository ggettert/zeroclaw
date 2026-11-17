#!/usr/bin/env python3
"""Structural fixture checks only: never executes/reimplements timestamp logic."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for name, required, count in [
    ("timestamps", {"id", "input", "persisted", "serde", "log"}, 8),
    ("schedules", {"id", "expr", "zone", "from", "baseline", "candidate", "raw_candidate"}, 23),
]:
    rows = json.loads((root / "fixtures" / (name + ".json")).read_text())
    assert len(rows) == count
    assert len({r["id"] for r in rows}) == count
    assert all(set(r) == required and all(isinstance(v, str) for v in r.values()) for r in rows)
    if name == "timestamps":
        for row in rows:
            assert re.fullmatch(r"[0-9]{4}-.+T.+:[0-9]{2}(?:\.(?:[0-9]{3}|[0-9]{6}|[0-9]{9}))?\+00:00", row["persisted"])
            assert row["serde"].endswith("Z")
            assert re.search(r"\.[0-9]{3}Z$", row["log"])
    print(name + ": " + str(count) + " structurally valid source-derived fixtures")

for path in sorted(root.rglob("*")):
    if path.is_file():
        data = path.read_bytes()
        assert b"\0" not in data, str(path)
        assert data.endswith(b"\n"), str(path)
        assert all(line.rstrip() == line for line in data.splitlines()), str(path)
print("Text structure: no NUL, trailing whitespace or missing final newline")
for name, count in [("timestamps", 5), ("schedules", 9)]:
    actual = (root / "tests" / (name + ".rs")).read_text().count("#[test]")
    assert actual == count, (name, actual)
    print(name + ": " + str(count) + " authored tests (NOT executed)")
