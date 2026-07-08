"""Route for /api/today — Hebrew date, day flags, and zmanim in local time."""

from ..responses import ok, err


def _parse_date(raw):
    parts = raw.split("-")
    if len(parts) != 3:
        raise ValueError("date must be YYYY-MM-DD")
    return int(parts[0]), int(parts[1]), int(parts[2])


def register(app, settings_store, views):

    @app.get("/api/today")
    async def get_today(req):
        raw = req.args.get("date")
        try:
            settings = settings_store.get()
            if raw:
                year, month, day = _parse_date(raw)
            else:
                year, month, day = views.local_today(settings)
            return ok(views.today_view(settings, year, month, day))
        except (KeyError, TypeError, ValueError) as exc:
            return err(str(exc))
