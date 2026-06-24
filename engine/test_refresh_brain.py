#!/usr/bin/env python3
"""Tests for diff-scoped refresh (stdlib only): python3 engine/test_refresh_brain.py

Headline invariant: a FULL extract+upsert at HEAD must equal (full extract+upsert at an
older SHA, then a diff-scoped refresh up to HEAD) — same nodes, edges, AND revision counts.
Needs git; skips cleanly if git is unavailable.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from brain_store import DEFAULT_REVISION, BrainStore
from extract import extract_full, extract_scoped, git_changed_paths
from refresh_brain import scoped_delta


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _have_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


FLAGS_YML = """\
flags:
  enable_x:
    description: toggle x
    default: false
    owner: team
"""

MOD_V0 = '''\
def alpha(store, url):
    """First.

    @intent Alpha makes a thing and returns it.
    @param store the store
    @param url the url
    @returns Thing
    """
    return 1


def beta(x):
    """Second.

    @intent Beta validates x and raises on bad input.
    @param x the input
    @raises ValueError if x is bad
    """
    raise ValueError("bad")
'''

# v1: alpha intent changed; beta deleted; gamma added.
MOD_V1 = '''\
def alpha(store, url):
    """First.

    @intent Alpha now ALSO caches the thing before returning it.
    @param store the store
    @param url the url
    @returns Thing
    """
    return 1


def gamma(y):
    """Third.

    @intent Gamma sums things.
    @param y the input
    @returns int
    """
    return y
'''


def _normalize(graph: dict) -> dict:
    nodes = sorted(
        (n["id"], n["type"], n.get("intent"), (n.get("provenance") or {}).get("source_sha"))
        for n in graph["nodes"]
    )
    edges = sorted((e["from"], e["to"], e["type"]) for e in graph["edges"])
    return {"nodes": nodes, "edges": edges}


@unittest.skipUnless(_have_git(), "git not available")
class RefreshParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        # brain lives OUTSIDE the repo (like BRAIN_DIR=/tmp) so it never enters git
        self.braindir = tempfile.TemporaryDirectory()
        (self.root / "src").mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@t.t")
        _git(self.root, "config", "user.name", "t")
        (self.root / "flags.yml").write_text(FLAGS_YML)
        (self.root / "src" / "mod.py").write_text(MOD_V0)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v0")
        self.sha0 = _git(self.root, "rev-parse", "--short", "HEAD")
        self.src = self.root / "src"
        self.flags = self.root / "flags.yml"

    def tearDown(self) -> None:
        self.dir.cleanup()
        self.braindir.cleanup()

    def _open(self, name: str) -> BrainStore:
        return BrainStore.open(Path(self.braindir.name) / name)

    def test_scoped_refresh_equals_full(self) -> None:
        # B: full @ v0, then a diff-scoped refresh to v1
        b = self._open("b.sqlite")
        full0 = extract_full(self.root, self.src, self.flags)
        b.upsert_main(self.sha0, full0["nodes"], full0["edges"],
                      {"added": full0["nodes"], "removed": [], "changed": []})

        # advance the repo to v1
        (self.src / "mod.py").write_text(MOD_V1)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        sha1 = _git(self.root, "rev-parse", "--short", "HEAD")

        changed, deleted = git_changed_paths(self.root, self.sha0, include_working=False)
        self.assertIn("src/mod.py", changed)
        scoped = extract_scoped(self.root, self.src, self.flags, changed, deleted)
        prev = b.load_graph(DEFAULT_REVISION)
        delta = scoped_delta(prev["nodes"], scoped["nodes"], scoped["scope"], self.flags.name)
        b.upsert_main(sha1, scoped["nodes"], scoped["edges"], delta)

        # C: full @ v1
        c = self._open("c.sqlite")
        full1 = extract_full(self.root, self.src, self.flags)
        c.upsert_main(sha1, full1["nodes"], full1["edges"],
                      {"added": full1["nodes"], "removed": [], "changed": []})

        gb, gc = b.load_graph(DEFAULT_REVISION), c.load_graph(DEFAULT_REVISION)
        # parity: nodes + edges identical
        self.assertEqual(_normalize(gb), _normalize(gc))
        # parity: revision counts identical (the count fix)
        rb = {r["ref"]: r for r in b.list_revisions()}[DEFAULT_REVISION]
        rc = {r["ref"]: r for r in c.list_revisions()}[DEFAULT_REVISION]
        self.assertEqual((rb["node_count"], rb["edge_count"]),
                         (rc["node_count"], rc["edge_count"]))
        b.close(); c.close()

    def test_delta_shape_add_change_remove(self) -> None:
        b = self._open("b.sqlite")
        full0 = extract_full(self.root, self.src, self.flags)
        b.upsert_main(self.sha0, full0["nodes"], full0["edges"],
                      {"added": full0["nodes"], "removed": [], "changed": []})

        (self.src / "mod.py").write_text(MOD_V1)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")

        changed, deleted = git_changed_paths(self.root, self.sha0, include_working=False)
        scoped = extract_scoped(self.root, self.src, self.flags, changed, deleted)
        delta = scoped_delta(b.load_graph(DEFAULT_REVISION)["nodes"],
                             scoped["nodes"], scoped["scope"], self.flags.name)
        ids = lambda key: {n["id"] for n in delta[key]}
        self.assertEqual(ids("added"), {"src/mod.py#gamma"})
        self.assertEqual(ids("changed"), {"src/mod.py#alpha"})
        self.assertEqual({d["id"] for d in delta["removed"]}, {"src/mod.py#beta"})
        b.close()

    def test_out_of_scope_untouched(self) -> None:
        # two modules; change only one; assert the other's flag-edge / node survive
        (self.src / "other.py").write_text(MOD_V0.replace("alpha", "omega").replace("beta", "psi"))
        _git(self.root, "add", "-A"); _git(self.root, "commit", "-q", "-m", "add other")
        base = _git(self.root, "rev-parse", "--short", "HEAD")

        b = self._open("b.sqlite")
        full = extract_full(self.root, self.src, self.flags)
        b.upsert_main(base, full["nodes"], full["edges"],
                      {"added": full["nodes"], "removed": [], "changed": []})

        (self.src / "mod.py").write_text(MOD_V1)
        _git(self.root, "add", "-A"); _git(self.root, "commit", "-q", "-m", "v1")
        sha1 = _git(self.root, "rev-parse", "--short", "HEAD")

        changed, deleted = git_changed_paths(self.root, base, include_working=False)
        self.assertEqual(changed, {"src/mod.py"})
        scoped = extract_scoped(self.root, self.src, self.flags, changed, deleted)
        delta = scoped_delta(b.load_graph(DEFAULT_REVISION)["nodes"],
                             scoped["nodes"], scoped["scope"], self.flags.name)
        b.upsert_main(sha1, scoped["nodes"], scoped["edges"], delta)

        ids = {n["id"] for n in b.load_graph(DEFAULT_REVISION)["nodes"]}
        self.assertIn("src/other.py#omega", ids)  # untouched module preserved
        self.assertIn("src/other.py#psi", ids)
        self.assertIn("src/mod.py#gamma", ids)     # touched module updated
        self.assertNotIn("src/mod.py#beta", ids)   # removed symbol gone
        b.close()


if __name__ == "__main__":
    unittest.main()
