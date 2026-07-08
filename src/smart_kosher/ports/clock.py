"""Clock contract. Runtime clocks must return UTC timestamps."""


class Clock:
    def now_utc(self):
        """Return ``(year, month, day, hour, minute)`` in UTC."""
        raise NotImplementedError


class SettableClock(Clock):
    """A clock whose time can be set — the device RTC.

    The hub is offline (no NTP): the only time source is a trusted client.
    The RTC holds **UTC**; local time is always derived from it through the
    settings' UTC offset. Setters must therefore be given UTC, never local
    civil time.
    """

    def set_utc(self, year, month, day, hour, minute, second):
        raise NotImplementedError
