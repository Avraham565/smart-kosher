"""Battery-backed PCF8563 RTC behind the SettableClock port (I2C).

The ESP32's internal ``machine.RTC`` loses time on a full power-off (fresh boot
reads 2000-01-01). Product A (CrowPanel) has a PCF8563 with a coin-cell backup on
the display I2C bus (address 0x51), which keeps time across power cycles. This
adapter reads/writes it, and -- so the rest of the system (``time.localtime`` in
status/zmanim) stays correct -- also mirrors writes into ``machine.RTC`` and can
sync the chip's time into it at boot.

Time is stored as UTC, matching the whole-system convention (every displayed
local time is derived from UTC + the settings offset).

Register map (PCF8563, 16 registers): 0x02 VL_seconds (bit7 VL = clock integrity
lost), 0x03 minutes, 0x04 hours, 0x05 days, 0x06 weekdays, 0x07 century_months
(bit7 century), 0x08 years. ``machine`` is imported lazily so this module stays
importable on CPython.
"""

from ..ports.clock import SettableClock

_ADDR = 0x51
_SECONDS_REG = 0x02


def _from_bcd(value):
    return (value >> 4) * 10 + (value & 0x0F)


def _to_bcd(value):
    return ((value // 10) << 4) | (value % 10)


class PCF8563(SettableClock):
    def __init__(self, i2c, addr=_ADDR):
        self._i2c = i2c
        self._addr = addr

    def read(self):
        """Return (year, month, day, hour, minute, second) as UTC, or None when
        the chip reports lost integrity (VL bit) or the read fails."""
        try:
            data = self._i2c.readfrom_mem(self._addr, _SECONDS_REG, 7)
        except OSError:
            return None
        if data[0] & 0x80:                 # VL: oscillator stopped, time invalid
            return None
        second = _from_bcd(data[0] & 0x7F)
        minute = _from_bcd(data[1] & 0x7F)
        hour = _from_bcd(data[2] & 0x3F)
        day = _from_bcd(data[3] & 0x3F)
        month = _from_bcd(data[5] & 0x1F)
        year = 2000 + _from_bcd(data[6])
        return (year, month, day, hour, minute, second)

    def now_utc(self):
        full = self.read()
        if full is None:
            import time
            now = time.gmtime()
            return (now[0], now[1], now[2], now[3], now[4])
        return full[:5]

    def set_utc(self, year, month, day, hour, minute, second):
        # weekday byte left 0: nothing here relies on the chip's weekday (zmanim
        # derives day-of-week from the date). Century bit 0 => 20xx.
        data = bytes([
            _to_bcd(second) & 0x7F,        # 0x02 clears VL
            _to_bcd(minute),               # 0x03
            _to_bcd(hour),                 # 0x04
            _to_bcd(day),                  # 0x05
            0,                             # 0x06 weekday
            _to_bcd(month),                # 0x07 century=0
            _to_bcd(year % 100),           # 0x08
        ])
        self._i2c.writeto_mem(self._addr, _SECONDS_REG, data)
        self._set_system(year, month, day, hour, minute, second)

    def sync_to_system(self):
        """Copy the chip's time into ``machine.RTC`` at boot so ``time.localtime``
        is correct immediately. No-op (returns False) when the chip has no real
        time yet (year < 2013 == never set / factory default)."""
        full = self.read()
        if full is None or full[0] < 2013:
            return False
        self._set_system(*full)
        return True

    @staticmethod
    def _set_system(year, month, day, hour, minute, second):
        try:
            import machine
            machine.RTC().datetime(
                (year, month, day, 0, hour, minute, second, 0))
        except Exception:
            pass
