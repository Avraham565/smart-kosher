"""Clock contract. Runtime clocks must return UTC timestamps."""


class Clock:
    def now_utc(self):
        """Return ``(year, month, day, hour, minute)`` in UTC."""
        raise NotImplementedError
