#!/usr/bin/env python3
"""Trusted tooling: attest exact committed candidate before executing its tests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def main():
    require(len(sys.argv) == 3, "usage: verifier SOURCE MANIFEST")
    source = Path(sys.argv[1]).resolve()
    manifest = json.loads(Path(sys.argv[2]).read_text())
    sha = manifest.get("target_sha", "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "UNBOUND candidate: parent must freeze manifest")
    require(manifest.get("schema") == 1, "Unsupported manifest schema")
    require(manifest.get("base_sha") == "03b29bcc68eadf8bd03905b93d6867d3af9d7b87", "Unexpected base")
    require(os.environ.get("TARGET_SHA", "").lower() == sha, "Input differs from attested candidate")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args])

    require(git("rev-parse", "HEAD").decode().strip() == sha, "Source HEAD differs")
    origin = git("remote", "get-url", "origin").decode().strip()
    require(origin in ("https://github.com/ggettert/zeroclaw", "https://github.com/ggettert/zeroclaw.git"), "Unexpected origin")
    git("diff", "--exit-code", "--no-ext-diff", "--quiet")
    git("diff", "--cached", "--exit-code", "--no-ext-diff", "--quiet")
    require(not git("ls-files", "--others", "--exclude-standard"), "Untracked source checkout")
    files = manifest.get("changed_files", [])
    require(files and isinstance(files, list), "Empty candidate attestation")
    expected = {}
    for item in files:
        path = item.get("path", "")
        require(path and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and chr(92) not in path and ":" not in path and path not in expected, "Unsafe/duplicate manifest path")
        require(not path.startswith(".github/") and not path.startswith("scripts/ci/fork_12109"), "Fork CI tooling cannot enter feature candidate")
        require(item.get("mode") in ("100644", "100755"), "Unsupported candidate mode")
        require(re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")), "Invalid content hash")
        expected[path] = item
    actual = git("diff", "--name-only", "--no-renames", "-z", manifest["base_sha"], sha).decode().split(chr(0))[:-1]
    require(set(actual) == set(expected) and len(actual) == len(expected), "Candidate path set differs")
    attested = []
    for path, item in expected.items():
        tree = git("ls-tree", "-z", sha, "--", path).decode().split(chr(0))[0]
        require(tree and tree.split()[0] == item["mode"], "Candidate mode differs: " + path)
        committed = git("show", sha + ":" + path)
        require(hashlib.sha256(committed).hexdigest() == item["sha256"], "Committed content differs: " + path)
        destination = source / path
        require(destination.is_file() and not destination.is_symlink(), "Non-regular path: " + path)
        require(source in destination.resolve().parents, "Outside candidate: " + path)
        require(not any(parent.is_symlink() for parent in destination.parents if parent != source and source in parent.parents), "Symlink parent: " + path)
        attested.append((destination, committed, item["sha256"]))
    # All hashes/modes/destinations verified before ANY writes. Git attributes
    # can checkout PS1 as CRLF; execution must use exact frozen Git blob bytes.
    for destination, committed, digest in attested:
        if destination.read_bytes() != committed:
            destination.write_bytes(committed)
        require(hashlib.sha256(destination.read_bytes()).hexdigest() == digest, "Materialized bytes differ")
    # Git may report the normalized PS1 as a stat/line-ending change despite
    # no content diff. Verify semantic cleanliness without changing index/config.
    git("diff", "--exit-code", "--no-ext-diff", "--quiet")
    git("diff", "--cached", "--exit-code", "--no-ext-diff", "--quiet")
    require(not git("ls-files", "--others", "--exclude-standard"), "Unexpected untracked candidate files")
    print("Candidate attested:", sha, "paths:", len(expected))


if __name__ == "__main__":
    main()
