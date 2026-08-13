# Schedules screen -- lists every automation with a human Hebrew description,
# a quick enable/disable, and delete. Reactive on store.schedules (+ endpoints /
# groups for target names). "+ הוסף תזמון" opens the wizard.

import lvgl as lv

import bridge
import sched_describe
import shell
import store
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_label

_screen = None
_list = None
_list_effect = None


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


def _rebuild():
    schedules = store.schedules.get()
    _list.clean()
    if not schedules:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין תזמונים — הוסיפו תזמון למטה").center()
        return
    for schedule in schedules:
        _row(_list, schedule)


def _add(e):
    import schedule_add
    schedule_add.open()


def build():
    global _screen, _list, _list_effect
    scr, body = shell.page_create("תזמונים")
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)
    _list_effect = effect(_rebuild)

    add = w_card_button(body)
    add.set_width(lv.pct(100))
    add.set_height(52)
    add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    add.add_event_cb(_add, lv.EVENT.CLICKED, None)
    w_label(add, theme.FONTS.h1, theme.SURFACE, "+ הוסף תזמון").center()

    _screen = scr
    return scr
