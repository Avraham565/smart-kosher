"""Route for /api/time — set the device RTC (offline product, no NTP).

Thin HTTP adapter over DeviceTimeService; the payload must carry **UTC**
(see application/device_time.py for the contract).
"""

from ...application.device_time import ClockUnsupportedError
from ..responses import ok, err
from . import require_json_body


def register(app, device_time_service):

    @app.post("/api/time")
    async def set_time(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            device_time = device_time_service.set_time(body)
        except ValueError as exc:
            return err(str(exc))
        except ClockUnsupportedError as exc:
            return err(str(exc), 501)
        return ok({"device_time": device_time})
