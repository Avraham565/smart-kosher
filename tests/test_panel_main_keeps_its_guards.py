"""The panel's survival guards, checked as source.

`products/panel/device/main.py` holds the machinery that keeps a CrowPanel from
dying quietly: the try/backoff around the UART read, the `return_exceptions`
containment in the gather, and the sentinel that prints a proof of life every
30s. All three exist because the failure they cover is invisible -- the RGB DMA
keeps scanning out the last frame whatever the software does
(host/clean_board.py), so a dead panel and a healthy one look identical from
the outside.

Nothing else covers this file. It imports `lvgl`, so it cannot be imported on
the host at all, and behavioural tests are out. Hardware cannot cover it
either: both on-board suites *delete* main.py before they run
(host/run_hwtest.py) and hwtest.py imports neither main nor lvgl_loop. The only
verification these guards ever had was a one-off manual demonstration on the
bench. Until this file, `tests/test_boot_sentinel_is_in_sync.py` was the whole
of main.py's coverage, and it pins one string.

So: structural, on the AST, in the pattern of
tests/test_core_is_micropython_safe.py. Deliberately no refactor of main.py to
make it importable -- rewriting the composition root is a far bigger risk than
these claims are worth, and a structural check does not need it.

Each claim below is written so that removing the thing it names makes it red;
that was checked by breaking each in turn, and by mutations chosen by someone
other than their author. A structural test is exactly where a claim that
passes on every input gets written by accident, so a green run here is only
evidence while that stays true.

Two claims here exist because an earlier version of this file got them wrong,
both times the same way: an assertion phrased over *some* handler where the
guard needs *every* one.

First the width of the caught exception went unpinned, so `except Exception`
could become `except OSError` with all five still green and the guard hollow.
Pinning the width then still permitted

    except OSError:    ... await asyncio.sleep(delay)
    except Exception:  print(exc)

which satisfies "some handler yields" and "Exception is among the types caught"
simultaneously, while everything that is not an OSError spins the loop exactly
as it did before either guard existed. Both were found by review, after the
claims had been proved by mutation -- which is the point: mutation proves a
claim measures what it says, never that the claims cover the rule.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "products" / "panel" / "device" / "main.py"


def _calls_named(node, name):
    """Every Call under `node` spelled `name(...)` or `something.name(...)`."""
    found = []
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        func = inner.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            found.append(inner)
        elif isinstance(func, ast.Name) and func.id == name:
            found.append(inner)
    return found


def _contains_await(node):
    return any(isinstance(inner, ast.Await) for inner in ast.walk(node))


class PanelMainGuardTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(MAIN.read_text(encoding="utf-8"))

    def _function(self, name):
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == name:
                return node
        raise AssertionError(
            "main.py no longer defines {}(); every claim below reads it by "
            "name, so this test can no longer see the guard it covers".format(
                name))

    def _guarded_tries(self):
        """The try blocks in _zigbee_reader whose *body* does the UART read."""
        reader = self._function("_zigbee_reader")
        return [node for node in ast.walk(reader)
                if isinstance(node, ast.Try)
                and any(_calls_named(stmt, "readline") for stmt in node.body)]

    def _the_gather(self):
        run = self._function("_run")
        gathers = _calls_named(run, "gather")
        self.assertTrue(gathers, "_run no longer calls gather at all")
        return gathers

    def test_the_uart_read_itself_is_inside_the_try(self):
        # Guarding only process_line is the bug this replaced: readline() is
        # the call that touches the UART, and a raise there escaped into the
        # gather and ended main() -- leaving a frozen frame on a board that
        # looks alive and is dead.
        self.assertTrue(
            self._guarded_tries(),
            "_zigbee_reader's readline() is no longer inside a try; a UART "
            "fault escapes into the gather and ends the reader")

    def test_the_reader_yields_before_it_retries(self):
        # The half that is easy to drop while keeping the try. An except that
        # does not give up the queue turns a UART that faults on every read
        # into a hot loop, and on one cooperative loop that starves LVGL and
        # the scheduler -- the same freeze by another door.
        #
        # Every handler, not merely one of them. Adding a second except is the
        # ordinary way to give one error type its own treatment, and
        #
        #     except OSError:     ... await asyncio.sleep(delay)
        #     except Exception:   print(exc)
        #
        # satisfies "some handler yields" and "Exception is caught" at once,
        # while everything that is not an OSError spins the loop exactly as
        # before -- the first handler's backoff still present and still
        # looking right.
        tries = self._guarded_tries()
        self.assertTrue(tries, "no guarded try to read the handlers from")
        bare = []
        for node in tries:
            self.assertTrue(
                node.handlers,
                "the try around the UART read has no except at all")
            for handler in node.handlers:
                if _contains_await(handler):
                    continue
                caught = (handler.type.id
                          if isinstance(handler.type, ast.Name) else "...")
                bare.append("main.py:{} except {}".format(
                    handler.lineno, caught))
        self.assertEqual(
            [], bare,
            "every except on the UART read has to yield before the loop comes "
            "round again; these do not, so a read that always faults spins "
            "the loop and starves LVGL and the scheduler")

    def test_the_handler_catches_the_full_width_of_Exception(self):
        # Narrowing the caught type restores the original bug for everything
        # outside it, with the try and the backoff both still in place and
        # still looking right. Not via the framing path -- process_line
        # catches uart_decode's ValueError itself and returns False, so a
        # corrupt frame never reaches here -- but it calls _handle_async
        # unguarded, and an AttributeError out of _ieee_for_short (a registry
        # entry that is not a dict) escapes into the gather exactly as before.
        #
        # BaseException is rejected rather than waved through as "wider
        # still". It also swallows CancelledError, so the task can no longer
        # be stopped, and KeyboardInterrupt -- which host/clean_board.py spams
        # as Ctrl-C to catch main.py before it starts. That is the mechanism
        # keeping a deploy from writing onto a board with live DMA, so eating
        # it here trades a caught error for a corrupt filesystem: a change of
        # behaviour, not a hardening. A bare except is the same semantics once
        # more, and is already ruff E722 under this repo's select list.
        tries = self._guarded_tries()
        # Without this the loop below asserts nothing when the try is gone
        # altogether, and this test goes green on the one input it should
        # have the least to say about. The regression is caught either way,
        # by the two tests above -- but an assertion that holds on every
        # input is the thing this file exists to not contain.
        self.assertTrue(tries, "no guarded try to read the caught type from")
        for node in tries:
            caught = set(handler.type.id for handler in node.handlers
                         if isinstance(handler.type, ast.Name))
            self.assertNotIn(
                "BaseException", caught,
                "the UART handler catches BaseException; that swallows "
                "CancelledError and the Ctrl-C clean_board.py depends on, "
                "which is a change of behaviour and not a wider guard")
            self.assertIn(
                "Exception", caught,
                "the UART handler no longer catches Exception; everything "
                "outside the narrower type escapes into the gather and ends "
                "the reader -- the exact bug the try was added for")

    def test_the_gather_contains_a_raise_rather_than_unwinding(self):
        # Without return_exceptions the first raise unwinds through gather,
        # main() returns, and the RGB DMA keeps scanning out the last frame
        # forever: a wall panel showing buttons that answer nothing.
        for call in self._the_gather():
            keywords = dict((kw.arg, kw.value) for kw in call.keywords)
            flag = keywords.get("return_exceptions")
            self.assertTrue(
                isinstance(flag, ast.Constant) and flag.value is True,
                "gather at main.py:{} does not pass return_exceptions=True; "
                "one task raising takes the whole panel down".format(
                    call.lineno))

    def test_the_sentinel_task_is_held_by_that_gather(self):
        # MicroPython collects a task nothing holds a reference to, before it
        # ever runs (CLAUDE.md). Being an argument to the gather is what keeps
        # the sentinel alive; fire-and-forget would silently lose it, and the
        # symptom is the absence of a console line nobody is watching for yet.
        run = self._function("_run")
        held = None
        for node in ast.walk(run):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            if not _calls_named(node.value, "create_task"):
                continue
            if not node.value.args:
                continue
            inner = node.value.args[0]
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_sentinel"
                    and isinstance(node.targets[0], ast.Name)):
                held = node.targets[0].id
                break
        self.assertIsNotNone(
            held,
            "_run no longer binds the _sentinel task to a name; an unheld "
            "task is collected before it runs on MicroPython")
        passed = set()
        for call in self._the_gather():
            for arg in call.args:
                if isinstance(arg, ast.Name):
                    passed.add(arg.id)
        self.assertIn(
            held, passed,
            "the _sentinel task ({}) is created but never passed to gather; "
            "nothing holds it and the panel loses its only proof of "
            "life".format(held))

    def test_the_sentinel_reads_the_pump_counter(self):
        # The signal with no substitute. Task.done() cannot see a wedged task,
        # because wedged is still 'running'; the pump's cycle count is what
        # catches it, and everything shares that one cooperative loop, so a
        # count that stops means the loop stopped.
        sentinel = self._function("_sentinel")
        reads = [node for node in ast.walk(sentinel)
                 if isinstance(node, ast.Attribute)
                 and node.attr == "beats"
                 and isinstance(node.value, ast.Name)
                 and node.value.id == "lvgl_loop"
                 and isinstance(node.ctx, ast.Load)]
        self.assertTrue(
            reads,
            "_sentinel no longer reads lvgl_loop.beats; it is left with "
            "done(), which cannot tell a wedged task from a working one")


if __name__ == "__main__":
    unittest.main()
