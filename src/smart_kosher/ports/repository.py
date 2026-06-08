"""Repository contract for JSON-native domain entities."""

from ..domain.entities import CONFIG_ENTITY_TYPES

ENTITY_TYPES = CONFIG_ENTITY_TYPES


class Repository:
    def get_all(self, entity_type):
        raise NotImplementedError

    def get_by_id(self, entity_type, entity_id):
        raise NotImplementedError

    def upsert(self, entity_type, entity):
        raise NotImplementedError

    def replace_all(self, entity_type, entities):
        raise NotImplementedError

    def delete_by_id(self, entity_type, entity_id):
        raise NotImplementedError

    def get_revision(self, entity_type):
        raise NotImplementedError
