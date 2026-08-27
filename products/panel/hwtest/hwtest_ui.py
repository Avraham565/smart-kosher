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
# This file runs on product A with the display up, so the rendering rules bind
# it like any other module here: no gc.collect()/gc.threshold(), no full-screen
# animation, no scrolling (CLAUDE.md). gc.mem_free() below is a read of the
# heap accounting and collects nothing -- it is the forcing that is banned.
# Nor does anything here pump LVGL: the loop owns lv.timer_handler
# (lvgl_loop.py), and geometry questions are answered by update_layout(), which
# recalculates without drawing.
#
# Usage (from the host):  python products/panel/host/run_hwtest_ui.py

import gc

import lvgl as lv

import city_picker
import display
import theme
from smart_kosher.data import load_cities, search_cities

# What is NOT here any more: the per-gang state checks and the pairing-window
# check moved to tests/test_panel_state_layer.py, because they never needed a
# board -- they seed dicts and read a return value. Two suites asserting the
# same thing drift apart, so they were moved rather than copied. What belongs
# here is what only a board can answer: real screens, real coordinates, real
# widget counts.

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


def _content_overflow(container):
    """How far a container's children reach past its own content box, in px.

    _escapes asks a question about the glass; this asks about the box, and the
    two are not the same. A list row that overflows its container but still
    lands on the panel is drawn over whatever sits below it -- the pager bar,
    the add button -- and is unreachable behind them. Nothing leaves the 800x480
    and nothing complains.

    That gap is not hypothetical. Measuring capacity with _escapes alone
    reported five rows for all three list pages, which have different row
    heights and different furniture below them: the number was the height of
    the panel, not the height of the list.

    Relative coordinates on purpose, unlike _box. Inside one flex container
    laid out in a column, a child's y is its position in that flow, which is
    exactly the frame this question lives in.
    """
    container.update_layout()
    bottom = 0
    for index in range(container.get_child_count()):
        child = container.get_child(index)
        if child.has_flag(lv.obj.FLAG.HIDDEN):
            continue
        end = child.get_y() + child.get_height()
        if end > bottom:
            bottom = end
    over = bottom - container.get_content_height()
    return over if over > 0 else 0


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
    """Not only the screens this change touched -- and then delete it.

    The zmanim page is here because it lost a row in the same work -- it was
    laid out as nineteen static entries in two columns, and it is now eighteen.
    A page that is one row short is harmless; one row long is invisible.

    It is also the densest binder in the product (nineteen effects on one
    Signal), which makes it the sharpest test that a screen can now be torn
    down and deleted without leaving any of them behind.
    """
    import store
    import zmanim_page

    settled = len(store.today._observers)
    screen = zmanim_page.build()
    lv.screen_load(screen)
    screen.update_layout()
    escaped = _escapes(screen)
    _check("overflow: zmanim page stays on screen", not escaped,
           str(escaped[:3]))

    lv.screen_load(home)

    # The delete this test used to forbid, and it is the better test of the two.
    #
    # It took both halves. shell.sub_page hands its corner clock to a list the
    # page owns, and zmanim_page keeps the nineteen bindings its own rows make
    # -- a bound effect is owned by the Signal it read (store.today, store.now),
    # not by the widget, so an effect whose handle was dropped could never be
    # unsubscribed. Twenty of them held set_text on labels this delete frees.
    zmanim_page._teardown()
    screen.delete()
    after = len(store.today._observers)
    _check("teardown: the zmanim page releases all its bindings",
           after == settled, "{} -> {}".format(settled, after))

    # The date rollover that used to land on freed memory. Any dict != None
    # notifies, and every one of the twenty would call set_text from here.
    store.today.set({})
    store.today.set(None)
    _check("teardown: a date write after the delete is survivable", True,
           "{} observers fired".format(after))


def test_the_wizard_stays_on_the_glass(home):
    """Every step of the add-schedule wizard, with a house too big for it.

    The wizard is the one screen whose layout depends on two lists at once:
    the room chips wrap, and the device grid sits under whatever height they
    took. Left alone, adding rooms pushed the grid down rather than making it
    scroll, so the last devices went under the edge -- and this is the screen
    where losing an item means the schedule cannot be built at all.

    Driven through _goto rather than by tapping, for the same reason the picker
    is: what is being measured is the layout, and a synthetic touch would be
    measuring LVGL's hit-testing instead.
    """
    import schedule_add
    import store

    store.zones.set([{"id": "z{}".format(i),
                      "name": "חדר ארוך במיוחד {}".format(i)}
                     for i in range(12)])
    store.endpoints.set(
        [{"id": "e{}".format(i), "name": "מכשיר עם שם ארוך {}".format(i),
          "zone_id": "z0", "ieee_address": "00:{:02d}".format(i)}
         for i in range(30)])
    store.groups.set([{"id": "g{}".format(i), "name": "קבוצה {}".format(i)}
                      for i in range(5)])

    schedule_add.open()
    screen = schedule_add._screen
    _check("wizard: the screen builds", screen is not None)

    def _wizard_problems():
        screen.update_layout()
        problems = _escapes(screen)
        # The grid too, not only the glass: its rows overflowing their own box
        # are drawn behind the pager bar, which _escapes cannot see. The three
        # list pages measured five rows each on the strength of that blind
        # spot before it was closed.
        grid = schedule_add._grid_obj
        over = _content_overflow(grid) if grid is not None else 0
        if over:
            problems = problems + ["grid overflows its box by {}px".format(over)]
        return problems

    for step in sorted(schedule_add._RENDERERS):
        schedule_add._goto(step)
        problems = _wizard_problems()
        _check("wizard: {} step stays on screen".format(step),
               not problems, str(problems[:2]))

    # The two paged steps, on their last page -- where a partial page is drawn
    # and the arithmetic is easiest to get wrong.
    for step, per_page, total in (("target", schedule_add.TARGETS_PER_PAGE, 35),
                                  ("zman", schedule_add.ZMANIM_PER_PAGE, 18)):
        schedule_add._goto(step)
        for _ in range(total // per_page + 1):
            schedule_add._turn_grid(1)
            problems = _wizard_problems()
            if problems:
                break
        _check("wizard: {} step stays on screen on every page".format(step),
               not problems, str(problems[:2]))

    # The room filter with more rooms than its reserved block holds: the chip
    # that pages them must not push the grid down.
    schedule_add._goto("target")
    for _ in range(3):
        schedule_add._turn_tags()
        problems = _wizard_problems()
        if problems:
            break
    _check("wizard: room filter paging keeps the grid on screen",
           not problems, str(problems[:2]))

    store.zones.set([])
    store.endpoints.set([])
    store.groups.set([])
    lv.screen_load(home)


def test_deleting_a_sub_page_releases_its_clock(home):
    """Open a sub-page, delete it, then tick the clock -- the deletion is the test.

    This is routine navigation on the wall panel: leave one room for another and
    the page you left is deleted. Its corner clock was built by shell.sub_page,
    which used to drop the effect's only handle on the floor; the Signal keeps
    the effect subscribed forever, so the deleted screen's label stayed
    reachable from store.now and the next minute wrote set_text into freed
    memory. A native fault, which reactive's `except Exception` cannot contain.

    zone_picker is the page under test because it is the one that had no effect
    list at all, and because it needs no brain: it reads store.zones and builds.

    Two independent assertions, because either alone would pass on a bug. The
    observer count catches the leak deterministically and would fail on the host
    too. The store.now write is the part only the board can answer: with orphans
    subscribed, every one of them fires here, and reaching the line after it is
    the pass.
    """
    import store
    import zone_picker

    zone_picker.open(lambda zone_id: None)
    zone_picker._back()
    settled = len(store.now._observers)      # one live picker screen, one clock

    for _ in range(5):
        zone_picker.open(lambda zone_id: None)   # deletes the previous screen
        zone_picker._back()

    after = len(store.now._observers)
    _check("teardown: five reopens leave no orphan clock effect",
           after == settled, "{} -> {}".format(settled, after))

    store.now.set((23, 59))
    store.now.set(None)
    _check("teardown: a clock tick after the deletes is survivable", True,
           "{} observers fired".format(after))
    _check("teardown: back on the calling screen", lv.screen_active() is home)


MIN_USABLE_PER_PAGE = 3


def _measure(case, count, home):
    """Seed ``count`` items, build the page, and answer (fits, escaped).

    _escapes walks absolute screen coordinates, so a widget drawn under the
    edge of the glass is caught even though LVGL clips it in silence.

    Disposal is per case rather than a plain delete(). room_page.open() already
    deletes the screen it replaces, so deleting it here too would be a double
    free -- and the pages that *are* cached in the product (rooms, schedules)
    have to be torn down before their screen goes, or the effects they built
    outlive it. Both are the same lesson from a different angle.
    """
    _, build, seed, _, _, dispose, container = case
    seed(count)
    screen = build()
    lv.screen_load(screen)
    screen.update_layout()
    problems = _escapes(screen)
    over = _content_overflow(container())
    if over:
        problems = problems + ["list overflows its box by {}px".format(over)]
    lv.screen_load(home)
    dispose(screen)
    return not problems, problems


# Walking past this many rows means the page is not paging at all, not that the
# glass is enormous: the shortest row in the product is 64px in a 416px body.
_CAPACITY_CEILING = 16


def _capacity(case, home):
    """The largest number of rows that fits, measured with paging turned off.

    Paging has to be off, or this measures nothing. With it on, seeding more
    items just draws the same page again, no widget ever leaves the glass, and
    the walk returns its own upper bound. The first hardware run of this test
    did exactly that: it reported twice the declared number for all three
    pages, 4->8, 3->6, 4->8, which is too tidy to be a measurement of anything.
    """
    _, _, _, module, attr, _, _ = case
    declared = getattr(module, attr)
    setattr(module, attr, 10 ** 6)          # one page, however long the list
    try:
        found = 0
        for count in range(1, _CAPACITY_CEILING + 1):
            fits, _ = _measure(case, count, home)
            if not fits:
                break
            found = count
    finally:
        setattr(module, attr, declared)
    return found


def test_lists_never_overflow_the_glass(home):
    """The three pages that grow with use, measured on the panel.

    This is the test the paging work was written against, and it is the
    authority on the numbers: the pixel budgets in those three docstrings are
    arithmetic, and arithmetic does not know what the font metrics do to a row.
    If a constant here is wrong the page silently loses its last item, which is
    a schedule the user cannot delete while it goes on firing.

    Two questions per page. Does a full page fit -- which is the constant being
    correct. And what is the real capacity -- which is whether the constant is
    leaving a whole row of glass unused.

    Nothing is written to /data: each page is seeded by writing its store
    Signal directly, which is the same path the brain's poll uses.
    """
    import room_page
    import rooms_page
    import schedules_page
    import store

    def seed_zones(count):
        store.endpoints.set([])
        store.zones.set([{"id": "z{}".format(i), "name": "חדר מספר {}".format(i)}
                         for i in range(count)])

    def seed_devices(count):
        store.zones.set([{"id": "z0", "name": "סלון"}])
        store.endpoints.set(
            [{"id": "e{}".format(i), "name": "מכשיר מספר {}".format(i),
              "zone_id": "z0", "ieee_address": "00:{:02d}".format(i)}
             for i in range(count)])

    def seed_schedules(count):
        # The longest description the wizard can produce: a named target, a
        # zman with an offset, and a weekday list. Layout is decided by the
        # widest row, not the average one.
        store.endpoints.set([{"id": "e0", "name": "מנורת הסלון הגדולה",
                              "zone_id": "z0", "ieee_address": "00:00"}])
        store.schedules.set(
            [{"id": "s{}".format(i), "enabled": True, "action_type": "on",
              "target_type": "endpoint", "target_id": "e0",
              "trigger_type": "zman_offset",
              "trigger_data": {"zman": "tset_hakohavim", "offset": -20},
              "recurrence_type": "days_of_week",
              "recurrence_data": {"days": [0, 1, 2, 3, 4]}}
             for i in range(count)])

    def build_room():
        room_page.open("z0", "סלון")
        return room_page._screen

    def kept(screen):
        # room_page.open() deletes the screen it replaces; deleting it here
        # would be the second free of the same object.
        pass

    # The per-page constant is carried as (module, attribute) rather than as a
    # value, so _capacity can turn paging off to measure underneath it.
    cases = (
        ("rooms", rooms_page.build, seed_zones, rooms_page, "ROOMS_PER_PAGE",
         lambda screen: (rooms_page._teardown(), screen.delete()),
         lambda: rooms_page._list),
        ("devices", build_room, seed_devices, room_page, "DEVICES_PER_PAGE",
         kept, lambda: room_page._list),
        ("schedules", schedules_page.build, seed_schedules, schedules_page,
         "SCHEDULES_PER_PAGE",
         lambda screen: (schedules_page._teardown(), screen.delete()),
         lambda: schedules_page._list),
    )

    for case in cases:
        name, _, _, module, attr, _, _ = case
        declared = getattr(module, attr)

        # A full page must fit. This is the constant being right.
        fits, escaped = _measure(case, declared, home)
        _check("paging: {} fits {} per page".format(name, declared),
               fits, str(escaped[:2]))

        # And a list five times longer must still fit, which is what proves the
        # pager is slicing rather than the list happening to be short.
        fits, escaped = _measure(case, declared * 5, home)
        _check("paging: {} stays on one page at {} items".format(
            name, declared * 5), fits, str(escaped[:2]))

        measured = _capacity(case, home)
        _check("paging: {} constant is within the real capacity".format(name),
               declared <= measured,
               "declared {}, measured {}".format(declared, measured))
        _check("paging: {} constant is not leaving a row unused".format(name),
               measured <= declared,
               "declared {} but {} fit -- raise the constant".format(
                   declared, measured))

        # A product question, not a layout one: at one or two items a page the
        # pager costs more than it returns, and the card height wants rethinking
        # before this ships.
        _check("paging: {} page holds enough to be usable".format(name),
               measured >= MIN_USABLE_PER_PAGE,
               "only {} fit -- reconsider the card height".format(measured))

    seed_zones(0)
    seed_schedules(0)
    store.endpoints.set([])
    lv.screen_load(home)


def _tree_size(obj):
    """Widgets in the subtree, obj included."""
    total = 1
    for index in range(obj.get_child_count()):
        total += _tree_size(obj.get_child(index))
    return total


def test_reopening_does_not_leak(home):
    """The screen is cached: ten opens must reuse one tree, not build ten.

    Counted in widgets, not bytes. This used to bracket the loop with
    gc.collect() + gc.mem_free(), and a forced collect is exactly what this
    product forbids once rendering has started -- it can free a partial draw
    buffer that core 0 is still scanning out, which is the LoadProhibited boot
    loop (CLAUDE.md, memory panel-mp-rendering). The suite was the only place on
    product A still doing it.

    Losing nothing, either: the heap reading was noise. A passing run reported
    "-144 bytes" -- a negative leak -- because mem_free() on this board answers
    for a PSRAM heap the picker is a rounding error against. What a rebuilt
    screen actually costs is widgets, and the tree can be walked exactly.
    """
    first = city_picker._screen
    before = _tree_size(first)
    for _ in range(10):
        city_picker.open(lambda city_id: None)
        for ch in "בא":
            city_picker._on_letter(ch)
        city_picker._cancel(None)

    # Identity and size are two different failures, and neither implies the
    # other: a rebuilt screen is a *new* object with the *same* widget count, so
    # counting alone would call it clean.
    _check("reopen: the screen is still the cached one",
           city_picker._screen is first)
    after = _tree_size(city_picker._screen)
    _check("reopen: ten cycles add no widgets", after == before,
           "{} -> {}".format(before, after))
    _check("reopen: back on the calling screen", lv.screen_active() is home)


# ── add-device list: one row per gang ────────────────────────────────────────

def _dev(endpoints, onoff, on_off=None):
    clusters = {}
    for ep in endpoints:
        clusters[str(ep)] = [0, 3, 6] if ep in onoff else [0, 3]
    return {"on_off": on_off, "unreachable": False, "endpoint": endpoints[0],
            "endpoints": endpoints, "clusters": clusters}


def test_add_device_rows():
    import add_device_page
    import store
    IEEE = "70:d0:7e:ff:fe:6e:c6:40"
    ACT = "78:1c:9d:ff:fe:12:76:fa"

    store.endpoints.set([])
    store.devices.set({IEEE: _dev([1, 2], [1, 2])})
    ready, pending = add_device_page.rows()
    _check("add: a two-gang switch offers two rows",
           [x["endpoint"] for x in ready] == [1, 2], str(ready))
    _check("add: nothing pending once clusters are known", pending == [])

    # Adopting gang 1 must not take gang 2 off the list. Written by ieee alone
    # this is where gang 2 vanishes.
    store.endpoints.set([{"ieee_address": IEEE, "zigbee_endpoint": 1}])
    ready, _ = add_device_page.rows()
    _check("add: gang 2 survives gang 1 being adopted",
           [x["endpoint"] for x in ready] == [2], str(ready))

    # Green Power is an endpoint, not a gang.
    store.endpoints.set([])
    store.devices.set({ACT: _dev([1, 242], [1])})
    ready, _ = add_device_page.rows()
    _check("add: endpoint 242 is not offered as a gang",
           [x["endpoint"] for x in ready] == [1], str(ready))

    # Three gangs, no new code.
    store.devices.set({IEEE: _dev([1, 2, 3], [1, 2, 3])})
    ready, _ = add_device_page.rows()
    _check("add: a three-gang switch offers three rows",
           [x["endpoint"] for x in ready] == [1, 2, 3], str(ready))

    # Discovery not finished: shown as pending, never as a single gang.
    store.devices.set({IEEE: {"on_off": None, "unreachable": False,
                              "endpoint": 1, "endpoints": None,
                              "clusters": None}})
    ready, pending = add_device_page.rows()
    _check("add: a freshly joined device is pending, not one gang",
           ready == [] and pending == [IEEE], "{} {}".format(ready, pending))

    store.devices.set({IEEE: {"on_off": None, "unreachable": False,
                              "endpoint": 1, "endpoints": [1, 2],
                              "clusters": {"1": [0, 3, 6]}}})
    ready, pending = add_device_page.rows()
    _check("add: half-discovered is still pending",
           ready == [] and pending == [IEEE], "{} {}".format(ready, pending))
    store.devices.set({})
    store.endpoints.set([])



def _glyph_probe():
    """(call_shape, fn) for asking a font whether it has a codepoint.

    Discovered rather than assumed: a first attempt guessed
    font.get_glyph_dsc(dsc, cp, 0) and every call raised "takes 4 positional
    arguments but 3 were given" -- which, had it printed a bool instead of the
    exception, would have read as "every glyph is missing" and been wrong in
    the most convincing way.
    """
    dsc = lv.font_glyph_dsc_t()
    shapes = (
        ("font.get_glyph_dsc(dsc, cp, 0)",
         lambda font, cp: font.get_glyph_dsc(dsc, cp, 0)),
        ("font.get_glyph_dsc(font, dsc, cp, 0)",
         lambda font, cp: font.get_glyph_dsc(font, dsc, cp, 0)),
        ("lv.font_get_glyph_dsc(font, dsc, cp, 0)",
         lambda font, cp: lv.font_get_glyph_dsc(font, dsc, cp, 0)),
    )
    for name, fn in shapes:
        try:
            fn(theme.FONTS.body, 0x0041)      # "A" must exist in any font
            return name, fn
        except Exception:
            continue
    return None, None


# 32 modules ship in products/panel/device today. The floor is deliberately
# well under that: it is here to catch a walk that collapsed, not to notice
# somebody deleting a page.
_MIN_REACHABLE = 20


def _reachable_modules():
    """Module names the product actually loads, walked from main.

    The board's filesystem is not the product. house_page.py was deleted from
    git on 2026-08-02 and is still sitting on the flash at the same 5308 bytes,
    because deploy copies files and never prunes them. Scanning "/" therefore
    reports characters from code that no longer runs, and the first widened
    version of this check failed on an ellipsis in exactly that orphan.

    Walking imports from main means the answer tracks what is rendered rather
    than what the flash has accumulated, so the check does not quietly become a
    filesystem-hygiene test.
    """
    import os
    have = set()
    for name in os.listdir("/"):
        if name.endswith(".py"):
            have.add(name[:-3])
    seen = set()
    # main_src is the copy the runner stashes: clean_board deletes main.py
    # before the suite starts, so on a live run "main" is the name that is not
    # there. Both are listed because the suite is also runnable by hand on a
    # board that still has its main.py.
    queue = ["main", "main_src"]
    while queue:
        module = queue.pop()
        if module in seen or module not in have:
            continue
        seen.add(module)
        try:
            source = open("/" + module + ".py", encoding="utf-8").read()
        except Exception:
            continue
        for line in source.splitlines():
            stripped = line.strip()
            name = None
            if stripped.startswith("import "):
                name = stripped[7:].split()[0].split(",")[0].split(".")[0]
            elif stripped.startswith("from "):
                name = stripped[5:].split()[0].split(".")[0]
            if name and name in have:
                queue.append(name)
    return seen


def _drawn_codepoints():
    """Every non-ASCII, non-Hebrew codepoint in a string literal the panel runs.

    Derived from the source rather than kept by hand. A hand-kept list ages:
    someone adds an arrow next month and the list does not know, which is the
    difference between "we fixed five characters" and "this cannot happen
    again".

    Comments and docstrings are stripped, and then the rule that makes this
    sound: outside them, Python source is ASCII except inside string literals,
    because identifiers and syntax are. So whatever non-ASCII survives the
    strip is text, and text on this panel is text that gets drawn.

    A narrower first attempt matched only lines containing w_label or set_text
    and reported one codepoint for the whole product. Most drawn text is built
    in a helper and handed to a binding, so that filter would have caught two
    of the five characters this task removed -- it was measuring its own
    narrowness, not the code.

    Stripping comments is what keeps the box-drawing out: U+2500 appears in
    section rules and is never rendered, and a check with hundreds of false
    positives is one people learn to skip.
    """
    triple_d = chr(34) * 3
    triple_s = chr(39) * 3
    found = {}
    reached = _reachable_modules()
    for module in reached:
        try:
            source = open("/" + module + ".py", encoding="utf-8").read()
        except Exception:
            continue
        in_doc = False
        for line in source.splitlines():
            marks = line.count(triple_d) + line.count(triple_s)
            if in_doc:
                if marks:
                    in_doc = False
                continue
            if marks % 2:
                in_doc = True
                continue
            if line.strip().startswith("#"):
                continue
            for ch in line:
                cp = ord(ch)
                if cp < 0x7F or 0x0590 <= cp <= 0x05FF:
                    continue
                found.setdefault(cp, module + ".py")
    return found, reached


def test_font_glyph_coverage():
    """No codepoint the UI draws may be missing from the font that draws it.

    The icons that rendered as boxes were not LV_SYMBOL -- they were
    typographic characters, and theme.py describes the .bin files as
    "Hebrew-ranged" without anything checking what that range holds. load_fonts
    asks only whether the font object is not None.
    """
    shape, ask = _glyph_probe()
    if not _check("font: glyph coverage can be queried at all", ask is not None,
                  "no call shape worked"):
        return
    print("  note  glyph query: {}".format(shape))

    fonts = (("small", theme.FONTS.small), ("body", theme.FONTS.body),
             ("title", theme.FONTS.title), ("h1", theme.FONTS.h1),
             ("clock", theme.FONTS.clock))
    # The control row: if these ever fail the query is broken, not the fonts.
    for name, cp in (("A", 0x0041), ("alef", 0x05D0), ("hyphen", 0x002D)):
        _check("font: control glyph {} present".format(name),
               all(ask(font, cp) for _n, font in fonts))

    # The scan below ignores everything under 0x7F, because outside comments
    # the ASCII in a source file is mostly syntax rather than text. That makes
    # it blind to exactly the characters this fix chose as replacements -- the
    # dots became "|", the chevrons became ">" and "<". Measured once and
    # present in all five fonts, but a font rebuild is its own open task, and
    # the day it drops one of these the boxes come back with the scan silent.
    substitutes = "|><+/."
    absent = [c for c in substitutes
              if not all(ask(font, ord(c)) for _n, font in fonts)]
    _check("font: the ASCII the fix substituted in is present",
           not absent, "missing: {}".format("".join(absent)))

    missing = []
    drawn, reached = _drawn_codepoints()
    # The scan is only worth reading if it saw the product. Its first version
    # reached zero modules -- the runner had deleted the main.py it walks from
    # -- and reported "every drawn codepoint exists" over an empty set. A check
    # that passes loudest when it measured nothing is worse than no check, so
    # too few modules is a failure, not a quiet pass.
    if not _check("font: the codepoint scan can see the product",
                  len(reached) >= _MIN_REACHABLE,
                  "reached {} modules, expected at least {}".format(
                      len(reached), _MIN_REACHABLE)):
        return
    for cp in sorted(drawn):
        absent = [n for n, font in fonts if not ask(font, cp)]
        if absent:
            missing.append("{:#06x} in {} (missing from {})".format(
                cp, drawn[cp], ",".join(absent)))
    _check("font: every drawn codepoint exists in the Assistant fonts",
           not missing, "; ".join(missing[:4]))
    # The module count is printed because a collapse in coverage is what
    # this check's first version actually suffered: it reported one
    # codepoint for the whole product and passed. A reader who sees the
    # reachable count drop knows the instrument moved, not the code.
    print("  note  {} modules reachable from main, {} non-ASCII drawn "
          "codepoints".format(len(reached), len(drawn)))


def test_a_device_row_stays_tappable():
    """The row height is derived now, so it can shrink without anyone typing it.

    Capacity became the input and height the output, which is what stops the
    page leaving a quarter of itself empty -- and it also means raising
    DEVICES_PER_PAGE silently makes every row shorter. Six rows still fit in
    the 264px the list has (37px each, 262 total), so every paging check here
    would pass while the rows became too small to hit.

    theme.TAP_MIN is the minimum touch target the theme declares, and it is
    the thing the derivation can quietly cross.
    """
    import room_page

    _check("paging: a device row is still a touch target",
           room_page.ROW_H >= theme.TAP_MIN,
           "row is {}px, tap minimum is {}px".format(
               room_page.ROW_H, theme.TAP_MIN))
    _check("paging: the rows fill the list they were derived from",
           room_page.ROW_H * room_page.DEVICES_PER_PAGE
           + (room_page.DEVICES_PER_PAGE - 1) * room_page._LIST_GAP
           <= room_page.LIST_H,
           "rows need more than the {}px the list has".format(room_page.LIST_H))


def test_text_input_has_a_cursor(home):
    """You must be able to see where the next letter lands.

    The field was a label, and a label has no cursor and cannot be given one --
    the gap was structural, not a missing style. So the check is structural
    too: type three letters and ask the widget where its cursor is. A label
    cannot answer that question at all.

    The scrollable flag is checked in the same breath because it is what the
    textarea costs: the panel has no scrollbars and the RGB driver forbids
    scrolling, so a field that brought its own would be trading one defect for
    a worse one.
    """
    import text_input

    text_input.open("שם", "", lambda _t: None)
    field = text_input._field

    for letter in ("א", "ב", "ג"):
        text_input._on_letter(letter)

    where = None
    try:
        where = field.get_cursor_pos()
    except Exception as exc:
        where = "no cursor: {}".format(exc)
    _check("cursor: it sits after the three letters typed", where == 3,
           "cursor reports {}".format(where))

    _check("cursor: the field brought no scrolling with it",
           not field.has_flag(lv.obj.FLAG.SCROLLABLE))

    lv.screen_load(home)


def test_text_input_offers_digits_and_stays_on_the_glass(home):
    """The rename screen must be able to type the names we generate.

    This file's own header has claimed since it was written that the suite
    proves "four result slots plus a 27-key Hebrew keyboard ... fits in 800x480"
    -- and nothing in it ever built the keyboard. The claim was true of the city
    picker's slots and imagined about the keyboard, which is how a fourth key
    row could be added with no guard at all.

    Two things are checked, and the second is the one that costs. Digits are
    the fix; the height is what the fix risks, because the keyboard is the
    tallest thing on the panel and a row is 46px on a 480px glass.
    """
    import text_input

    text_input.open("שם", "", lambda _t: None)
    screen = text_input._screen
    screen.update_layout()

    keys = []

    def walk(obj):
        for index in range(obj.get_child_count()):
            child = obj.get_child(index)
            try:
                keys.append(child.get_text())
            except Exception:
                pass
            walk(child)

    walk(screen)
    digits = [d for d in "1234567890" if d in keys]
    _check("keyboard: every digit is typeable", len(digits) == 10,
           "found {} of 10: {}".format(len(digits), digits))
    _check("keyboard: the letters are still there",
           "ק" in keys and "ץ" in keys)

    escaped = _escapes(screen)
    _check("overflow: the text input stays on screen", not escaped,
           str(escaped[:3]))

    lv.screen_load(home)


def test_add_device_page_stays_on_the_glass(home):
    """The add screen was never in this list, and three layout tasks follow.

    Its rows carry three buttons now, and 38 may swap the typographic
    characters for wider Hebrew words while 41 changes row heights -- all on
    this page. Three layout changes in a row verified by looking is how a
    silent overflow ships: the panel has no scrollbars, so anything past the
    edge is simply lost and nothing complains.
    """
    import add_device_page
    import store
    IEEE = "70:d0:7e:ff:fe:6e:c6:40"
    ACT = "78:1c:9d:ff:fe:12:76:fa"

    # A two-gang device (two rows), a single-gang one, one still being
    # identified, and one carrying the failed-removal label -- the longest
    # text this page can put on a row.
    store.endpoints.set([])
    store.devices.set({
        IEEE: {"endpoints": [1, 2], "clusters": {"1": [0, 3, 6], "2": [0, 3, 6]},
               "leave_failed": "no_response"},
        ACT: {"endpoints": [1, 242], "clusters": {"1": [0, 3, 6], "242": []}},
        "b0:e8:e8:ff:fe:66:82:bd": {"endpoints": None, "clusters": None},
    })
    screen = add_device_page._build()
    lv.screen_load(screen)
    screen.update_layout()
    escaped = _escapes(screen)
    _check("overflow: add-device page stays on screen", not escaped,
           str(escaped[:3]))

    lv.screen_load(home)
    screen.delete()
    store.devices.set({})
    store.endpoints.set([])



def _probe_ruler(parent, ink):
    """A scale down the left edge, so a stripe's height can be READ.

    The eye is the instrument in this probe, and an instrument without a scale
    returns "a few stripes, fairly thin". Ticks sit every 48px because that is
    the panel's partial draw buffer: display.py leaves frame_buffer1/2 unset,
    the driver allocates ~1/10-screen buffers, and 1/10 of 800x480 as full
    width lines is exactly 48 rows.

    That number is the whole reason the ruler is here. If a stripe measures 48
    or 96, geometry is back in play whatever its position; if the heights come
    out arbitrary, the buffer is not what decides them.
    """
    from widgets import w_label

    column = lv.obj(parent)
    column.set_size(58, SCREEN_H)
    column.set_pos(0, 0)
    column.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    column.set_style_border_width(0, lv.PART.MAIN)
    column.set_style_pad_all(0, lv.PART.MAIN)
    column.remove_flag(lv.obj.FLAG.SCROLLABLE)
    for y in range(0, SCREEN_H, 48):
        tick = lv.obj(column)
        tick.set_size(16, 2)
        tick.set_pos(0, y)
        tick.set_style_bg_color(ink, lv.PART.MAIN)
        tick.set_style_border_width(0, lv.PART.MAIN)
        tick.remove_flag(lv.obj.FLAG.SCROLLABLE)
        mark = w_label(column, theme.FONTS.small, ink, str(y))
        mark.set_pos(20, y - 8)
    return column


def _probe_screen(name, bg, ink, card):
    """One screen loaded like a real page: header, four rows, a bottom bar.

    An empty screen would prove nothing -- 115ms of drawing is what makes a
    transition non-atomic, and an empty screen does not spend it. The two
    screens are built in maximum contrast (near-black against near-white) for
    one reason: a leftover band from the other one has to be unmistakable
    rather than a shade someone could talk themselves into.
    """
    from widgets import w_label

    scr = lv.obj(None)
    scr.set_style_bg_color(bg, lv.PART.MAIN)
    scr.set_style_pad_all(0, lv.PART.MAIN)
    scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

    _probe_ruler(scr, ink)

    head = lv.obj(scr)
    head.set_size(SCREEN_W - 64, 64)
    head.set_pos(64, 0)
    head.set_style_bg_color(card, lv.PART.MAIN)
    head.set_style_border_width(0, lv.PART.MAIN)
    head.remove_flag(lv.obj.FLAG.SCROLLABLE)
    counter = w_label(head, theme.FONTS.title, ink, name)
    counter.align(lv.ALIGN.RIGHT_MID, -12, 0)

    for row in range(4):
        card_obj = lv.obj(scr)
        card_obj.set_size(SCREEN_W - 220, 60)
        card_obj.set_pos(180, 80 + row * 68)
        card_obj.set_style_bg_color(card, lv.PART.MAIN)
        card_obj.set_style_border_width(0, lv.PART.MAIN)
        card_obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
        w_label(card_obj, theme.FONTS.body, ink,
                "{} {}".format(name, row + 1)).align(lv.ALIGN.RIGHT_MID, 0, 0)

        state = lv.obj(scr)
        state.set_size(110, 60)
        state.set_pos(64, 80 + row * 68)
        state.set_style_bg_color(ink, lv.PART.MAIN)
        state.set_style_border_width(0, lv.PART.MAIN)
        state.remove_flag(lv.obj.FLAG.SCROLLABLE)
        w_label(state, theme.FONTS.body, bg, "on/off").center()

    bar = lv.obj(scr)
    bar.set_size(SCREEN_W - 64, 52)
    bar.set_pos(64, SCREEN_H - 52)
    bar.set_style_bg_color(card, lv.PART.MAIN)
    bar.set_style_border_width(0, lv.PART.MAIN)
    bar.remove_flag(lv.obj.FLAG.SCROLLABLE)
    w_label(bar, theme.FONTS.body, ink, name).center()
    return scr, counter


def probe_screen_transition_striping(swaps=20, hold_ms=1500, invalidate=0):
    """Swap between two loaded screens while nothing else runs. A person watches.

    This exists because the measurement that closed task 42 answered a question
    nobody asked. 114.8ms of full repaint against a 22.8ms frame period proves
    a transition cannot be atomic -- true, and no explanation at all for bands
    that STAY on the glass after the transition ends. A tear is gone in the
    next frame. A residue is not.

    What points away from geometry is where the bands appear: they have no
    fixed position. Buffer boundaries are geometry and would put them at the
    same heights every time. A position that moves points at timing, and this
    panel runs LVGL, the brain and the scheduler on one cooperative asyncio
    loop -- brain.create blocks 840ms, a registry save ~350ms, a join burst
    1.75s, and main.py's own comment puts ~89ms as the point where arriving
    frames start being dropped. The device poll runs every three seconds
    against a 115ms repaint.

    So this is the separating experiment, and it separates by SUBTRACTION: the
    runner deletes main.py before the suite starts, which means that while this
    probe runs there is no brain, no poll and no scheduler at all. Nothing on
    this board can interrupt a transition except LVGL itself.

      no bands here  -> the drawing is fine on its own and something else was
                        interrupting it. The fix is about what runs during a
                        transition, not about how the transition is drawn.
      bands here     -> it is in the drawing, and invalidation comes back into
                        play. The follow-up is `invalidate` 1 then 2: with two
                        framebuffers a single invalidate only lands on
                        alternating swaps, so "1 fixes half, 2 fixes all" is a
                        signature, not a coincidence.

    Nothing is printed between the swaps, deliberately. Console traffic over
    the serial link during a transition is exactly the kind of interruption
    under test, and an instrument that perturbs what it measures answers about
    itself. The swap number is on the SCREEN instead, so what the watcher
    reports can be matched to the timings printed at the end.

    Timing is collected per swap so an eye-report becomes data: if the swaps
    that showed bands are also the slow ones, that is the collision hypothesis
    with a number attached.
    """
    import time

    # run() does these two lines before anything else, and this probe did not.
    # Without them LVGL has no display registered, so the panel stays black and
    # screen_load blocks -- which is exactly what happened twice: no rendering,
    # mpremote waiting on a raw REPL that never answers, and an orphaned
    # process holding the port with main.py still deleted. The symptom looked
    # like a wedged board and was a missing initialiser.
    display.init()
    theme.load_fonts()

    print("== striping probe: {} swaps, {}ms apart ==".format(swaps, hold_ms))
    print("   quiet board: main.py is deleted by the runner, so no brain,")
    print("   no device poll and no scheduler are running.")
    if invalidate:
        print("   invalidate() called {}x after each load".format(invalidate))
    print("   WATCH THE PANEL. The swap number is in the header and the")
    print("   bottom bar; the left edge is a ruler in 48px steps.")
    print("   Starting in 3 seconds.")
    time.sleep(3)

    dark, light = lv.color_hex(0x101014), lv.color_hex(0xF2F2F0)
    a, a_counter = _probe_screen("A", dark, light, lv.color_hex(0x2A2A32))
    b, b_counter = _probe_screen("B", light, dark, lv.color_hex(0xD8D8D4))

    lv.screen_load(a)
    lv.refr_now(None)
    time.sleep_ms(hold_ms)

    times = []
    for index in range(1, swaps + 1):
        target, counter = (b, b_counter) if index % 2 else (a, a_counter)
        name = "B" if index % 2 else "A"
        counter.set_text("{}  --  swap {} / {}".format(name, index, swaps))
        start = time.ticks_us()
        lv.screen_load(target)
        for _ in range(invalidate):
            lv.screen_active().invalidate()
        lv.refr_now(None)
        times.append(time.ticks_diff(time.ticks_us(), start) / 1000.0)
        time.sleep_ms(hold_ms)

    print("")
    print("swap timings in ms, in order:")
    for index in range(0, len(times), 5):
        chunk = times[index:index + 5]
        print("  {:>2}-{:<2} {}".format(
            index + 1, index + len(chunk),
            "  ".join("{:6.1f}".format(t) for t in chunk)))
    ordered = sorted(times)
    median = ordered[len(ordered) // 2]
    print("")
    print("  fastest {:.1f}   median {:.1f}   slowest {:.1f}".format(
        ordered[0], median, ordered[-1]))
    slow = [i + 1 for i, t in enumerate(times) if t > median * 1.5]
    print("  swaps over 1.5x the median: {}".format(slow if slow else "none"))
    print("")
    print("PROBE_DONE {} swaps".format(swaps))
    print("")
    print("This exit code means the probe RAN, not that the panel is clean.")
    print("The finding is what the watcher saw: how many of the {} swaps"
          .format(swaps))
    print("left bands, and what the ruler said their height was.")



def _rgb(color):
    """(r, g, b) of an lv colour, or None if this binding will not say."""
    try:
        return color.red, color.green, color.blue
    except Exception:
        return None


def _press_reactive(root):
    """Every widget under `root` whose background changes under PRESSED.

    The card is found by what it DOES, not by where it sits in the tree.
    `scr.get_child(1).get_child(0)` names the hero today and would quietly name
    something else the day a row is inserted above it -- and a probe pointed at
    the wrong widget reports "no bands" with total confidence.

    Asking which widgets react to a press is the same question the probe is
    about, so the search doubles as the instrument check: an empty result means
    nothing on this screen responds to a press at all, and that has to stop the
    run rather than produce twenty measurements of nothing.
    """
    out = []

    def walk(obj):
        for index in range(obj.get_child_count()):
            child = obj.get_child(index)
            before = _rgb(child.get_style_bg_color(lv.PART.MAIN))
            child.add_state(lv.STATE.PRESSED)
            after = _rgb(child.get_style_bg_color(lv.PART.MAIN))
            child.remove_state(lv.STATE.PRESSED)
            if before != after:
                out.append((child, _box(child), before, after))
            walk(child)

    walk(root)
    return out


def _press_ruler(parent, box, ink, pitch=10, major=50):
    """A scale laid over the left edge of the card under test.

    47's ruler runs down the far left of the glass. It cannot serve here: this
    card starts 18px from that edge and runs 764px across, and sighting a
    band's height across three quarters of the panel is not a measurement. So
    the scale sits ON the card, which puts it inside the invalidated rectangle
    and has it redrawn with it -- the cost is that the ruler stripes too, and
    that is also the point, because a scale outside the redrawn area cannot say
    where inside it a band fell.

    Graduated in tens with a labelled tick every fifty, and the numbers are
    offsets from the top of the card, not from the top of the screen. Round
    numbers rather than the predicted seam pitch, deliberately: 50 rows is what
    a flush-chunk seam would measure here (38400px of draw buffer over a 764px
    wide area), and a ruler ruled in the prediction invites the eye to agree
    with it. That the two coincide is said out loud instead of being hidden in
    the tick spacing.
    """
    from widgets import w_label

    x1, y1, _, y2 = box
    column = lv.obj(parent)
    column.set_size(58, y2 - y1 + 1)
    column.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    column.set_style_border_width(0, lv.PART.MAIN)
    column.set_style_pad_all(0, lv.PART.MAIN)
    column.remove_flag(lv.obj.FLAG.SCROLLABLE)

    # set_pos is relative to the parent's CONTENT area, and `box` is absolute
    # screen coordinates. Rather than assume the screen has no padding -- which
    # would put every tick a few pixels off and make the scale lie by exactly
    # the amount nobody would notice -- place it at the origin, read back where
    # that landed, and correct by the difference. The caller prints tick 0's
    # absolute position against the card's, so the correction is checked rather
    # than trusted.
    column.set_pos(0, 0)
    parent.update_layout()
    origin = _box(column)
    column.set_pos(x1 - origin[0], y1 - origin[1])
    parent.update_layout()

    for y in range(0, y2 - y1 + 1, pitch):
        tick = lv.obj(column)
        tick.set_size(20 if y % major == 0 else 8, 2)
        tick.set_pos(0, y)
        tick.set_style_bg_color(ink, lv.PART.MAIN)
        tick.set_style_border_width(0, lv.PART.MAIN)
        tick.remove_flag(lv.obj.FLAG.SCROLLABLE)
        if y % major == 0:
            w_label(column, theme.FONTS.small, ink, str(y)).set_pos(24, y - 8)
    return column


def _spread(name, times):
    """Print one series of timings the way task 47 printed its swaps."""
    print("")
    print("{} in ms, in order:".format(name))
    for index in range(0, len(times), 5):
        chunk = times[index:index + 5]
        print("  {:>2}-{:<2} {}".format(
            index + 1, index + len(chunk),
            "  ".join("{:6.1f}".format(t) for t in chunk)))
    ordered = sorted(times)
    median = ordered[len(ordered) // 2]
    print("  fastest {:.1f}   median {:.1f}   slowest {:.1f}".format(
        ordered[0], median, ordered[-1]))
    slow = [i + 1 for i, t in enumerate(times) if t > median * 1.5]
    print("  over 1.5x the median: {}".format(slow if slow else "none"))


def probe_home_card_press(presses=20, hold_ms=1200, rest_ms=700,
                          single_draw_buffer=False, mode="draws"):
    """Press the real home card on a quiet board, twenty times. A person watches.

    Avraham, in passing while reading 47's result: pressing the house card on
    the main screen ALWAYS rules it with lines like a notebook page. That is a
    better lead than 42 on three counts -- it reproduces on demand rather than
    sometimes, it is one widget and one interaction with no screen change in
    it, and evenly spaced lines are geometry, where 42's bands wander.

    So this is 47's experiment aimed at 48, separating the same way, by
    subtraction: the runner has deleted main.py, so no brain, no device poll
    and no scheduler are running while the card is pressed. Nothing but LVGL
    can interrupt the redraw.

      bands here     -> the partial redraw itself produces them, on a board
                        with nothing else on it. Geometry is back, and the
                        follow-up is to vary the invalidated WIDTH: the seam
                        pitch is buffer-px over area-width, so a card half as
                        wide must double the spacing. That is a prediction the
                        eye can judge without measuring anything.
      no bands here  -> the same answer 47 got, but from a symptom that
                        reproduces every time instead of sometimes -- which
                        makes the collision hypothesis testable on demand.

    What this run subtracts BESIDES main.py, written before the result rather
    than after it, because 47 had to record exactly this against itself:

      * no real touch. The state is set from code, so the GT911 is never read
        over I2C during the redraw and no indev processing runs.
      * no click. The product's press is followed by pages.page_open, which
        builds rooms_page on the first one; none of that happens here.
      * no pump. lv.refr_now draws in one call, where the product renders from
        lvgl_loop's timer_handler in between other tasks.

    Any of those three could be the disturber. "No bands" here therefore
    clears the redraw, not the product's press.
    """
    import time

    # run() does these two first, and the probes that skipped them looked like
    # dead boards: no display registered means nothing renders and the REPL
    # never answers.
    disp = display.init(single_draw_buffer)
    theme.load_fonts()

    # Reported rather than assumed. A probe that changes a configuration and
    # does not say what the configuration ended up being leaves the reader
    # inferring it from a 3ms shift in the timings -- and the run that first
    # used this flag could only be believed that way.
    print("== LVGL draw buffers ==")
    for name in ("_frame_buffer1", "_frame_buffer2"):
        buf = getattr(disp, name, None)
        print("   {:<16} {}".format(
            name, "None" if buf is None else "{} bytes".format(len(buf))))
    print("   asked for one: {}".format(single_draw_buffer))
    print("")

    import ui_home
    from widgets import w_label

    if _rgb(lv.color_hex(0)) is None:
        print("!! this binding will not report style colours, so the card "
              "cannot be identified by behaviour. It will not be guessed at.")
        return

    # None is the brain: the home screen only passes it on to sub-screens this
    # probe never opens, and nothing here taps anything.
    ui_home.create(None)
    scr = lv.screen_active()
    scr.update_layout()

    candidates = _press_reactive(scr)
    if not candidates:
        print("!! nothing on the home screen changes colour when pressed. "
              "Either the card lost its pressed style or this binding "
              "resolves styles differently -- either way there is nothing "
              "to measure, and twenty measurements of nothing is worse.")
        return

    print("== widgets that react to a press ==")
    for _, box, before, after in candidates:
        print("   {:>4},{:<4} .. {:>4},{:<4}   {:>4}x{:<4}  {} -> {}".format(
            box[0], box[1], box[2], box[3],
            box[2] - box[0] + 1, box[3] - box[1] + 1, before, after))

    card, box, normal, pressed = max(
        candidates, key=lambda c: (c[1][2] - c[1][0]) * (c[1][3] - c[1][1]))
    width, height = box[2] - box[0] + 1, box[3] - box[1] + 1
    if width < SCREEN_W // 2:
        print("!! the widest press-reactive widget is only {}px across. The "
              "hero card spans most of the screen, so this is not it, and "
              "pressing the wrong widget would report 'no bands' with total "
              "confidence.".format(width))
        return

    ruler = _press_ruler(scr, box, theme.TEXT)
    counter = w_label(scr, theme.FONTS.body, theme.TEXT, "")
    counter.align(lv.ALIGN.TOP_MID, 0, 8)
    scr.update_layout()

    pitch = 38400 // width
    print("")
    print("== the card under test ==")
    print("   box     {},{} .. {},{}   {}x{}".format(
        box[0], box[1], box[2], box[3], width, height))
    print("   ruler   tick 0 lands at absolute y {}, card top is {}".format(
        _box(ruler)[1], box[1]))
    print("   bg      {} normal -> {} pressed".format(normal, pressed))
    print("")
    print("== written before the run ==")
    print("   redraw  {}px is {}% of the screen and 47 measured a full".format(
        width * height, 100 * width * height // (SCREEN_W * SCREEN_H)))
    print("           repaint at 111.4ms, so expect roughly 20-60ms per")
    print("           press. Over 100ms means the whole screen is being")
    print("           repainted for a press, which is a finding of its own.")
    print("           Under 5ms and uniform means nothing was drawn -- check")
    print("           the probe before believing it.")
    print("   bands   if these are seams between flushed chunks the pitch is")
    print("           {}px (38400px of draw buffer over a {}px wide area)"
          .format(pitch, width))
    print("           and there are only {} of them. Note {}, NOT the 48 on"
          .format((height - 1) // pitch, pitch))
    print("           47's ruler: 48 is the pitch of a FULL-WIDTH area.")
    print("           Many closely spaced lines are not this hypothesis.")
    print("")
    print("")
    print("== the experiment: odd presses draw once, even presses twice ==")
    print("   Avraham reports bands only on LARGE buttons, at constant")
    print("   spacing, and a line that can survive into the NEXT screen. A")
    print("   redraw cannot leave anything on a screen it did not draw, so")
    print("   the picture has to be kept in two places -- and display.py says")
    print("   it is: two full framebuffers with partial renders copied in.")
    print("   Four strips over two buffers gives each of them half the")
    print("   strips, which is bands at a constant pitch, and a small button")
    print("   fits in one strip, which is why it never shows them.")
    print("")
    print("   Drawing the same area twice puts it in BOTH buffers. So:")
    print("     even presses clean, odd ones banded -> two buffers, and the")
    print("       fix is decided by measurement rather than guessed at.")
    print("     both banded -> the story is wrong and nothing was touched.")
    print("")
    print("   The instrument check is in the timings: a DOUBLE press must")
    print("   cost about twice a single one. If the two come out equal, the")
    print("   second pass drew nothing and this run means nothing -- read")
    print("   that before reading the panel.")
    if mode == "width":
        print("")
        print("== THIS RUN VARIES THE WIDTH, NOT THE NUMBER OF DRAWS ==")
        print("   Both variants draw exactly once. Odd presses use the card")
        print("   at its full {}px; even presses halve it to {}px.".format(
            width, width // 2))
        print("")
        print("   If bands are seams between flushed strips, the pitch is")
        print("   38400 / area width, so:")
        print("     {:>4}px wide -> {:>3} row strips -> {} seams".format(
            width, 38400 // width, (height - 1) // (38400 // width)))
        print("     {:>4}px wide -> {:>3} row strips -> {} seams".format(
            width // 2, 38400 // (width // 2),
            (height - 1) // (38400 // (width // 2))))
        print("")
        print("   So the narrow card must show FEWER bands, FURTHER apart.")
        print("   Same count and same spacing on both means the pitch does")
        print("   not come from the strips at all, and the whole flush-seam")
        print("   story is out -- which is the cheap answer this should have")
        print("   been asked for before any firmware was built.")

    print("")
    print("   WATCH THE PANEL. The press number is at the top and says which")
    print("   kind it is; the scale down the card's left edge is in 10px")
    print("   steps, labelled every 50.")
    print("   Starting in 3 seconds.")
    # The cold first paint happens here, outside the loop and outside the
    # clock. In 47 it landed on swap 1 and showed up as a 151ms outlier among
    # 111s; here press 1 is a press like the other nineteen, and the watcher
    # sees the home screen through the countdown instead of a blank panel.
    lv.refr_now(None)
    time.sleep(3)

    down, up = [], []
    for index in range(1, presses + 1):
        # Odd presses draw the card once, even presses draw it twice. Paired
        # INSIDE one run rather than across two runs: the eye compares banded
        # against clean back to back, seconds apart, on the same board in the
        # same state -- and "the board was in a different mood today" stops
        # being an available explanation.
        passes = 2 if index % 2 == 0 else 1
        label = "DOUBLE draw" if passes > 1 else "single draw"

        if mode == "width":
            # The other question the same rig can ask, and the one that should
            # have been asked first. If bands are seams between flushed strips
            # then their pitch is buffer-px over area WIDTH -- so halving the
            # width must double the spacing and halve the count. That is a
            # prediction only this hypothesis makes, and the eye judges it
            # without measuring anything: fewer bands, further apart.
            #
            # Nothing else about the card changes, and both variants draw once.
            passes = 1
            narrow = index % 2 == 0
            card.set_width(width // 2 if narrow else width)
            label = "NARROW {}px".format(width // 2 if narrow else width)
            scr.update_layout()
            lv.refr_now(None)

        # Settled before the clock starts: the counter's own invalidated
        # rectangle would otherwise be merged into the press redraw and charged
        # to it. Nothing else is printed between presses -- console traffic
        # over the serial link during a redraw is the kind of interruption
        # under test, and an instrument that perturbs what it measures answers
        # about itself.
        counter.set_text("press {} / {}    {}".format(
            index, presses, label))
        lv.refr_now(None)

        start = time.ticks_us()
        card.add_state(lv.STATE.PRESSED)
        lv.refr_now(None)
        for _ in range(passes - 1):
            card.invalidate()
            lv.refr_now(None)
        down.append(time.ticks_diff(time.ticks_us(), start) / 1000.0)
        time.sleep_ms(hold_ms)

        start = time.ticks_us()
        card.remove_state(lv.STATE.PRESSED)
        lv.refr_now(None)
        for _ in range(passes - 1):
            card.invalidate()
            lv.refr_now(None)
        up.append(time.ticks_diff(time.ticks_us(), start) / 1000.0)
        time.sleep_ms(rest_ms)

    # Index 1 is odd and sits at list position 0, so the even slice is the
    # varied one.
    other = "NARROW" if mode == "width" else "DOUBLE"
    _spread("press,   plain  ", down[0::2])
    _spread("press,   " + other, down[1::2])
    _spread("release, plain  ", up[0::2])
    _spread("release, " + other, up[1::2])
    print("")
    print("PROBE_DONE {} presses".format(presses))
    print("")
    print("This exit code means the probe RAN, not that the card is clean.")
    print("The finding is what the watcher saw: whether the ODD presses")
    print("(single draw) ruled the card while the EVEN ones (double) came")
    print("out clean, and what the scale said the spacing was.")


def _heap_free():
    """(total free bytes, regions) across the IDF data heap, or None.

    esp32.idf_heap_info sees what gc.mem_free() cannot: the framebuffers are
    allocated by esp_lcd in C and never touch MicroPython's heap, so watching
    the IDF allocator is the only way to count them from up here. Reading the
    accounting collects nothing -- it is *forcing* a collection that is banned
    once rendering has started, and nothing here has rendered yet.
    """
    try:
        import esp32
        regions = esp32.idf_heap_info(esp32.HEAP_DATA)
    except Exception as exc:
        print("   (esp32.idf_heap_info unavailable: {})".format(exc))
        return None
    return sum(region[1] for region in regions), regions


def _knobs(obj, label):
    """Print the buffer-shaped attributes an object carries. Reads only."""
    print("   {}:".format(label))
    found = 0
    for name in sorted(dir(obj)):
        low = name.lower()
        if not any(word in low for word in
                   ("buf", "fb", "frame", "render", "mode", "bounce")):
            continue
        found += 1
        try:
            value = getattr(obj, name)
        except Exception as exc:
            print("      {:<30} (unreadable: {})".format(name, exc))
            continue
        if isinstance(value, (int, bool)) or value is None:
            print("      {:<30} {}".format(name, value))
        else:
            try:
                print("      {:<30} {} of {}".format(
                    name, type(value).__name__, len(value)))
            except TypeError:
                print("      {:<30} {}".format(name, type(value).__name__))
    if not found:
        print("      (none)")


def probe_display_buffers():
    """Count the buffers the RGB driver allocates on the FLASHED firmware.

    Task 48 proved the mechanism by experiment: the panel shows content the
    current render did not produce, and drawing the same area again supplies
    it. Reading lvgl_micropython's source then named the cause -- rgb_bus.c
    sets `double_fb = 1`, so esp_lcd keeps two full framebuffers and the copy
    task resyncs the idle one with a whole-framebuffer memcpy after every
    refresh.

    Source is not firmware. This project has already been bitten by a flashed
    binary that was not the one on disk, and the whole argument rests on that
    flag being set in what is actually running. So it gets counted, not
    assumed.

    Written before the run -- one 800x480 RGB565 framebuffer is 768,000 bytes:

      ~1.72MB  two framebuffers (1,536,000) plus LVGL's two partial draw
               buffers (2 x 76,800) plus the bounce pair (2 x 16,000).
               The flashed firmware matches the source and 48 stands.
      ~0.95MB  ONE framebuffer. The source on disk is not what is running,
               and the explanation needs rewriting even though the
               experimental result does not.
      no drop  the allocation does not come from this heap and this probe
               answered nothing. Say that, do not reason around it.

    Nothing here writes, resizes or reconfigures. The panel comes up exactly
    as the product brings it up -- a count taken against a different
    configuration is a count of something else.
    """
    print("== display buffers: what the flashed firmware allocates ==")
    print("   one 800x480 RGB565 framebuffer = 768,000 bytes.")
    print("   expected ~1,721,600 for two of them + LVGL's two partial")
    print("   draw buffers (76,800 each) + the bounce pair (16,000 each).")
    print("")

    before = _heap_free()
    if before is None:
        print("!! no heap accounting on this build, so nothing can be "
              "counted. Not inferring it from the driver source.")
        return
    print("   free before display.init():  {:>10}".format(before[0]))

    disp = display.init()

    after = _heap_free()
    print("   free after  display.init():  {:>10}".format(after[0]))
    spent = before[0] - after[0]
    print("")
    print("   consumed by bring-up:        {:>10} bytes".format(spent))
    print("   = {:.2f} full framebuffers' worth".format(spent / 768000.0))
    print("")
    print("   per region, free before -> after (only those that moved):")
    for index in range(min(len(before[1]), len(after[1]))):
        was, now = before[1][index][1], after[1][index][1]
        if was != now:
            print("      region {:<2} {:>10} -> {:>10}   ({:+d})".format(
                index, was, now, now - was))

    print("")
    print("== what the driver is willing to be told ==")
    _knobs(disp, "the display object")
    bus = getattr(disp, "_data_bus", None)
    if bus is None:
        print("   the bus object: not reachable from the display")
    else:
        _knobs(bus, "the bus object")

    print("")
    print("PROBE_DONE display buffers")
    print("")
    print("This exit code means the probe RAN. The finding is the byte count")
    print("above: whether the firmware on this board really keeps two full")
    print("framebuffers, which is what task 48's explanation rests on.")



def probe_touch(press_level=None, leave_level=None,
                shake_count=None, refresh_rate=None):
    """Report the touch controller's configuration. Writes only when told to.

    Two different complaints hide under "the touch is not sensitive enough",
    and they have different knobs:

      taps that are missed      -> the GT911's own press/leave thresholds, in
                                   the controller's config registers
      taps that land late       -> how often LVGL samples the panel, which is
                                   an LVGL timer and nothing to do with the
                                   controller

    Both are reported here. Reading first is the point: a threshold set from a
    guess is a number with no baseline, and if it turns out worse there is
    nothing to go back to. The current values ARE the thing to go back to, so
    they get printed before anything is written.

    Passing press_level/leave_level writes them. That write goes to the
    controller's own flash and survives power-off and reflashing -- it is not
    in this repo and nothing here can see it later, which is exactly why the
    run prints what it changed FROM. The GT911's config flash has a limited
    number of write cycles, so this is a deliberate, occasional act, never a
    loop and never a default.
    """
    display.init()
    theme.load_fonts()

    if display.touch is None:
        print("!! the touch driver did not come up, so there is nothing to "
              "report and nothing to tune.")
        return

    print("== how often LVGL samples the panel ==")
    getter = getattr(display.touch._indev_drv, "get_read_timer", None)
    if getter is None:
        print("   this binding has no get_read_timer; the period is whatever")
        print("   lv_conf.h set (LV_DEF_REFR_PERIOD, 33ms) and display.py's")
        print("   retune silently did nothing.")
    else:
        # lv_timer_t exposes the period as a struct field, not a getter --
        # get_period does not exist in this binding. Read back rather than
        # trust: display.init() has already set it, and a probe that prints
        # what it asked for instead of what took effect is the false green
        # this file exists to avoid.
        timer = getter()
        period = getattr(timer, "period", None)
        print("   read timer period: {}   (display.TOUCH_SAMPLE_MS = {})"
              .format("unreadable in this binding" if period is None
                      else "{}ms".format(period), display.TOUCH_SAMPLE_MS))
        print("   a tap costs two samples -- one to see it land, one to see")
        print("   it lift -- because LVGL reports the click on release.")

    print("")
    print("== the controller's own thresholds ==")
    try:
        # A property in this driver, not a method -- calling it returns the
        # extension and then tries to call the extension.
        config = display.touch.firmware_config
        if callable(config):
            config = config()
    except Exception as exc:
        print("   unavailable: {}".format(exc))
        print("   gt911_extension.py has to be on the board for this; the")
        print("   runner uploads it from products/panel/host/vendor/.")
        print("")
        print("PROBE_DONE touch")
        return

    for name in ("touch_press_level", "touch_leave_level", "noise_reduction"):
        print("   {:<20} {}".format(name, getattr(config, name)))

    # Read straight out of the config block, because these three are where the
    # LATENCY lives and the extension exposes none of them. Offsets are from
    # 0x8047; Goodix's own table:
    #   0x804F Shake_Count   de-jitter counts, one nibble for release and one
    #                        for press -- how many consecutive scans the
    #                        controller must agree on before it reports
    #   0x8050 Filter        First_Filter | Normal_Filter, coordinate
    #                        smoothing, coefficient 4
    #   0x8056 Refresh_Rate  "Coordinates report period: 5+N ms"
    #
    # So the delay before a press is seen is roughly
    #   press de-jitter count x (5 + Refresh_Rate) ms
    # and the delay before the release is seen -- which is when LVGL fires the
    # click -- is the release count times the same period.
    raw = config._config_data
    shake, filt, refresh = raw[0x08], raw[0x09], raw[0x0F]
    period = 5 + refresh
    print("")
    print("   {:<20} 0x{:02X}  ({} and {} scans)".format(
        "shake_count", shake, shake >> 4, shake & 0x0F))
    print("   {:<20} 0x{:02X}  (first {}, normal {})".format(
        "filter", filt, filt >> 4, filt & 0x0F))
    print("   {:<20} {}    -> report period {}ms".format(
        "refresh_rate", refresh, period))
    print("")
    print("   so the controller alone costs about {}ms to confirm one edge"
          .format((shake >> 4) * period))
    print("   and {}ms for the other, before LVGL has sampled anything."
          .format((shake & 0x0F) * period))
    print("")
    print("   press_level is how much signal counts as a finger landing:")
    print("   LOWER is more sensitive. leave_level is when it counts as")
    print("   lifted, and it must stay BELOW press_level or the controller")
    print("   chatters between the two.")

    wanted = (press_level, leave_level, shake_count, refresh_rate)
    if all(value is None for value in wanted):
        print("")
        print("   Nothing written. Pass any of press_level, leave_level,")
        print("   shake_count or refresh_rate to change it.")
        print("")
        print("PROBE_DONE touch")
        return

    was = (config.touch_press_level, config.touch_leave_level, shake, refresh)
    if press_level is not None:
        config.touch_press_level = press_level
    if leave_level is not None:
        config.touch_leave_level = leave_level
    # Straight into the config block: the extension has no property for
    # either, and these two are where the latency is.
    if shake_count is not None:
        raw[0x08] = shake_count & 0xFF
    if refresh_rate is not None:
        raw[0x0F] = refresh_rate & 0xFF
    now = (config.touch_press_level, config.touch_leave_level,
           raw[0x08], raw[0x0F])

    if now[1] >= now[0]:
        print("")
        print("!! leave_level {} is not below press_level {}. The controller "
              "would chatter between pressed and released in the middle of a "
              "steady touch; refusing to write.".format(now[1], now[0]))
        print("")
        print("PROBE_DONE touch")
        return

    print("")
    print("== writing ==")
    for name, before, after in zip(
            ("press_level", "leave_level", "shake_count", "refresh_rate"),
            was, now):
        print("   {:<14} {:>4} -> {}{}".format(
            name, before, after, "" if before != after else "   (unchanged)"))
    print("")
    print("   The values on the LEFT are the way back. They live in the")
    print("   controller's own flash -- they survive power-off, a reflash and")
    print("   --erase-all, and nothing in this repo can see them. Write them")
    print("   down; that flash also has a limited number of write cycles, so")
    print("   this is not a knob to turn in a loop.")
    config.save()
    print("   saved.")

    print("")
    print("PROBE_DONE touch")

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
    test_lists_never_overflow_the_glass(home)
    test_the_wizard_stays_on_the_glass(home)
    test_deleting_a_sub_page_releases_its_clock(home)
    test_reopening_does_not_leak(home)
    test_add_device_rows()
    test_font_glyph_coverage()
    test_text_input_offers_digits_and_stays_on_the_glass(home)
    test_text_input_has_a_cursor(home)
    test_a_device_row_stays_tappable()
    test_add_device_page_stays_on_the_glass(home)

    failed = [name for name, ok, _ in _results if not ok]
    print()
    print("{} of {} passed".format(len(_results) - len(failed), len(_results)))
    if failed:
        print("FAILED: " + ", ".join(failed))
    # The one line the host scores this run by. It cannot import the constant
    # from run_common -- that is host code and this is MicroPython -- so
    # tests/test_hwtest_verdict.py pins the two spellings together.
    print("HWTEST_RESULT " + ("fail {}".format(len(failed)) if failed
                              else "pass"))
    return not failed
