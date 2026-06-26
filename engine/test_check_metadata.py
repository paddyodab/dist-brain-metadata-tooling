#!/usr/bin/env python3
"""Tests for the boy-scout (diff-scoped) gate: python3 engine/test_check_metadata.py

The discriminating spec: a touched file with ONE changed undocumented function AND a
pre-existing undocumented sibling → scoped gate fails ONLY on the changed function.
Function-level, not file-level — incidental siblings are not force-marched (that would
break the "don't boil the ocean" adoption ramp). Needs git; skips if unavailable.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import check_metadata


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _have_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


GOOD = '''\
def good(x):
    """G.

    @intent Good returns x.
    @param x in
    @returns int
    """
    return x
'''

# bad + also_bad: both public, both missing @intent (pre-existing legacy debt)
DEBT = '''\
def bad(x):
    return x


def also_bad(y):
    return y
'''


@unittest.skipUnless(_have_git(), "git not available")
class BoyScoutGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.src = self.root / "src"
        self.src.mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@t.t")
        _git(self.root, "config", "user.name", "t")
        (self.src / "m.py").write_text(GOOD + "\n\n" + DEBT)
        (self.root / "flags.yml").write_text("flags: {}\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v0")
        self.base = _git(self.root, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_only_changed_undocumented_function_is_gated(self) -> None:
        # change `bad`'s body only; `also_bad` (also undocumented) is untouched
        (self.src / "m.py").write_text(
            GOOD + "\n\ndef bad(x):\n    return x + 1\n\n\ndef also_bad(y):\n    return y\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        errs = check_metadata.scoped_check(self.root, self.src, set(),
                                           since=self.base, include_working=False)
        blob = "\n".join(errs)
        self.assertIn("bad()", blob)            # changed + undocumented → gated
        self.assertNotIn("also_bad()", blob)    # unchanged sibling → NOT gated (the whole point)
        self.assertNotIn("good()", blob)        # unchanged + documented → fine

    def test_new_function_in_touched_file_is_gated(self) -> None:
        (self.src / "m.py").write_text(
            GOOD + "\n\n" + DEBT + "\n\ndef fresh(z):\n    return z\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "add fresh")
        errs = check_metadata.scoped_check(self.root, self.src, set(),
                                           since=self.base, include_working=False)
        blob = "\n".join(errs)
        self.assertIn("fresh()", blob)
        self.assertNotIn("also_bad()", blob)

    def test_changed_function_with_valid_contract_passes(self) -> None:
        new_good = GOOD.replace("return x", "return x + 0")
        (self.src / "m.py").write_text(new_good + "\n\n" + DEBT)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "tweak good")
        errs = check_metadata.scoped_check(self.root, self.src, set(),
                                           since=self.base, include_working=False)
        self.assertNotIn("good()", "\n".join(errs))

    def test_full_mode_still_gates_everything(self) -> None:
        # unscoped: both bad and also_bad must fail (default behavior intact)
        errs: list[str] = []
        for f in sorted(self.src.rglob("*.py")):
            errs.extend(check_metadata.check_file(f, self.root, set()))
        blob = "\n".join(errs)
        self.assertIn("bad()", blob)
        self.assertIn("also_bad()", blob)


PY_BACKEND_GOOD = '''\
def get_user(user_id):
    """Fetch a user.

    @intent Returns the User for the given id.
    @param user_id int
    @returns User
    """
    return {"id": user_id}
'''

PY_BACKEND_INVALID_TAG = '''\
def render_user(user_id):
    """Render hook (invalid in backend).

    @intent Returns user id.
    @param user_id int
    @renders user_id
    """
    return user_id
'''

PY_FRONTEND_GOOD = '''\
def UserCard():
    """React component.

    @intent Renders the UserCard for the given User.
    @renders JSX
    """
    return None
'''

PY_FRONTEND_INVALID_TAG = '''\
def user_raises(props):
    """Bad tag.

    @intent Renders nothing.
    @props props
    @raises ValueError
    """
    raise ValueError
'''


@unittest.skipUnless(_have_git(), "git not available")
class ContextAwareGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.backend = self.root / "backend"
        self.frontend = self.root / "frontend"
        self.backend.mkdir()
        self.frontend.mkdir()
        (self.backend / "CONTEXT.md").write_text("# Backend\n")
        (self.frontend / "CONTEXT.md").write_text("# Frontend\n")
        (self.backend / "contracts.yml").write_text("""\
context: backend
kind: service
valid_tags:
  intent:
    required: true
  param:
    required: auto
  returns:
    required: auto
  raises:
    required: false
""")
        (self.frontend / "contracts.yml").write_text("""\
context: frontend
kind: component
valid_tags:
  intent:
    required: true
  props:
    required: auto
  renders:
    required: true
""")
        (self.root / "flags.yml").write_text("flags: {}\n")

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_backend_valid_tag_passes(self) -> None:
        f = self.backend / "svc.py"
        f.write_text(PY_BACKEND_GOOD)
        errs = check_metadata.check_file(f, self.root, set())
        self.assertEqual(errs, [])

    def test_backend_invalid_tag_fails(self) -> None:
        f = self.backend / "svc.py"
        f.write_text(PY_BACKEND_INVALID_TAG)
        errs = check_metadata.check_file(f, self.root, set())
        blob = "\n".join(errs)
        self.assertIn("@renders is not a valid tag in context 'backend'", blob)

    def test_frontend_valid_tag_passes(self) -> None:
        f = self.frontend / "cmp.py"
        f.write_text(PY_FRONTEND_GOOD)
        errs = check_metadata.check_file(f, self.root, set())
        self.assertEqual(errs, [])

    def test_frontend_invalid_tag_fails(self) -> None:
        f = self.frontend / "cmp.py"
        f.write_text(PY_FRONTEND_INVALID_TAG)
        errs = check_metadata.check_file(f, self.root, set())
        blob = "\n".join(errs)
        self.assertIn("@raises is not a valid tag in context 'frontend'", blob)

    def test_frontend_required_renders_missing_fails(self) -> None:
        """@renders is required: true in frontend contracts."""
        f = self.frontend / "cmp.py"
        f.write_text('''\
def UserCard():
    """Missing renders.

    @intent Renders the UserCard.
    """
    pass
''')
        errs = check_metadata.check_file(f, self.root, set())
        blob = "\n".join(errs)
        self.assertIn("missing required @renders (context: frontend)", blob)

    def test_required_auto_param_missing(self) -> None:
        f = self.backend / "svc.py"
        f.write_text('''\
def no_param(user_id):
    """Missing @param.

    @intent Returns user.
    @returns dict
    """
    return {"id": user_id}
''')
        errs = check_metadata.check_file(f, self.root, set())
        blob = "\n".join(errs)
        self.assertIn("@param missing for ['user_id']", blob)

    def test_no_contracts_falls_back_to_default_tags(self) -> None:
        """A repo with no CONTEXT.md/contracts.yml still uses today's hardcoded tags."""
        src = self.root / "src"
        src.mkdir()
        f = src / "legacy.py"
        f.write_text(PY_BACKEND_GOOD)
        errs = check_metadata.check_file(f, self.root, set())
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
