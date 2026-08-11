"""One-time data repairs applied at startup, before anything reads storage.

A migration here exists because a stored record predates a rule and would
otherwise stay wrong forever -- validation on the write path only guards new
data, and a device provisioned last month never takes that path again.

Every migration is idempotent and reports what it changed. Silence is the
failure mode this module exists to prevent: a schedule the user set that
quietly stops firing is worse than one that is removed and named.
"""

from ..data.cities import load_cities
from ..domain.schedules import retired_zman_key

# How close a stored coordinate must be to a packaged city's to be considered
# that city. Roughly a kilometre -- far enough to absorb a rounded or slightly
# edited coordinate, tight enough that two different cities never collide.
_COORDINATE_TOLERANCE_DEG = 0.01


def backfill_missing_elevation(settings):
    """Write an explicit elevation into a settings file that predates the field.

    Elevation only started reaching the zmanim when it became a setting. Until
    a device stores one, it falls back to the default -- and the default is
    Jerusalem's 779 m, which on a device configured for Tel Aviv would push
    sunset almost five minutes the wrong way. A missing value must not inherit
    another city's altitude.

    So the value is resolved once, from the coordinates the device already has:
    the packaged city at those coordinates, or sea level when they match none.
    Sea level is the honest answer for an unknown location and is what the
    system did before elevation was wired in.

    Returns the elevation it wrote, or None if there was already one.
    """
    # stored(), not get(): the default elevation would otherwise look like a
    # value the device had chosen, and this would never run.
    if settings.stored().get("elevation") is not None:
        return None

    # Resolve from the effective coordinates, so a device still on the default
    # location gets that location's elevation rather than sea level.
    effective = settings.get()
    lat = effective.get("lat")
    lon = effective.get("lon")
    elevation = 0
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        for city in load_cities().values():
            if (abs(city["lat"] - lat) <= _COORDINATE_TOLERANCE_DEG
                    and abs(city["lon"] - lon) <= _COORDINATE_TOLERANCE_DEG):
                elevation = city["elevation"]
                break

    settings.update({"elevation": elevation})
    return elevation


def purge_retired_zman_schedules(repository):
    """Delete schedules that fire on a zman the product no longer computes.

    Two paths reach the same result. A JSON repository has already held these
    records out of the loaded collection -- it must, or the file would look
    corrupt and the device would refuse to start -- and only lists them in
    ``dropped_records``; the stored file still contains them until we rewrite
    it here. An in-memory repository has no such step, so the collection is
    scanned directly.

    Returns the removed schedules, so the caller can report them to whoever
    configured them. Returns an empty list when there is nothing to do, which
    is the normal case on every start after the first.
    """
    dropped_at_load = list(getattr(repository, "dropped_records", ()))

    surviving = repository.get_all("schedules")
    still_present = [s for s in surviving if retired_zman_key(s) is not None]
    for schedule in still_present:
        repository.delete_by_id("schedules", schedule["id"])

    if dropped_at_load:
        # Rewrite the file without them; until this runs, every restart would
        # drop the same records again and report them again.
        repository.replace_all("schedules", repository.get_all("schedules"))
        del repository.dropped_records[:]

    return dropped_at_load + still_present


def apply_all(repository, settings=None):
    """Run every migration. Returns a summary of what changed, empty if nothing.

    Composition roots call this once, immediately after building the repository
    and the settings store, and before the planner reads either.
    """
    summary = {}

    retired = purge_retired_zman_schedules(repository)
    if retired:
        summary["removed_schedules"] = [
            {"id": schedule["id"],
             "zman": retired_zman_key(schedule),
             "name": schedule.get("name")}
            for schedule in retired
        ]

    if settings is not None:
        elevation = backfill_missing_elevation(settings)
        if elevation is not None:
            summary["elevation"] = elevation

    return summary


def describe(summary):
    """Render a summary as lines to log. Empty when nothing happened.

    Shared so the three composition roots report a migration identically; each
    having its own wording is how they drifted on defaults before.
    """
    lines = []
    for removed in summary.get("removed_schedules", ()):
        lines.append(
            "migration: dropped schedule {} ({!r}) -- fires on retired zman {}"
            .format(removed["id"], removed.get("name"), removed["zman"]))
    if "elevation" in summary:
        lines.append(
            "migration: elevation was unset, pinned to {} m from the stored "
            "coordinates".format(summary["elevation"]))
    return lines
