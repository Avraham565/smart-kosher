# A tiny reactive core (the "signals" model -- SolidJS/Preact-style, the clean
# cousin of React hooks) for a retained-mode LVGL UI.
#
#   Signal(v)          an observable value; .get() reads, .set(v) writes
#   effect(fn)         runs fn now and re-runs whenever a Signal it *read* changes
#   computed(fn)       a derived, cached Signal recomputed from its dependencies
#   bind(setter, fn)   effect that pushes fn() into setter(...) -- the UI glue
#
# Dependencies are tracked automatically: while an effect runs, every Signal.get()
# it touches subscribes it, so you never list deps by hand. Propagation is
# synchronous and single-threaded (matches our one asyncio loop -> no locks); a
# .set() to an equal value is skipped, so bound widgets don't repaint needlessly.
#
# Pure Python, no LVGL -- unit-tested on CPython. (bind() only calls setter(x), so
# it works with any object, e.g. label.set_text, and with fakes in tests.)
#
# Rule: never .set() a Signal from inside an effect that .get()s it -- that is an
# infinite loop, exactly as it would be in any reactive system.

_active = None          # the effect currently running, for dependency capture


class Signal:
    def __init__(self, value=None, eq=None):
        self._value = value
        self._observers = []
        self._eq = eq or _default_eq

    def get(self):
        if _active is not None:
            _active._track(self)
        return self._value

    def peek(self):
        """Read without subscribing the active effect (no dependency)."""
        return self._value

    def set(self, value):
        if self._eq(self._value, value):
            return
        self._value = value
        for observer in list(self._observers):   # copy: observers re-subscribe
            observer._notify()

    def update(self, fn):
        self.set(fn(self._value))

    def _subscribe(self, observer):
        if observer not in self._observers:
            self._observers.append(observer)

    def _unsubscribe(self, observer):
        try:
            self._observers.remove(observer)
        except ValueError:
            pass


def _default_eq(a, b):
    # Cheap identity/equality; dict/list values should be replaced, not mutated
    # in place (a mutated-in-place container would compare equal and skip).
    return a is b or a == b


class _Effect:
    def __init__(self, fn):
        self._fn = fn
        self._deps = []
        self._disposed = False

    def _track(self, signal):
        if signal not in self._deps:
            self._deps.append(signal)
            signal._subscribe(self)

    def _run(self):
        if self._disposed:
            return None
        global _active
        for dep in self._deps:            # drop stale deps; re-tracked on read
            dep._unsubscribe(self)
        self._deps = []
        prev = _active
        _active = self
        try:
            return self._fn()
        except Exception as exc:
            # Contain a bad binding: one failing effect must not propagate up
            # through Signal.set and freeze every other observer (e.g. the clock).
            print("effect error:", exc)
            return None
        finally:
            _active = prev

    def _notify(self):
        self._run()

    def dispose(self):
        for dep in self._deps:
            dep._unsubscribe(self)
        self._deps = []
        self._disposed = True


def effect(fn):
    """Run fn now and re-run on any change to Signals it read. Returns the
    effect; keep the reference alive (its Signals do, once it reads one) and call
    .dispose() to stop it."""
    eff = _Effect(fn)
    eff._run()
    return eff


def computed(fn, eq=None):
    """A read-only Signal derived from fn, recomputed when its dependencies
    change. Read it with .get() like any Signal."""
    sig = Signal(None, eq=eq)
    effect(lambda: sig.set(fn()))
    return sig


def bind(setter, fn):
    """UI glue: call setter(fn()) now and whenever fn's dependencies change.
    e.g. bind(label.set_text, lambda: fmt(now.get()))."""
    return effect(lambda: setter(fn()))


def bind_text(label, fn):
    """Bind an LVGL label's text to fn(): label shows fn() and re-renders it
    whenever any Signal fn reads changes. (Only calls label.set_text, so it stays
    LVGL-free and testable.)"""
    return bind(label.set_text, fn)
