"""In-memory repository and journal for deterministic tests."""

from ..domain._values import clone_json, is_integer
from ..domain.entities import ALL_ENTITY_TYPES, validate_entity
from ..domain.events import validate_event
from ..ports.journal import EventJournal
from ..ports.repository import Repository


class MemoryRepository(Repository):
    def __init__(self, initial=None):
        self._data = {entity_type: [] for entity_type in ALL_ENTITY_TYPES}
        self._revisions = {entity_type: 0 for entity_type in ALL_ENTITY_TYPES}
        for entity_type, entities in (initial or {}).items():
            for entity in entities:
                self.upsert(entity_type, entity)

    @staticmethod
    def _validate_type(entity_type):
        if entity_type not in ALL_ENTITY_TYPES:
            raise ValueError("unsupported entity type: {}".format(entity_type))

    def get_all(self, entity_type):
        self._validate_type(entity_type)
        return clone_json(self._data[entity_type])

    def get_by_id(self, entity_type, entity_id):
        self._validate_type(entity_type)
        for entity in self._data[entity_type]:
            if entity["id"] == entity_id:
                return clone_json(entity)
        return None

    def upsert(self, entity_type, entity):
        self._validate_type(entity_type)
        validate_entity(entity_type, entity)
        items = clone_json(self._data[entity_type])
        for index, current in enumerate(items):
            if current["id"] == entity["id"]:
                items[index] = clone_json(entity)
                self._data[entity_type] = items
                self._revisions[entity_type] += 1
                return "updated"
        items.append(clone_json(entity))
        self._data[entity_type] = items
        self._revisions[entity_type] += 1
        return "created"

    def replace_all(self, entity_type, entities):
        self._validate_type(entity_type)
        if not isinstance(entities, list):
            raise ValueError("entities must be a list")
        seen = set()
        for entity in entities:
            validate_entity(entity_type, entity)
            if entity["id"] in seen:
                raise ValueError("duplicate entity id: {}".format(entity["id"]))
            seen.add(entity["id"])
        self._data[entity_type] = clone_json(entities)
        self._revisions[entity_type] += 1

    def delete_by_id(self, entity_type, entity_id):
        self._validate_type(entity_type)
        items = [item for item in self._data[entity_type] if item["id"] != entity_id]
        if len(items) == len(self._data[entity_type]):
            return False
        self._data[entity_type] = items
        self._revisions[entity_type] += 1
        return True

    def get_revision(self, entity_type):
        self._validate_type(entity_type)
        return self._revisions[entity_type]


class MemoryEventJournal(EventJournal):
    def __init__(self, repository=None, max_records=4096):
        if not is_integer(max_records) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self.repository = repository or MemoryRepository()
        self.max_records = max_records

    def was_executed(self, event_id):
        return self.repository.get_by_id("journal", event_id) is not None

    def record(self, event, result):
        validate_event(event)
        record = {
            "id": event["event_id"],
            "event": clone_json(event),
            "result": clone_json(result),
        }
        records = [
            item for item in self.repository.get_all("journal")
            if item["id"] != event["event_id"]
        ]
        records.append(record)
        self.repository.replace_all("journal", records[-self.max_records:])
        return "recorded"

    def get(self, event_id):
        return self.repository.get_by_id("journal", event_id)
