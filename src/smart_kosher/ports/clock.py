"""Clock contract. Runtime clocks must return UTC timestamps."""

# A clock that was never set reads 2000-01-01 (machine.RTC and the PCF8563's
# factory default alike), so a year below this means "there is no real time
# here" -- fire nothing, show nothing, and wait for the user to set it.
#
# It lives on the port because every layer needs the same answer: the scheduler
# refuses to plan, status.get reports clock_unset, the RTC adapter refuses to
# sync a garbage time into the system clock, and the panel blanks its clock
# face. Those five checks were five bare 2013s, and the number is also the year
# Israeli DST law starts -- an unrelated rule that happens to share the value,
# which is exactly how a careless edit to one becomes a bug in the other.
MIN_VALID_YEAR = 2013

# Upper bound for a hand-entered year. Not a correctness limit, just a guard
# against a typo becoming a date the calendar maths has never been checked at.
MAX_VALID_YEAR = 2099


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
