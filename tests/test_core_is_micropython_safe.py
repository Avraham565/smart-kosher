"""Portability rules that CPython cannot fail on, checked as source.

Everything here is legal Python 3 and passes every other test in this suite.
It is only wrong on the device -- which means the suite being green proves
nothing about it, and the failure lands at import time on a board, as a boot
loop, not as a red test.

Multiple inheritance is the case that prompted this file. Fixing a 500 meant
widening a repository exception, and the obvious spelling was
``class RepositoryValidationError(RepositoryError, ValueError)``. That is fine
on CPython. On the panel's own MicroPython 1.24.1 it is:

    TypeError: multiple bases have instance lay-out conflict

raised while *defining* the class -- so importing smart_kosher.adapters at all
would have failed, on both products, with a fully green suite behind it.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Everything that is copied to a board: the shared core, plus the panel and
# hub modules that are flashed alongside it.
DEVICE_TREES = (
    ROOT / "src" / "smart_kosher",
    ROOT / "products" / "panel" / "device",
    ROOT / "products" / "panel" / "hwtest",
    ROOT / "products" / "hub" / "device",
)


def _device_sources():
    for tree in DEVICE_TREES:
        for path in sorted(tree.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


class MicroPythonSafetyTests(unittest.TestCase):
    def test_at_least_one_source_was_scanned(self):
        # A path typo here would make every test below pass on an empty set.
        self.assertGreater(len(list(_device_sources())), 50)

    def test_no_class_has_more_than_one_base(self):
        offenders = []
        for path in _device_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and len(node.bases) > 1:
                    offenders.append("{}:{} {}".format(
                        path.relative_to(ROOT), node.lineno, node.name))
        self.assertEqual([], offenders,
                         "MicroPython rejects these at import time "
                         "(multiple bases have instance lay-out conflict)")

    def test_no_f_strings_or_annotations_in_device_code(self):
        # CLAUDE.md bans both; ruff is configured for correctness rules only
        # and does not enforce it, so nothing else would notice.
        offenders = []
        for path in _device_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                where = "{}:{}".format(path.relative_to(ROOT),
                                       getattr(node, "lineno", 0))
                if isinstance(node, ast.JoinedStr):
                    offenders.append(where + " f-string")
                elif isinstance(node, ast.AnnAssign):
                    offenders.append(where + " annotated assignment")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns is not None:
                        offenders.append(where + " return annotation")
                    args = node.args
                    annotated = [a for a in list(args.args) + list(args.kwonlyargs)
                                 if a.annotation is not None]
                    if annotated:
                        offenders.append(where + " argument annotation")
        self.assertEqual([], offenders)

    def test_no_forbidden_imports_in_device_code(self):
        # dataclasses/typing/abc do not exist on the device.
        banned = {"dataclasses", "typing", "abc", "collections.abc"}
        offenders = []
        for path in _device_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name in banned or name.split(".")[0] in banned:
                        offenders.append("{}:{} {}".format(
                            path.relative_to(ROOT), node.lineno, name))
        self.assertEqual([], offenders)

    def test_no_await_inside_a_comprehension(self):
        # Legal Python, rejected by the device's compiler.
        comprehensions = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        offenders = []
        for path in _device_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, comprehensions):
                    if any(isinstance(inner, ast.Await) for inner in ast.walk(node)):
                        offenders.append("{}:{}".format(
                            path.relative_to(ROOT), node.lineno))
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
