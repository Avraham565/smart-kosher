# Human Hebrew description of a schedule, derived from its fields (so the user
# never has to name schedules). Pure -- unit-tested on CPython.

import sched_labels


def _time(data):
    return "%02d:%02d" % (data.get("h", 0), data.get("m", 0))


def _when(schedule):
    trigger = schedule.get("trigger_type")
    data = schedule.get("trigger_data") or {}
    if trigger == "fixed_time":
        return "בשעה " + _time(data)
    zman = sched_labels.ZMAN_NAMES.get(data.get("zman"), data.get("zman") or "")
    if trigger == "zman":
        return "ב" + zman
    if trigger == "zman_offset":
        offset = data.get("offset", 0)
        if offset == 0:
            return "ב" + zman
        if offset < 0:
            return "{} דק׳ לפני {}".format(-offset, zman)
        return "{} דק׳ אחרי {}".format(offset, zman)
    return ""


def _every(schedule):
    recurrence = schedule.get("recurrence_type")
    if recurrence == "days_of_week":
        days = schedule.get("recurrence_data", {}).get("days") or []
        by_index = {index: label for label, index in sched_labels.DAYS_OF_WEEK}
        names = [by_index[d] for d in sorted(days) if d in by_index]
        return "בימים " + ", ".join(names) if names else "ימים בשבוע"
    return sched_labels.RECURRENCE_NAMES.get(recurrence, "")


def describe(schedule, target_name):
    """'<target> · הדלק/כבה · <when> · <recurrence>'."""
    action = "הדלק" if schedule.get("action_type") == "on" else "כבה"
    parts = [target_name, action, _when(schedule), _every(schedule)]
    return " · ".join(p for p in parts if p)
