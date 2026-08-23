# The add-device screen: one row per *gang*, not per device.
#
# It replaces main._try_autopair, which grabbed the first unclaimed device the
# moment one appeared, invented a name from a count, and created exactly one
# entity. A two-gang switch came out as one entity called "מכשיר 2" -- a name
# that is not even its number -- and the second gang was unreachable from the
# UI forever.
#
# A row is an endpoint carrying OnOff that has no entity yet. Two things about
# that sentence are load-bearing:
#
#   * OnOff, from the device's own cluster discovery. Endpoint 242 on the real
#     actuator is Green Power: it is an endpoint, it is not a gang, and it
#     cannot switch anything.
#   * "has no entity" means no entity with this ieee *and this endpoint*. By
#     ieee alone -- the obvious way to write it -- adopting gang 1 makes gang 2
#     disappear from the list, which is the same bug in a new place.
#
# Identify and discard go through zigbee.identify and zigbee.discard. Neither
# is a primitive this screen assembles: identify is one call that reads, flips,
# holds and restores on the server side, because a screen change between two
# dispatches would leave a real load switched on; discard is local-only and
# never writes remove_device, which this firmware acks unconditionally.
#
# A three-gang switch arrives as endpoints [1,2,3] and gets three rows with no
# new code here.

import lvgl as lv

import bridge
import shell
import store
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_label

CLUSTER_ON_OFF = 6

_screen = None
_zone_id = None
_return = None
_effects = []


def _teardown():
    for eff in _effects:
        eff.dispose()
    del _effects[:]


def _back():
    lv.screen_load(_return)


def _discovery_complete(entry):
    """Whether this device has told us what it is made of.

    device_joined always says endpoint 1, because that is all it knows when it
    announces; the endpoint list and the clusters arrive afterwards in separate
    messages. Drawing a row the moment a device joins therefore shows a
    two-gang switch as one gang, the user adds only that one, and we are back
    to the bug this screen exists to fix. So a device counts as known only once
    its endpoint list is present *and* every endpoint in it has an entry in
    clusters.
    """
    endpoints = entry.get("endpoints")
    if not endpoints:
        return False
    clusters = entry.get("clusters") or {}
    for endpoint in endpoints:
        if str(endpoint) not in clusters:
            return False
    return True


def _onoff_endpoints(entry):
    clusters = entry.get("clusters") or {}
    return [endpoint for endpoint in (entry.get("endpoints") or [])
            if CLUSTER_ON_OFF in (clusters.get(str(endpoint)) or [])]


def _claimed():
    """(ieee, endpoint) pairs that already have an entity."""
    taken = []
    for entity in store.endpoints.get():
        taken.append((entity.get("ieee_address"),
                      entity.get("zigbee_endpoint", 1)))
    return taken


def rows():
    """One entry per addable gang, plus the devices still being identified.

    Public because the on-device suite drives it directly: it is the whole
    decision this screen makes, and it is pure.
    """
    claimed = _claimed()
    ready, pending = [], []
    devices = store.devices.get()
    for ieee in sorted(devices):
        entry = devices[ieee]
        if not _discovery_complete(entry):
            pending.append(ieee)
            continue
        gangs = _onoff_endpoints(entry)
        for endpoint in gangs:
            if (ieee, endpoint) in claimed:
                continue
            ready.append({"ieee": ieee, "endpoint": endpoint,
                          "gangs": len(gangs)})
    return ready, pending


def _add(row):
    """Create the entity for one gang, in the room we are pairing into."""
    name = "גאנג {}".format(row["endpoint"]) if row["gangs"] > 1 else "מכשיר"
    data = {"name": name, "ieee_address": row["ieee"],
            "zigbee_endpoint": row["endpoint"]}
    if _zone_id:
        data["zone_id"] = _zone_id
    bridge.dispatch(store.api, "endpoints.create", {"data": data},
                    on_ok=lambda _r: _refresh_entities(),
                    on_err=lambda kind, msg: _toast("לא ניתן להוסיף"))


def _identify(row):
    """Flip this gang for a moment so the user can see which one it is."""
    _toast("מהבהב…")
    bridge.dispatch(store.api, "zigbee.identify",
                    {"ieee": row["ieee"], "endpoint": row["endpoint"]},
                    on_ok=_identified,
                    on_err=lambda kind, msg: _toast("לא ניתן לזהות"))


def _identified(result):
    result = result or {}
    # Tapping two rows inside one pulse is the natural rhythm of "which one is
    # this?", and the gateway refuses the second rather than let the two undo
    # each other. Say so, or the row looks broken.
    if result.get("error") == "identify_in_progress":
        _toast("מכשיר זה כבר מהבהב — המתן רגע")
        return
    # The restore is the half that can hurt, so its failure is spoken rather
    # than swallowed: the load is left inverted and only the user can see it.
    if result.get("restored") is False:
        _toast("הזיהוי בוצע אך המצב לא הוחזר — בדוק את המכשיר")


def _discard(row):
    """Take the row off the list. The device stays on the network."""
    bridge.dispatch(store.api, "zigbee.discard", {"ieee": row["ieee"]},
                    on_ok=lambda _r: _toast("הוסר מהרשימה"),
                    on_err=lambda kind, msg: _toast(
                        "המכשיר בשימוש — מחק אותו מהחדר"
                        if kind == "conflict" else "לא ניתן להסיר"))


def _toast(message):
    import toast
    toast.notify(message)


def _refresh_entities():
    bridge.dispatch(store.api, "endpoints.list", None,
                    on_ok=lambda items: store.endpoints.set(items))


def _build():
    scr, body = shell.page_create("הוסף מכשיר", on_back=_back, effects=_effects)
    body.set_style_pad_all(16, lv.PART.MAIN)
    column = w_group(body, lv.FLEX_FLOW.COLUMN)
    column.set_width(lv.pct(100))
    column.set_style_pad_row(8, lv.PART.MAIN)

    def _rebuild():
        column.clean()
        ready, pending = rows()
        if not ready and not pending:
            w_label(column, theme.FONTS.body, theme.TEXT,
                    "לחץ 5 שניות על כפתור המכשיר עד שהנורית מהבהבת")
            return
        for ieee in pending:
            # Named, not hidden: a device that is here but not yet understood
            # is exactly what the user is waiting on.
            w_label(column, theme.FONTS.body, theme.TEXT,
                    "מזהה יכולות…  {}".format(ieee[-8:]))
        for row in ready:
            card = w_card_button(column)
            card.set_width(lv.pct(100))
            card.set_height(theme.TAP_MIN + 16)
            label = "{}  ·  גאנג {}".format(row["ieee"][-8:], row["endpoint"]) \
                if row["gangs"] > 1 else row["ieee"][-8:]
            w_label(card, theme.FONTS.body, theme.TEXT, label)
            card.add_event_cb(lambda e, r=row: _add(r), lv.EVENT.CLICKED, None)
            buttons = w_group(column, lv.FLEX_FLOW.ROW)
            buttons.set_width(lv.pct(100))
            buttons.set_style_pad_column(8, lv.PART.MAIN)
            for text, handler in (("זהה", _identify), ("הסר מהרשימה", _discard)):
                button = w_card_button(buttons)
                button.set_width(lv.pct(48))
                button.set_height(theme.TAP_MIN)
                w_label(button, theme.FONTS.body, theme.TEXT, text).center()
                button.add_event_cb(lambda e, r=row, h=handler: h(r),
                                    lv.EVENT.CLICKED, None)

    _effects.append(effect(_rebuild))
    return scr


def open(zone_id):
    global _screen, _zone_id, _return
    _return = lv.screen_active()
    _zone_id = zone_id
    _teardown()
    old = _screen
    _screen = _build()
    lv.screen_load(_screen)
    if old is not None:
        old.delete()
