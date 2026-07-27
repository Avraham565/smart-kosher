"""CRUD use-cases for the four domain entity types."""

import binascii
import os

ENTITY_TYPES = ("zones", "endpoints", "groups", "schedules")

_PREFIXES = {
    "zones": "z",
    "endpoints": "ep",
    "groups": "grp",
    "schedules": "sch",
}


class NotFoundError(KeyError):
    pass


class InUseError(ValueError):
    """Deleting the entity would leave dangling references."""


def _gen_id(entity_type):
    prefix = _PREFIXES.get(entity_type, "e")
    return "{}_{}".format(prefix, binascii.hexlify(os.urandom(4)).decode())


def _names(entities):
    return ", ".join(sorted(e.get("name") or e["id"] for e in entities))


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
        self._check_not_referenced(entity_type, entity_id)
        deleted = self._repo.delete_by_id(entity_type, entity_id)
        if not deleted:
            raise NotFoundError(entity_id)

    def _check_not_referenced(self, entity_type, entity_id):
        if entity_type == "zones":
            used_by = [
                ep for ep in self._repo.get_all("endpoints")
                if ep.get("zone_id") == entity_id
            ]
            if used_by:
                raise InUseError(
                    "zone is used by endpoints: {}".format(_names(used_by))
                )
        elif entity_type == "endpoints":
            groups = [
                grp for grp in self._repo.get_all("groups")
                if entity_id in grp.get("member_ids", [])
            ]
            if groups:
                raise InUseError(
                    "endpoint is used by groups: {}".format(_names(groups))
                )
            self._check_no_schedules("endpoint", entity_id)
        elif entity_type == "groups":
            self._check_no_schedules("group", entity_id)

    def _check_no_schedules(self, target_type, target_id):
        schedules = [
            sch for sch in self._repo.get_all("schedules")
            if sch.get("target_type") == target_type
            and sch.get("target_id") == target_id
        ]
        if schedules:
            raise InUseError(
                "{} is used by schedules: {}".format(target_type, _names(schedules))
            )
