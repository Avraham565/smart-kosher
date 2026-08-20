"""Manual immediate device control — bypasses the scheduler."""

import binascii
import os
import time

from ..domain.actions import ACTION_TYPES
from ..domain.entities import TARGET_COLLECTIONS
from ..zmanim import gregorian_day_number
from .crud_service import NotFoundError
from .executor import ACK_UNJOURNALED, EXECUTED

# Both vocabularies come from the domain. This module used to restate them --
# its own ("on","off","toggle") tuple and its own target->collection map -- so
# a fourth action would have been accepted by the domain and rejected here.

# Outcomes that mean the device acted, and so are worth asking it to confirm.
# ack_unjournaled belongs here for the same reason it stopped being re-sent by
# the scheduler -- the ack came back and the relay moved -- but the question is
# not the same one. The scheduler asked "send it again?"; this asks "read the
# state back?", and a command whose journal write failed is the one where an
# observed-state read matters most, because the journal has no record of it and
# the device's own word is the only evidence left.
#
# This is policy, so it lives with the caller that holds it; the names come
# from the Executor, which is what produces them.
_DEVICE_ACTED = (EXECUTED, ACK_UNJOURNALED)


class ControlService:
    def __init__(self, executor, repository):
        self._executor = executor
        self._repo = repository

    async def send(self, target_type, target_id, action_type,
                   confirm_ms=None):
        """Execute a manual action.

        ``confirm_ms`` (endpoint on/off only): after the command is acked,
        wait up to that long for the device's own attribute_report to say
        the state actually changed — observed-state confirmation, not an
        ack echo. Result gains a ``confirmation`` dict when requested and
        the gateway supports it (the simulator does not).
        """
        if target_type not in TARGET_COLLECTIONS:
            raise ValueError("unsupported target_type: {}".format(target_type))
        if action_type not in ACTION_TYPES:
            raise ValueError("unsupported action_type: {}".format(action_type))
        collection = TARGET_COLLECTIONS[target_type]
        entity = self._repo.get_by_id(collection, target_id)
        if entity is None:
            raise NotFoundError(target_id)

        outcome = await self._executor.execute(
            _build_event(target_type, target_id, action_type))

        if (confirm_ms and target_type == "endpoint"
                and action_type in ("on", "off")
                and outcome.get("status") in _DEVICE_ACTED):
            gateway = getattr(self._executor, "gateway", None)
            waiter = getattr(gateway, "wait_for_report", None)
            ieee = entity.get("ieee_address")
            if waiter is not None and ieee:
                outcome = dict(outcome)
                outcome["confirmation"] = await waiter(
                    ieee, action_type == "on", confirm_ms)
        return outcome


def _build_event(target_type, target_id, action_type):
    now = time.gmtime()
    return {
        "event_id": "ctrl_{}".format(binascii.hexlify(os.urandom(4)).decode()),
        "schedule_id": "manual",
        "source_date": (now[0], now[1], now[2]),
        "utc_minute": (
            gregorian_day_number(now[0], now[1], now[2]) * 1440
            + now[3] * 60 + now[4]
        ),
        "target_type": target_type,
        "target_id": target_id,
        "action_type": action_type,
        "action_data": {},
    }
