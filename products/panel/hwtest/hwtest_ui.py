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
