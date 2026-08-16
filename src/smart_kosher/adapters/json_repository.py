"""Validated JSON repository with backup-based atomic replacement."""

try:
    import ujson as json
except ImportError:
    import json

import os

from ..domain._values import clone_json, is_integer
from ..domain.entities import ALL_ENTITY_TYPES, validate_entity
from ..domain.events import validate_event
from ..domain.schedules import retired_zman_key
from ..ports.journal import EventJournal
from ..ports.repository import Repository
from ._atomic_io import exists as _exists
from ._atomic_io import flush_file as _flush_file
from ._atomic_io import replace as _replace
from ._atomic_io import sync_filesystem as _sync_filesystem


class RepositoryError(Exception):
    pass


class RepositoryValidationError(ValueError):
    """Invalid input, not a storage failure -- so it is a ValueError.

    It descends from ValueError and not from RepositoryError, which is the
    same shape the domain uses (DeviceValidationError, ScheduleValidationError
    are both ValueError). upsert()/replace_all() catch the domain's own
    XValidationError and re-raise it as this type; while this was a plain
    RepositoryError that re-raise *destroyed* the classification, because
    Api.dispatch turns ValueError into bad_request/400 and everything else
    into internal/500. Every rejected field answered 500 on both products,
    while the suite -- which builds its clients on MemoryRepository, which
    does no such conversion -- saw 400 and passed.

    Deriving from (RepositoryError, ValueError) would also have worked on
    CPython, but that is multiple inheritance from a native type, which
    MicroPython restricts -- and it would have been the only such class in
    the code that ships to a board. Nothing catches RepositoryError as a
    base: it is raised directly, once, for a directory that cannot be made.

    RepositoryCorruptionError deliberately stays outside ValueError: corrupt
    storage is an internal fault, and 500 is the right answer for it.
    """


class RepositoryCorruptionError(RepositoryError):
    pass


class JsonRepository(Repository):
    def __init__(self, base_path="/data", load=True):
        self.base_path = base_path.rstrip("/\\") or base_path
        self._data = {entity_type: [] for entity_type in ALL_ENTITY_TYPES}
        self._revisions = {entity_type: 0 for entity_type in ALL_ENTITY_TYPES}
        # Records dropped while loading because they name a retired zman. Read
        # by application.migrations, which persists the cleaned collection and
        # reports what went. Never silently discarded.
        self.dropped_records = []
        self._ensure_base_path()
        if load:
            self.load_all()

    @staticmethod
    def _validate_type(entity_type):
        if entity_type not in ALL_ENTITY_TYPES:
            raise RepositoryValidationError(
                "unsupported entity type: {}".format(entity_type)
            )

    def _path(self, entity_type, suffix=""):
        self._validate_type(entity_type)
        return "{}/{}.json{}".format(self.base_path, entity_type, suffix)

    def _ensure_base_path(self):
        if _exists(self.base_path):
            return
        try:
            os.mkdir(self.base_path)
        except OSError as exc:
            raise RepositoryError("cannot create storage directory: {}".format(exc))

    @staticmethod
    def _validate_collection(entity_type, data):
        if not isinstance(data, list):
            raise RepositoryValidationError("stored entity collection must be a list")
        seen = set()
        for entity in data:
            try:
                validate_entity(entity_type, entity)
            except ValueError as exc:
                raise RepositoryValidationError(str(exc))
            if entity["id"] in seen:
                raise RepositoryValidationError(
                    "duplicate entity id: {}".format(entity["id"])
                )
            seen.add(entity["id"])

    def _drop_retired(self, entity_type, data):
        """Separate records naming a retired zman from the rest.

        These are not corruption and must not reach _validate_collection: a
        schedule written before a zman was retired is well-formed data that the
        current rules no longer accept. Failing it there would send a healthy
        file down the .tmp/.bak recovery path, where the backup holds the very
        same record -- and the device would refuse to start over one stale
        switch. They are dropped here and reported by application.migrations.
        """
        if entity_type != "schedules" or not isinstance(data, list):
            return data
        kept = []
        # Recorded by id: load_all may read the same collection up to three
        # times (primary, then .tmp, then .bak) when the primary is unreadable,
        # and each pass would otherwise report the same stale schedule again.
        seen = {record.get("id") for record in self.dropped_records
                if isinstance(record, dict)}
        for record in data:
            if retired_zman_key(record) is None:
                kept.append(record)
            elif record.get("id") not in seen:
                self.dropped_records.append(record)
                seen.add(record.get("id"))
        return kept

    def _read_collection(self, entity_type, path):
        with open(path) as handle:
            data = json.load(handle)
        data = self._drop_retired(entity_type, data)
        self._validate_collection(entity_type, data)
        return data

    def load_all(self):
        for entity_type in ALL_ENTITY_TYPES:
            if entity_type == "journal" and any(
                _exists("{}/journal.log{}".format(self.base_path, suffix))
                for suffix in ("", ".tmp", ".bak")
            ):
                self._data[entity_type] = []
                self._revisions[entity_type] += 1
                continue
            primary = self._path(entity_type)
            backup = self._path(entity_type, ".bak")
            temporary = self._path(entity_type, ".tmp")
            if not _exists(primary) and not _exists(backup) and not _exists(temporary):
                self._data[entity_type] = []
                self._revisions[entity_type] += 1
                continue

            try:
                self._data[entity_type] = self._read_collection(entity_type, primary)
            except (OSError, ValueError, RepositoryValidationError) as primary_error:
                recovery_errors = []
                for recovery_path in (temporary, backup):
                    try:
                        recovered = self._read_collection(entity_type, recovery_path)
                        _replace(recovery_path, primary)
                        _sync_filesystem()
                        self._data[entity_type] = recovered
                        break
                    except (OSError, ValueError, RepositoryValidationError) as recovery_error:
                        recovery_errors.append(str(recovery_error))
                else:
                    raise RepositoryCorruptionError(
                        "{} has no readable primary, temporary, or backup file: {}; {}".format(
                            entity_type, primary_error, "; ".join(recovery_errors)
                        )
                    )
            self._revisions[entity_type] += 1
        return clone_json(self._data)

    def _save_collection(self, entity_type, collection):
        self._validate_type(entity_type)
        self._validate_collection(entity_type, collection)
        self._ensure_base_path()

        primary = self._path(entity_type)
        temporary = self._path(entity_type, ".tmp")
        backup = self._path(entity_type, ".bak")
        with open(temporary, "w") as handle:
            json.dump(collection, handle)
            _flush_file(handle)

        if _exists(primary):
            _replace(primary, backup)
        try:
            _replace(temporary, primary)
            _sync_filesystem()
        except OSError:
            if _exists(backup) and not _exists(primary):
                _replace(backup, primary)
            raise

        self._data[entity_type] = clone_json(collection)
        self._revisions[entity_type] += 1

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
        try:
            validate_entity(entity_type, entity)
        except ValueError as exc:
            raise RepositoryValidationError(str(exc))
        items = clone_json(self._data[entity_type])
        for index, current in enumerate(items):
            if current["id"] == entity["id"]:
                items[index] = clone_json(entity)
                self._save_collection(entity_type, items)
                return "updated"
        items.append(clone_json(entity))
        self._save_collection(entity_type, items)
        return "created"

    def replace_all(self, entity_type, entities):
        self._save_collection(entity_type, entities)

    def delete_by_id(self, entity_type, entity_id):
        self._validate_type(entity_type)
        items = [item for item in self._data[entity_type] if item["id"] != entity_id]
        if len(items) == len(self._data[entity_type]):
            return False
        self._save_collection(entity_type, items)
        return True

    def get_revision(self, entity_type):
        self._validate_type(entity_type)
        return self._revisions[entity_type]

    def _cache_journal_records(self, records):
        self._data["journal"] = records
        self._revisions["journal"] += 1


class JsonEventJournal(EventJournal):
    """Append-only persistent journal with bounded in-memory lookup."""

    def __init__(self, repository, max_records=4096):
        if not is_integer(max_records) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self.repository = repository
        self.max_records = max_records
        self._records = []
        self._by_id = {}
        self._physical_record_count = 0
        self._needs_compaction = False
        self._loaded_legacy = False

        base_path = getattr(repository, "base_path", None)
        self._log_path = (
            "{}/journal.log".format(base_path)
            if isinstance(base_path, str) and base_path
            else None
        )
        if self._log_path is None or not self._load_log():
            self._load_legacy_records()

    @staticmethod
    def _validate_record(record):
        try:
            validate_entity("journal", record)
        except ValueError as exc:
            raise RepositoryValidationError(str(exc))

    def _set_records(self, records):
        seen = set()
        selected = []
        for record in reversed(records):
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            selected.append(record)
            if len(selected) == self.max_records:
                break
        selected.reverse()
        self._records = selected
        self._by_id = {record["id"]: record for record in selected}
        cache_records = getattr(self.repository, "_cache_journal_records", None)
        if cache_records is not None:
            cache_records(self._records)

    def _load_legacy_records(self):
        records = self.repository.get_all("journal")
        for record in records:
            self._validate_record(record)
        self._set_records(records)
        self._loaded_legacy = bool(records)

    def _read_log(self, path):
        with open(path) as handle:
            lines = handle.readlines()

        records = []
        truncated_tail = False
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                self._validate_record(record)
            except (ValueError, RepositoryValidationError) as exc:
                if index == len(lines) - 1 and not line.endswith("\n"):
                    truncated_tail = True
                    break
                raise RepositoryCorruptionError(
                    "invalid journal log record: {}".format(exc)
                )
            records.append(record)
        return records, truncated_tail

    def _load_log(self):
        temporary = self._log_path + ".tmp"
        backup = self._log_path + ".bak"
        candidates = (self._log_path, temporary, backup)
        if not any(_exists(path) for path in candidates):
            return False

        errors = []
        for path in candidates:
            try:
                records, truncated_tail = self._read_log(path)
                if path != self._log_path:
                    _replace(path, self._log_path)
                    _sync_filesystem()
                self._physical_record_count = len(records)
                self._set_records(records)
                self._needs_compaction = (
                    truncated_tail
                    or len(records) != len(self._records)
                    or len(self._by_id) != len(self._records)
                )
                return True
            except (OSError, RepositoryCorruptionError) as exc:
                errors.append(str(exc))
        raise RepositoryCorruptionError(
            "journal log has no readable primary, temporary, or backup file: {}".format(
                "; ".join(errors)
            )
        )

    def _write_compacted(self, records):
        temporary = self._log_path + ".tmp"
        backup = self._log_path + ".bak"
        with open(temporary, "w") as handle:
            for record in records:
                handle.write(json.dumps(record))
                handle.write("\n")
            _flush_file(handle)

        if _exists(self._log_path):
            _replace(self._log_path, backup)
        try:
            _replace(temporary, self._log_path)
            _sync_filesystem()
        except OSError:
            if _exists(backup) and not _exists(self._log_path):
                _replace(backup, self._log_path)
            raise

        self._physical_record_count = len(records)
        self._needs_compaction = False
        self._loaded_legacy = False

    def _append(self, record):
        existed = _exists(self._log_path)
        with open(self._log_path, "a") as handle:
            handle.write(json.dumps(record))
            handle.write("\n")
            _flush_file(handle)
        if not existed:
            _sync_filesystem()
        self._physical_record_count += 1

    def _records_with(self, record):
        records = [
            current for current in self._records
            if current["id"] != record["id"]
        ]
        records.append(record)
        return records[-self.max_records:]

    def was_executed(self, event_id):
        if self._log_path is None:
            return self.repository.get_by_id("journal", event_id) is not None
        return event_id in self._by_id

    def record(self, event, result):
        validate_event(event)
        record = {
            "id": event["event_id"],
            "event": clone_json(event),
            "result": clone_json(result),
        }
        self._validate_record(record)

        if self._log_path is None:
            records = [
                item for item in self.repository.get_all("journal")
                if item["id"] != event["event_id"]
            ]
            records.append(record)
            self.repository.replace_all("journal", records[-self.max_records:])
            return "recorded"

        records = self._records_with(record)
        should_compact = (
            self._loaded_legacy
            or self._needs_compaction
            # Avoid full-file rewrites, then periodically discard stale log entries.
            or self._physical_record_count + 1 > self.max_records * 2
        )
        try:
            if should_compact:
                self._write_compacted(records)
            else:
                self._append(record)
        except Exception:
            self._needs_compaction = True
            raise
        self._set_records(records)
        return "recorded"

    def get(self, event_id):
        if self._log_path is None:
            record = self.repository.get_by_id("journal", event_id)
        else:
            record = self._by_id.get(event_id)
        if record is None:
            return None
        value = clone_json(record)
        value["event"]["source_date"] = tuple(value["event"]["source_date"])
        return value
