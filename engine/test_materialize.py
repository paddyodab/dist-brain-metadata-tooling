#!/usr/bin/env python3
"""Tests for materialize prior-state sourcing: python3 engine/test_materialize.py

The fix: the delta's prior state comes from brain.sqlite (load_graph), not graph.json.
This makes incremental deltas correct in --no-json mode and keeps json/no-json in lockstep.
Needs git; skips cleanly if git is unavailable.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from brain_store import DEFAULT_REVISION, BrainStore

ENGINE = Path(__file__).resolve().parent
MATERIALIZE = ENGINE / "materialize.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _have_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


FLAGS = "flags: {}\n"

MOD_V0 = '''\
def alpha(x):
    """A.

    @intent Alpha returns x unchanged.
    @param x in
    @returns int
    """
    return x


def beta(y):
    """B.

    @intent Beta returns y unchanged.
    @param y in
    @returns int
    """
    return y
'''

# v1: alpha's intent changed; beta unchanged; gamma added.
MOD_V1 = '''\
def alpha(x):
    """A.

    @intent Alpha now DOUBLES x.
    @param x in
    @returns int
    """
    return x * 2


def beta(y):
    """B.

    @intent Beta returns y unchanged.
    @param y in
    @returns int
    """
    return y


def gamma(z):
    """G.

    @intent Gamma triples z.
    @param z in
    @returns int
    """
    return z * 3
'''


def _materialize(root: Path, brain: Path, no_json: bool) -> None:
    cmd = [sys.executable, str(MATERIALIZE), "--root", str(root), "--src",
           str(root / "src"), "--brain", str(brain)]
    if no_json:
        cmd.append("--no-json")
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def _latest_changelog_entry(brain: Path) -> str:
    text = (brain / "Changelog.md").read_text()
    parts = text.split("\n## ")
    return parts[1] if len(parts) > 1 else ""  # newest entry (append-prepend: newest first)


def _graph_signature(brain: Path) -> set[tuple]:
    store = BrainStore.open(brain / "brain.sqlite")
    g = store.load_graph(DEFAULT_REVISION)
    sig = {(n["id"], n.get("intent"), (n.get("provenance") or {}).get("source_sha"))
           for n in g["nodes"]}
    store.close()
    return sig


@unittest.skipUnless(_have_git(), "git not available")
class MaterializePriorStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.braindir = tempfile.TemporaryDirectory()  # brains live outside the repo
        (self.root / "src").mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@t.t")
        _git(self.root, "config", "user.name", "t")
        (self.root / "flags.yml").write_text(FLAGS)
        (self.root / "src" / "m.py").write_text(MOD_V0)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v0")

    def tearDown(self) -> None:
        self.dir.cleanup()
        self.braindir.cleanup()

    def _advance_to_v1(self) -> None:
        (self.root / "src" / "m.py").write_text(MOD_V1)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")

    def test_no_json_incremental_is_not_a_full_readd(self) -> None:
        """The bug: in --no-json mode there is no graph.json, so the old code diffed
        against nothing and re-added every node each run. Now it diffs against sqlite."""
        brain = Path(self.braindir.name) / "b1"
        _materialize(self.root, brain, no_json=True)
        self.assertFalse((brain / "graph.json").exists())  # confirm --no-json
        self._advance_to_v1()
        _materialize(self.root, brain, no_json=True)

        entry = _latest_changelog_entry(brain)
        # incremental: gamma added, alpha changed — beta (unchanged) must NOT appear
        self.assertIn("#gamma", entry)
        self.assertIn("➕", entry)
        self.assertIn("#alpha", entry)
        self.assertIn("✏️", entry)
        self.assertNotIn("#beta", entry)  # the whole point — not a full re-add

    def test_json_and_no_json_agree(self) -> None:
        """Same v0→v1 sequence, one with graph.json and one without, must yield an
        identical brain.sqlite graph and identical newest changelog delta."""
        bj, bn = Path(self.braindir.name) / "bj", Path(self.braindir.name) / "bn"
        _materialize(self.root, bj, no_json=False)
        _materialize(self.root, bn, no_json=True)
        self._advance_to_v1()
        _materialize(self.root, bj, no_json=False)
        _materialize(self.root, bn, no_json=True)

        self.assertEqual(_graph_signature(bj), _graph_signature(bn))
        # compare the delta lines (ignore the per-run header with sha/timestamp)
        lines = lambda e: sorted(l for l in e.splitlines() if l.startswith("- "))
        self.assertEqual(lines(_latest_changelog_entry(bj)),
                         lines(_latest_changelog_entry(bn)))

    def test_idempotent_rerun_records_no_change(self) -> None:
        """Re-materializing with no code change diffs against sqlite → empty delta →
        no new changelog entry (previously --no-json would re-add everything)."""
        brain = Path(self.braindir.name) / "bi"
        _materialize(self.root, brain, no_json=True)
        first = (brain / "Changelog.md").read_text()
        _materialize(self.root, brain, no_json=True)   # no code change
        second = (brain / "Changelog.md").read_text()
        self.assertEqual(first, second)  # idempotent: no second entry appended


if __name__ == "__main__":
    unittest.main()
