"""CRUD use-cases for the four domain entity types."""

import binascii
import os

from ..domain.devices import DeviceValidationError
from ..domain.schedules import ScheduleValidationError

ENTITY_TYPES = ("zones", "endpoints", "groups", "schedules")

_PREFIXES = {
    "zones": "z",
    "endpoints": "ep",
    "groups": "grp",
    "schedules": "sch",
}


class NotFoundError(KeyError):
    pass


def _gen_id(entity_type):
    prefix = _PREFIXES.get(entity_type, "e")
    return "{}_{}".format(prefix, binascii.hexlify(os.urandom(4)).decode())


class CrudService:
    def __init__(self, repository):
        self._repo = repository

    def list(self, entity_type):
        return self._repo.get_all(entity_type)

    def get(self, entity_type, entity_id):
        entity = self._repo.get_by_id(entity_type, entity_id)
        if entity is None:
            raise NotFoundError(entity_id)
        return entity

    def create(self, entity_type, data):
        entity = dict(data)
        entity["id"] = _gen_id(entity_type)
        self._repo.upsert(entity_type, entity)
        return entity

    def update(self, entity_type, entity_id, data):
        self.get(entity_type, entity_id)
        entity = dict(data)
        entity["id"] = entity_id
        self._repo.upsert(entity_type, entity)
        return entity

    def delete(self, entity_type, entity_id):
        deleted = self._repo.delete_by_id(entity_type, entity_id)
        if not deleted:
            raise NotFoundError(entity_id)
