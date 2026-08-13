# UI hardware test suite -- runs ON the panel, against the real display.
#
# What a host test cannot answer, and this can: whether the screen actually
# builds on the device. CPython proves the search logic; only the panel proves
# that the fonts load, that LVGL has the memory for four result slots plus a
# 27-key Hebrew keyboard, that the layout fits in 800x480 without the scrolling
# the RGB driver forbids, and that MicroPython sorts and slices Hebrew strings
# the same way CPython does. Every one of those has bitten this project before.
#
# The picker is driven through its own handlers rather than by faking touch
# events: the point is the component's behaviour, and a synthetic touch would
# test LVGL's hit-testing instead.
#
# Nothing is written to /data -- no setting, schedule or device is changed.
#
# Usage (from the host):  python products/panel/host/run_hwtest_ui.py

import gc

import lvgl as lv

import city_picker
import display
import theme
from smart_kosher.data import load_cities, search_cities

_results = []


def _check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("{:<44} {}{}".format(
        name, "PASS" if ok else "FAIL", "  " + detail if detail else ""))
    return ok


# ── the pure logic, re-verified on MicroPython ────────────────────────────────

def test_search_agrees_with_the_host():
    """Hebrew string handling is the part most likely to differ here."""
    cities = load_cities()
    _check("search: full list is every city",
           len(search_cities("")) == len(cities),
           "{} of {}".format(len(search_cities("")), len(cities)))

    _check("search: sorted by name",
           [c["name_he"] for c in search_cities("")]
           == sorted(c["name_he"] for c in cities.values()))

    names = [c["name_he"] for c in search_cities("ברק")]
    _check("search: word prefix finds בני ברק", "בני ברק" in names, str(names))

    names = [c["name_he"] for c in search_cities("ירו")]
    _check("search: name prefix finds ירושלים", "ירושלים" in names, str(names))

    _check("search: unknown text finds nothing",
           search_cities("קקק") == [])

    unreachable = []
    for city in cities.values():
        name = city["name_he"]
        for length in range(2, len(name) + 1):
            top = search_cities(name[:length], limit=city_picker.MAX_RESULTS)
            if name in [c["name_he"] for c in top]:
                break
        else:
            unreachable.append(name)
    _check("search: every city reachable in 4 slots",
           not unreachable, str(unreachable))


# ── the screen, on the real display ───────────────────────────────────────────

def test_picker_builds_on_the_panel():
    before = gc.mem_free()
    picked = []
    home = lv.screen_active()

    city_picker.open(picked.append)
    _check("picker: screen builds", city_picker._screen is not None)
    _check("picker: it is the active screen",
           lv.screen_active() is city_picker._screen)
    _check("picker: four result slots exist",
           len(city_picker._result_slots) == city_picker.MAX_RESULTS)

    cost = before - gc.mem_free()
    _check("picker: build cost is sane", cost < 120000, "{} bytes".format(cost))

    return home, picked


def test_typing_filters_the_slots(home, picked):
    def visible():
        return [label.get_text()
                for button, label in city_picker._result_slots
                if not button.has_flag(lv.obj.FLAG.HIDDEN)]

    city_picker._state["buf"] = ""
    city_picker._refresh()
    _check("typing: empty query fills all four slots",
           len(visible()) == city_picker.MAX_RESULTS, str(visible()))

    for ch in "ירו":
        city_picker._on_letter(ch)
    shown = visible()
    _check("typing: ירו narrows to ירושלים",
           shown == ["ירושלים"], str(shown))

    city_picker._backspace(None)
    city_picker._backspace(None)
    city_picker._backspace(None)
    _check("typing: backspace restores the full list",
           len(visible()) == city_picker.MAX_RESULTS, str(visible()))

    for ch in "ברק":
        city_picker._on_letter(ch)
    _check("typing: word prefix ברק shows בני ברק",
           "בני ברק" in visible(), str(visible()))

    city_picker._clear(None)
    _check("typing: clear empties the query",
           city_picker._state["buf"] == "")

    for ch in "קקק":
        city_picker._on_letter(ch)
    _check("typing: no match hides every slot", visible() == [], str(visible()))


def test_choosing_returns_the_city_id(home, picked):
    city_picker._state["buf"] = ""
    for ch in "צפ":
        city_picker._on_letter(ch)
    shown = [c["name_he"] for c in city_picker._state["shown"]]
    city_picker._choose(0)

    _check("choose: callback fired once", len(picked) == 1, str(picked))
    _check("choose: it is a real city id",
           picked and picked[0] in load_cities(), str(picked))
    _check("choose: it matches the slot tapped",
           picked and load_cities()[picked[0]]["name_he"] == shown[0],
           "{} vs {}".format(picked, shown[:1]))
    _check("choose: returned to the calling screen",
           lv.screen_active() is home)


SCREEN_W, SCREEN_H = 800, 480


def _box(obj):
    """Absolute screen coordinates of `obj` as (x1, y1, x2, y2).

    Absolute, deliberately. get_x()/get_y() are relative to the parent's
    *content* area, while center() and align() place a child relative to its
    *box* -- so a centred label inside a padded button reports a legal negative
    x, and comparing those two frames invents overflow that is not there.
    Screen coordinates have no such ambiguity, and "must not leave the page" is
    a statement about the screen anyway.
    """
    area = lv.area_t()
    obj.get_coords(area)
    return area.x1, area.y1, area.x2, area.y2


def _escapes(root, tolerance=1):
    """Every visible widget in the subtree that leaves the panel's 800x480.

    The panel has no scrollbars, so anything off the page is simply lost, and
    lost silently: LVGL clips the pixels and nothing complains.
    """
    out = []

    def walk(obj):
        for index in range(obj.get_child_count()):
            child = obj.get_child(index)
            if child.has_flag(lv.obj.FLAG.HIDDEN):
                continue
            x1, y1, x2, y2 = _box(child)
            if (x1 < -tolerance or y1 < -tolerance
                    or x2 > SCREEN_W + tolerance or y2 > SCREEN_H + tolerance):
                text = ""
                try:
                    text = child.get_text()
                except Exception:
                    pass
                out.append("{} at {},{}..{},{}".format(
                    text or "widget", x1, y1, x2, y2))
            walk(child)

    walk(root)
    return out


def _text_width(font, text):
    """Natural width of `text`, measured by rendering it unconstrained."""
    probe = lv.label(lv.screen_active())
    probe.set_style_text_font(font, lv.PART.MAIN)
    probe.set_text(text)
    probe.update_layout()
    width = probe.get_width()
    probe.delete()
    return width


def test_no_city_name_overflows_its_slot():
    """Every one of the forty names, in a real slot, measured.

    The names are not uniform -- מודיעין עילית is thirteen characters against
    עכו's three -- and a slot is a fixed 48% of the row. A name that does not
    fit does not error; it draws over its neighbour, or vanishes at the clip.
    """
    city_picker.open(lambda city_id: None)
    cell, label = city_picker._result_slots[0]
    cell.update_layout()
    limit = cell.get_content_width()

    worst_name, worst_width = "", 0
    wrapped = []
    one_line = _text_width(theme.FONTS.body, "א")
    for city in search_cities(""):
        name = city["name_he"]
        used = _text_width(theme.FONTS.body, name)
        if used > worst_width:
            worst_name, worst_width = name, used
        # Does it still fit on one line inside the slot?
        label.set_text(name)
        cell.update_layout()
        if label.get_height() > one_line * 2:
            wrapped.append(name)

    _check("overflow: widest name fits its slot on one line",
           worst_width <= limit,
           "{} needs {} of {}".format(worst_name, worst_width, limit))
    _check("overflow: no name has to wrap", not wrapped, str(wrapped[:3]))

    city_picker._refresh()


def test_no_widget_escapes_its_parent(home):
    """The whole picker tree, at its most crowded: four matches on screen."""
    city_picker.open(lambda city_id: None)
    city_picker._state["buf"] = ""
    city_picker._refresh()
    screen = lv.screen_active()
    screen.update_layout()

    escaped = _escapes(screen)
    _check("overflow: picker tree stays on screen", not escaped, str(escaped[:3]))

    # And with the hint line showing, which is the widest text on the page.
    city_picker._state["buf"] = "א"
    city_picker._refresh()
    screen.update_layout()
    escaped = _escapes(screen)
    _check("overflow: picker with hint stays on screen", not escaped,
           str(escaped[:3]))

    # Every city in every slot, not just the four that happen to match.
    names = [c["name_he"] for c in search_cities("")]
    for start in range(0, len(names), city_picker.MAX_RESULTS):
        for slot, (cell, label) in enumerate(city_picker._result_slots):
            if start + slot < len(names):
                label.set_text(names[start + slot])
                cell.remove_flag(lv.obj.FLAG.HIDDEN)
        screen.update_layout()
        escaped = _escapes(screen)
        if escaped:
            break
    _check("overflow: all 40 names in all 4 slots stay on screen",
           not escaped, str(escaped[:3]))

    city_picker._refresh()
    lv.screen_load(home)


def test_settime_still_fits_with_the_city_row(home):
    """The clock screen has no scrollbar, and the city row ate its slack.

    Measured with update_layout(), which recalculates geometry only. Pumping
    LVGL with timer_handler() from here would race the display DMA -- the loop
    owns the pump (lvgl_loop.py), and driving it from outside crashes the board.
    """
    import settime

    class _NoApi:
        """settime only asks for settings.get; letting it fail is a real case --
        the chip falls back to a dash and stays tappable."""
        async def dispatch(self, op, params=None):
            raise Exception("no brain in this test")

    settime.open(_NoApi())
    scr = lv.screen_active()
    _check("settime: screen builds with the city row",
           scr is settime._screen)
    _check("settime: city chip exists", settime._state.get("city") is not None)

    scr.update_layout()
    body = scr.get_child(1)
    height = body.get_height()
    children = [body.get_child(i) for i in range(body.get_child_count())]
    bottom = max(child.get_y() + child.get_height() for child in children)

    _check("settime: content fits the body", bottom <= height,
           "{} of {}".format(bottom, height))
    _check("settime: nothing is scrollable",
           not body.has_flag(lv.obj.FLAG.SCROLLABLE))

    # The longest city name in the row, which is where it would collide with
    # the caption beside it.
    escaped = []
    for city in search_cities(""):
        settime._show_city(city["name_he"])
        scr.update_layout()
        escaped = _escapes(scr)
        if escaped:
            escaped = ["{}: {}".format(city["name_he"], escaped[0])]
            break
    _check("settime: every city name stays on screen", not escaped,
           str(escaped[:2]))

    lv.screen_load(home)


def test_other_screens_stay_on_the_page(home):
    """Not only the screens this change touched.

    The zmanim page is here because it lost a row in the same work -- it was
    laid out as nineteen static entries in two columns, and it is now eighteen.
    A page that is one row short is harmless; one row long is invisible.
    """
    import zmanim_page

    screen = zmanim_page.build()
    lv.screen_load(screen)
    screen.update_layout()
    escaped = _escapes(screen)
    _check("overflow: zmanim page stays on screen", not escaped,
           str(escaped[:3]))

    lv.screen_load(home)
    screen.delete()


def test_reopening_does_not_leak(home):
    """The screen is cached; opening it ten times must not grow the heap."""
    gc.collect()
    before = gc.mem_free()
    for _ in range(10):
        city_picker.open(lambda city_id: None)
        for ch in "בא":
            city_picker._on_letter(ch)
        city_picker._cancel(None)
    gc.collect()
    growth = before - gc.mem_free()
    _check("reopen: ten cycles do not leak", growth < 20000,
           "{} bytes".format(growth))
    _check("reopen: back on the calling screen", lv.screen_active() is home)


def run():
    print("== UI hardware tests ==")
    print("bringing up the display")
    display.init()
    theme.load_fonts()

    test_search_agrees_with_the_host()
    home, picked = test_picker_builds_on_the_panel()
    test_typing_filters_the_slots(home, picked)
    test_choosing_returns_the_city_id(home, picked)
    test_no_city_name_overflows_its_slot()
    test_no_widget_escapes_its_parent(home)
    test_settime_still_fits_with_the_city_row(home)
    test_other_screens_stay_on_the_page(home)
    test_reopening_does_not_leak(home)

    failed = [name for name, ok, _ in _results if not ok]
    print()
    print("{} of {} passed".format(len(_results) - len(failed), len(_results)))
    if failed:
        print("FAILED: " + ", ".join(failed))
    return not failed
