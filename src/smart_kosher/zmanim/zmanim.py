"""
zmanim.py
---------
חישוב 19 זמנים הלכתיים.

כל זמן מוחזר כדקות מחצות UTC (float). None = אין זריחה/שקיעה.
המרה לשעון מקומי: utc_min + utc_offset_hours * 60.

תלויות: astronomy.py (באותה תיקייה).
"""

from .astronomy import (
    _adjusted_zenith,
    _utc_sun_minutes,
    _validate_location,
    julian_day,
    sea_level_zenith,
)

# ---------------------------------------------------------------------------
# זוויות זנית
# ---------------------------------------------------------------------------

_Z_SEA     = sea_level_zenith()      # 90.8333° — זריחה/שקיעה בגובה הים
_Z_ALOT    = 106.1                   # GEOMETRIC_ZENITH + 16.1° — עלות השחר
_Z_TALIT   = 101.5                   # GEOMETRIC_ZENITH + 11.5° — טלית ותפילין
_Z_TZAIS85 = 98.5                    # GEOMETRIC_ZENITH +  8.5° — צאת כוכבים

# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------

def _safe(jd, lat, lon_w, zenith, is_sr):
    try:
        return _utc_sun_minutes(jd, lat, lon_w, zenith, is_sr)
    except (ValueError, ZeroDivisionError):
        return None


def _shaos(start, end, n):
    """
    sha'ot zmaniyot: start + (end-start) * n/12.
    n=3 → סוף זמן שמע, n=6.5 → מנחה גדולה, וכו'.
    """
    if start is None or end is None:
        return None
    return start + (end - start) * n / 12.0

# ---------------------------------------------------------------------------
# ממשק ראשי
# ---------------------------------------------------------------------------

def compute_zmanim(
    year, month, day, lat, lon, altitude=0, candle_offset=18, tzais_offset=40
):
    """
    מחשב את כל 19 הזמנים ההלכתיים לתאריך ומיקום נתונים.

    פרמטרים:
        year, month, day  — תאריך גרגוריאני
        lat               — קו רוחב  (°N חיובי)
        lon               — קו אורך  (°E חיובי)
        altitude          — גובה מעל פני הים (מטרים)
        candle_offset     — דקות לפני שקיעה להדלקת נרות (ברירת מחדל: 18)
        tzais_offset      — דקות אחרי שקיעה לצאת שבת (ברירת מחדל: 40)

    מחזיר dict עם מפתחות:
        alot_hashachar, talit_and_tefillin, netz_hachama,
        sof_zman_shema_gra, sof_zman_shema_mga,
        sof_zman_tfilla_gra, sof_zman_tfilla_mga,
        chatzot_hayom, mincha_gedola, mincha_gedola_30min,
        mincha_ketana, plag_hamincha, shkia,
        tset_hakohavim, tset_hakohavim_shabbat, tset_hakohavim_tsom,
        tset_hakohavim_rabeinu_tam, chatzot_halayla, candle_lighting

    ערכים: דקות מחצות UTC (float) או None.
    """
    _validate_location(lat, lon, altitude)
    if not isinstance(candle_offset, int) or not 0 <= candle_offset <= 1440:
        raise ValueError("candle_offset must be an integer in 0..1440")
    if not isinstance(tzais_offset, int) or not 0 <= tzais_offset <= 1440:
        raise ValueError("tzais_offset must be an integer in 0..1440")
    jd      = julian_day(year, month, day)
    lon_w   = -lon                           # NOAA: מערב חיובי
    z_elev  = _adjusted_zenith(altitude)     # זווית עם תיקון גובה

    # -----------------------------------------------------------------------
    # 1. זריחה/שקיעה — שני מצבים
    # -----------------------------------------------------------------------

    # א) גובה פני הים (ללא תיקון גובה) — לחצות, נרות, שעות זמניות MGA
    sr_sea = _safe(jd, lat, lon_w, _Z_SEA, True)
    ss_sea = _safe(jd, lat, lon_w, _Z_SEA, False)

    # ב) עם תיקון גובה — זריחה/שקיעה עיקריות + שעות זמניות GRA
    sr_elev = _safe(jd, lat, lon_w, z_elev, True)
    ss_elev = _safe(jd, lat, lon_w, z_elev, False)

    # ג) זוויות מיוחדות (ללא תיקונים נוספים — pass-through)
    alot    = _safe(jd, lat, lon_w, _Z_ALOT,    True)   # עלות השחר 16.1°
    talit   = _safe(jd, lat, lon_w, _Z_TALIT,   True)   # טלית 11.5°
    tzais85 = _safe(jd, lat, lon_w, _Z_TZAIS85, False)  # צאת 8.5°

    # -----------------------------------------------------------------------
    # 2. חצות היום — ממוצע זריחה/שקיעה בגובה הים
    #    מחושב כממוצע זריחה ושקיעה בגובה פני הים
    # -----------------------------------------------------------------------
    chatzos = ((sr_sea + ss_sea) / 2.0
               if (sr_sea is not None and ss_sea is not None) else None)

    # -----------------------------------------------------------------------
    # 3. MGA — עלות/צאת 72 דקות (מהזריחה/שקיעה עם תיקון גובה)
    #    מקביל ל-alos_72()/tzais_72() עם use_elevation=True
    # -----------------------------------------------------------------------
    alos72  = (sr_elev - 72.0) if sr_elev is not None else None
    tzais72 = (ss_elev + 72.0) if ss_elev is not None else None

    # -----------------------------------------------------------------------
    # 4. חישוב כל הזמנים
    # -----------------------------------------------------------------------
    return {
        # עלות השחר — 16.1° לפני זריחה (ללא תיקון גובה)
        'alot_hashachar':             alot,

        # זמן טלית ותפילין — 11.5° לפני זריחה (ללא תיקון גובה)
        'talit_and_tefillin':         talit,

        # נץ החמה — עם תיקון גובה
        'netz_hachama':               sr_elev,

        # סוף זמן שמע גר"א — 3 שעות זמניות מהנץ (עם גובה)
        'sof_zman_shema_gra':         _shaos(sr_elev, ss_elev, 3),

        # סוף זמן שמע מג"א — 3 שעות זמניות מעלות (72 דק')
        'sof_zman_shema_mga':         _shaos(alos72, tzais72, 3),

        # סוף זמן תפילה גר"א — 4 שעות זמניות
        'sof_zman_tfilla_gra':        _shaos(sr_elev, ss_elev, 4),

        # סוף זמן תפילה מג"א — 4 שעות זמניות
        'sof_zman_tfilla_mga':        _shaos(alos72, tzais72, 4),

        # חצות היום — ממוצע זריחה/שקיעה בגובה הים
        'chatzot_hayom':              chatzos,

        # מנחה גדולה — 6.5 שעות זמניות מהנץ
        'mincha_gedola':              _shaos(sr_elev, ss_elev, 6.5),

        # מנחה גדולה 30 דקות — חצות + 30 דקות
        'mincha_gedola_30min':        (chatzos + 30.0) if chatzos is not None else None,

        # מנחה קטנה — 9.5 שעות זמניות
        'mincha_ketana':              _shaos(sr_elev, ss_elev, 9.5),

        # פלג המנחה — 10.75 שעות זמניות
        'plag_hamincha':              _shaos(sr_elev, ss_elev, 10.75),

        # שקיעה — עם תיקון גובה
        'shkia':                      ss_elev,

        # צאת כוכבים — 8.5° אחרי שקיעה (ללא תיקון גובה)
        'tset_hakohavim':             tzais85,

        # צאת כוכבים לשבת — 40 דקות אחרי שקיעה (עם גובה)
        'tset_hakohavim_shabbat':     (ss_elev + tzais_offset) if ss_elev is not None else None,

        # צאת כוכבים לתענית — 30 דקות אחרי שקיעה (עם גובה)
        'tset_hakohavim_tsom':        (ss_elev + 30.0) if ss_elev is not None else None,

        # רבינו תם — 72 דקות אחרי שקיעה (עם גובה)
        'tset_hakohavim_rabeinu_tam': (ss_elev + 72.0) if ss_elev is not None else None,

        # חצות הלילה — 12 שעות אחרי חצות היום
        'chatzot_halayla':            (chatzos + 720.0) if chatzos is not None else None,

        # הדלקת נרות — N דקות לפני שקיעה בגובה הים
        'candle_lighting':            (ss_sea - candle_offset) if ss_sea is not None else None,
    }
