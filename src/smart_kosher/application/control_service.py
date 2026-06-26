"""Manual immediate device control — bypasses the scheduler."""

import binascii
import os
import time

from .crud_service import NotFoundError

_TARGET_TO_COLLECTION = {
    "endpoint": "endpoints",
    "group": "groups",
}

_VALID_ACTIONS = ("on", "off", "toggle")


class ControlService:
    def __init__(self, executor, repository):
        self._executor = executor
        self._repo = repository

    def send(self, target_type, target_id, action_type):
        if target_type not in _TARGET_TO_COLLECTION:
            raise ValueError("unsupported target_type: {}".format(target_type))
        if action_type not in _VALID_ACTIONS:
            raise ValueError("unsupported action_type: {}".format(action_type))
        collection = _TARGET_TO_COLLECTION[target_type]
        if self._repo.get_by_id(collection, target_id) is None:
            raise NotFoundError(target_id)
        return self._executor.execute(_build_event(target_type, target_id, action_type))


def _build_event(target_type, target_id, action_type):
    now = time.gmtime()
    return {
        "event_id": "ctrl_{}".format(binascii.hexlify(os.urandom(4)).decode()),
        "schedule_id": "manual",
        "source_date": (now[0], now[1], now[2]),
        "utc_minute": now[3] * 60 + now[4],
        "target_type": target_type,
        "target_id": target_id,
        "action_type": action_type,
        "action_data": {},
    }
