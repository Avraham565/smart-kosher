# Schedules screen -- lists every automation with a human Hebrew description,
# a quick enable/disable, and delete. Reactive on store.schedules (+ endpoints /
# groups for target names). "+ הוסף תזמון" opens the wizard.
#
# Pixel budget (800x480, and nothing here scrolls — see pager.py):
#     480 screen - 64 header                    = 416 body
#     416 - 2*16 body padding                   = 384
#     384 - 52 bottom bar - 10 pad_row          = 322 for the list
#     322 fits floor((322 + 8) / (64 + 8))      = 4 rows
# A schedule that falls off this page is one the user cannot disable or delete
# while it goes on firing, which is why the ceiling option was rejected. The
# arithmetic is the estimate — hwtest_ui.py measures the real capacity and pins
# SCHEDULES_PER_PAGE.

import lvgl as lv

import bridge
import pager
import sched_describe
import shell
import store
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_label, w_pager

# Pinned by hwtest_ui.test_lists_never_overflow_the_glass.
SCHEDULES_PER_PAGE = 4

_screen = None
_list = None
_effects = []
_page = 0
_pager_label = None
_pager_controls = ()


def _teardown():
    """Release this page's bindings before its screen is deleted.

    pages.py builds this screen once and keeps it, so in the product nothing
    ever deletes it. hwtest_ui does, to measure how many rows fit, and an
    effect is owned by the Signal it read rather than by the widget.
    """
    for eff in _effects:
        eff.dispose()
    del _effects[:]


def _target_name(schedule):
    target_id = schedule.get("target_id")
    collection = (store.endpoints.get() if schedule.get("target_type") == "endpoint"
                  else store.groups.get())
    for item in collection:
        if item["id"] == target_id:
            return item.get("name") or target_id
    return target_id or "?"


def _set_enabled(schedule, enabled):
    bridge.dispatch(store.api, "schedules.set_enabled",
                    {"id": schedule["id"], "enabled": enabled})
    updated = []
    for item in store.schedules.get():
        if item["id"] == schedule["id"]:
            item = dict(item)
            item["enabled"] = enabled
        updated.append(item)
    store.schedules.set(updated)


def _delete(schedule):
    bridge.dispatch(store.api, "schedules.delete", {"id": schedule["id"]})
    store.schedules.set(
        [s for s in store.schedules.get() if s["id"] != schedule["id"]])


def _edit(schedule):
    import schedule_add
    schedule_add.open(schedule)


def _row(parent, schedule):
    enabled = schedule.get("enabled", True)
    row = w_group(parent, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                       lv.FLEX_ALIGN.CENTER)

    desc = w_card_button(row)
    desc.set_flex_grow(1)
    desc.set_height(64)
    desc.add_event_cb(lambda e: _edit(schedule), lv.EVENT.CLICKED, None)
    text = sched_describe.describe(schedule, _target_name(schedule))
    label = w_label(desc, theme.FONTS.body,
                    theme.TEXT if enabled else theme.FAINT, text)
    label.align(lv.ALIGN.RIGHT_MID, 0, 0)

    state = w_card_button(row)
    state.set_size(90, 64)
    state.add_event_cb(lambda e: _set_enabled(schedule, not enabled),
                       lv.EVENT.CLICKED, None)
    w_label(state, theme.FONTS.body, theme.SUCCESS if enabled else theme.MUTED,
            "פעיל" if enabled else "מושבת").center()

    remove = w_card_button(row)
    remove.set_size(64, 64)
    remove.add_event_cb(lambda e: _delete(schedule), lv.EVENT.CLICKED, None)
    w_label(remove, theme.FONTS.body, theme.DANGER, "מחק").center()


def _turn(delta):
    global _page
    _page += delta
    _rebuild()          # clamped there; nothing else may assume _page is valid


def _sync_pager(total):
    _pager_label.set_text(pager.label(_page, total, SCHEDULES_PER_PAGE))
    many = pager.page_count(total, SCHEDULES_PER_PAGE) > 1
    for control in _pager_controls:
        if many:
            control.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            control.add_flag(lv.obj.FLAG.HIDDEN)


def _rebuild():
    global _page
    # Explicit order, not the repository's, so the 3-second poll cannot shuffle
    # schedules between pages while the user is reaching for one. Schedules have
    # no name to sort by; the id is stable, unique, and never reused.
    schedules = sorted(store.schedules.get(), key=lambda s: s["id"])
    _list.clean()
    _page = pager.clamp_page(_page, len(schedules), SCHEDULES_PER_PAGE)
    if not schedules:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין תזמונים — הוסיפו תזמון למטה").center()
        _sync_pager(0)
        return
    for schedule in pager.page_items(schedules, _page, SCHEDULES_PER_PAGE):
        _row(_list, schedule)
    _sync_pager(len(schedules))


def _add(e):
    import schedule_add
    schedule_add.open()


def build():
    global _screen, _list, _pager_label, _pager_controls
    _teardown()          # a rebuild must not leave the last build's effects live
    scr, body = shell.page_create("תזמונים", effects=_effects)
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)

    # Built before the effect: _rebuild writes the pager label on its first pass.
    bar = w_group(body, lv.FLEX_FLOW.ROW)
    bar.set_width(lv.pct(100))
    bar.set_height(theme.TAP_MIN + 8)
    bar.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    _, _pager_label, _pager_controls = w_pager(
        bar, lambda: _turn(-1), lambda: _turn(1))

    add = w_card_button(bar)
    add.set_flex_grow(1)
    add.set_height(theme.TAP_MIN + 8)
    add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    add.add_event_cb(_add, lv.EVENT.CLICKED, None)
    w_label(add, theme.FONTS.h1, theme.SURFACE, "+ הוסף תזמון").center()

    _effects.append(effect(_rebuild))

    _screen = scr
    return scr
