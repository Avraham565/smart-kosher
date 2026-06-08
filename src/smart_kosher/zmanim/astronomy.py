"""
astronomy.py
------------
חישוב זריחה, חצות שמש ושקיעה.
אלגוריתם: NOAA Solar Calculator.

תואם MicroPython ו-CPython. תלות יחידה: math (מובנה).
ממשק: sun_times() מחזיר דקות מחצות UTC (float).
"""

import math

# ---------------------------------------------------------------------------
# קבועים
# ---------------------------------------------------------------------------

_EARTH_RADIUS_KM  = 6356.9
_SOLAR_RADIUS_DEG = 16.0 / 60.0   # 0.2667°
_REFRACTION_DEG   = 34.0 / 60.0   # 0.5667°
_J2000            = 2451545.0
_DAYS_PER_CENTURY = 36525.0


def _validate_gregorian_date(year, month, day):
    if not isinstance(year, int) or year < 1:
        raise ValueError("year must be a positive integer")
    if not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("month must be in 1..12")
    if not isinstance(day, int):
        raise ValueError("day must be an integer")
    month_days = (31, 29 if ((year % 4 == 0 and year % 100 != 0) or year % 400 == 0) else 28,
                  31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not 1 <= day <= month_days[month - 1]:
        raise ValueError("day is outside the selected month")


def _validate_location(lat, lon, altitude=0):
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be in -90..90")
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be in -180..180")
    if altitude < 0:
        raise ValueError("altitude must be non-negative")

# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------

def _deg(r): return r * 180.0 / math.pi
def _rad(d): return d * math.pi / 180.0

# ---------------------------------------------------------------------------
# Julian Day
# ---------------------------------------------------------------------------

def julian_day(year, month, day):
    """Julian Day Number בחצות UTC לתאריך נתון."""
    _validate_gregorian_date(year, month, day)
    y, m = (year - 1, month + 12) if month <= 2 else (year, month)
    A = y // 100
    B = 2 - A + A // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + B - 1524.5

# ---------------------------------------------------------------------------
# פונקציות עמדת שמש (Julian Centuries)
# ---------------------------------------------------------------------------

def _jc(jd):
    return (jd - _J2000) / _DAYS_PER_CENTURY

def _jd_from_jc(jc):
    return jc * _DAYS_PER_CENTURY + _J2000

def _mean_longitude(jc):
    return (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0

def _mean_anomaly(jc):
    return (357.52911 + jc * (35999.05029 - jc * 0.0001537)) % 360.0

def _eccentricity(jc):
    return 0.016708634 - jc * (0.000042037 + jc * 0.0000001267)

def _equation_of_center(jc):
    mr = _rad(_mean_anomaly(jc))
    return (math.sin(mr)       * (1.914602 - jc * (0.004817 + jc * 0.000014))
          + math.sin(2.0 * mr) * (0.019993 - jc * 0.000101)
          + math.sin(3.0 * mr) *  0.000289)

def _true_longitude(jc):
    return _mean_longitude(jc) + _equation_of_center(jc)

def _apparent_longitude(jc):
    omega = 125.04 - 1934.136 * jc
    return _true_longitude(jc) - 0.00569 - 0.00478 * math.sin(_rad(omega))

def _mean_obliquity(jc):
    s = 21.448 - jc * (46.8150 + jc * (0.00059 - jc * 0.001813))
    return 23.0 + (26.0 + s / 60.0) / 60.0

def _obliquity_correction(jc):
    omega = 125.04 - 1934.136 * jc
    return _mean_obliquity(jc) + 0.00256 * math.cos(_rad(omega))

def _declination(jc):
    corr = _rad(_obliquity_correction(jc))
    app  = _rad(_apparent_longitude(jc))
    return _deg(math.asin(math.sin(corr) * math.sin(app)))

def _equation_of_time(jc):
    eps  = _rad(_obliquity_correction(jc))
    L0r  = _rad(_mean_longitude(jc))
    Mr   = _rad(_mean_anomaly(jc))
    eoe  = _eccentricity(jc)
    y    = math.tan(eps / 2.0) ** 2
    return 4.0 * _deg(
          y * math.sin(2.0 * L0r)
        - 2.0 * eoe * math.sin(Mr)
        + 4.0 * eoe * y * math.sin(Mr) * math.cos(2.0 * L0r)
        - 0.5 * y * y * math.sin(4.0 * L0r)
        - 1.25 * eoe * eoe * math.sin(2.0 * Mr)
    )

# ---------------------------------------------------------------------------
# חצות שמש — two-pass לדיוק
# ---------------------------------------------------------------------------

def _solar_noon_utc_minutes(jc, lon_west):
    """חצות שמש בדקות UTC. lon_west: קו אורך מערבי-חיובי."""
    jd_start = _jd_from_jc(jc)

    # pass 1
    approx_jc  = _jc(jd_start + lon_west / 360.0)
    approx_eot = _equation_of_time(approx_jc)
    approx_noon = 720.0 + lon_west * 4.0 - approx_eot

    # pass 2
    refined_jc  = _jc(jd_start - 0.5 + approx_noon / 1440.0)
    refined_eot = _equation_of_time(refined_jc)
    return 720.0 + lon_west * 4.0 - refined_eot

# ---------------------------------------------------------------------------
# חישוב זריחה/שקיעה — two-pass לדיוק
# ---------------------------------------------------------------------------

def _hour_angle(lat, solar_dec, zenith):
    """זווית שעה בדרגות (תמיד חיובית)."""
    cos_ha = (math.cos(_rad(zenith))
              / (math.cos(_rad(lat)) * math.cos(_rad(solar_dec)))
              - math.tan(_rad(lat)) * math.tan(_rad(solar_dec)))
    return _deg(math.acos(cos_ha))   # מעלה ValueError אם cos_ha מחוץ לתחום [-1,1]

def _approx_utc_minutes(approx_jc, lat, lon_west, zenith, is_sunrise):
    """חישוב בודד של זריחה/שקיעה (דקות UTC) מנקודת פתיחה נתונה."""
    eot  = _equation_of_time(approx_jc)
    dec  = _declination(approx_jc)
    ha   = _hour_angle(lat, dec, zenith)
    if not is_sunrise:
        ha = -ha
    delta = lon_west - ha
    return 720.0 + delta * 4.0 - eot

def _utc_sun_minutes(jd, lat, lon_west, zenith, is_sunrise):
    """
    Two-pass NOAA: חישוב זריחה או שקיעה בדקות מחצות UTC.
    מעלה ValueError אם אין זריחה/שקיעה (יום/לילה קוטבי).
    """
    jc = _jc(jd)

    # pass 1: מתחיל מחצות שמש
    noon_min = _solar_noon_utc_minutes(jc, lon_west)
    jc1      = _jc(jd + noon_min / 1440.0)
    first    = _approx_utc_minutes(jc1, lat, lon_west, zenith, is_sunrise)

    # pass 2: מחדד את התוצאה
    jc2      = _jc(jd + first / 1440.0)
    return _approx_utc_minutes(jc2, lat, lon_west, zenith, is_sunrise)

# ---------------------------------------------------------------------------
# תיקון גובה
# ---------------------------------------------------------------------------

def _elevation_adjustment_deg(altitude_m):
    """תיקון שקיעת אופק בגלל גובה (מטרים). נוסחת arccos(R/(R+h))."""
    if altitude_m <= 0:
        return 0.0
    return _deg(math.acos(_EARTH_RADIUS_KM / (_EARTH_RADIUS_KM + altitude_m / 1000.0)))

def _adjusted_zenith(altitude_m):
    """זווית זנית מתוקנת: 90° + רדיוס שמש + רפרקציה + שקיעת אופק."""
    return 90.0 + _SOLAR_RADIUS_DEG + _REFRACTION_DEG + _elevation_adjustment_deg(altitude_m)

# ---------------------------------------------------------------------------
# ממשק ראשי
# ---------------------------------------------------------------------------

def sun_times(year, month, day, lat, lon, altitude=0):
    """
    מחשב זריחה, חצות שמש ושקיעה.

    פרמטרים:
        year, month, day — תאריך גרגוריאני
        lat              — קו רוחב  (°N חיובי, °S שלילי)
        lon              — קו אורך  (°E חיובי, °W שלילי)
        altitude         — גובה מעל פני הים (מטרים)

    מחזיר:
        (sunrise_utc, solar_noon_utc, sunset_utc) — דקות מחצות UTC (float)
        (None, solar_noon_utc, None)               — יום/לילה קוטבי
    """
    _validate_location(lat, lon, altitude)
    jd       = julian_day(year, month, day)
    lon_west = -lon                          # NOAA: מערב חיובי
    zenith   = _adjusted_zenith(altitude)

    jc = _jc(jd)
    noon = _solar_noon_utc_minutes(jc, lon_west)

    try:
        sr = _utc_sun_minutes(jd, lat, lon_west, zenith, is_sunrise=True)
    except ValueError:
        sr = None

    try:
        ss = _utc_sun_minutes(jd, lat, lon_west, zenith, is_sunrise=False)
    except ValueError:
        ss = None

    return sr, noon, ss

# ---------------------------------------------------------------------------
# המרות עזר
# ---------------------------------------------------------------------------

def utc_sun_time(year, month, day, lat, lon, zenith, is_sunrise):
    """
    חישוב זמן שמש UTC עם זווית זנית ספציפית — ללא תיקונים נוספים.
    משמש לחישוב עלות השחר (zenith=106.1°), צאת כוכבים בזוויות (zenith=98.5°) וכו'.
    מחזיר דקות מחצות UTC (float) או None.
    """
    _validate_location(lat, lon)
    jd = julian_day(year, month, day)
    try:
        return _utc_sun_minutes(jd, lat, -lon, zenith, is_sunrise)
    except (ValueError, ZeroDivisionError):
        return None


def sea_level_zenith():
    """זווית זנית בגובה פני הים: 90° + רדיוס שמש + רפרקציה."""
    return 90.0 + _SOLAR_RADIUS_DEG + _REFRACTION_DEG


def minutes_to_hms(minutes):
    """דקות מחצות (float) → (hour, minute, second). עובד גם על ערכים שליליים."""
    total = int(round(minutes * 60)) % 86400
    return total // 3600, (total % 3600) // 60, total % 60

def hms_to_minutes(h, m, s=0):
    return h * 60.0 + m + s / 60.0
