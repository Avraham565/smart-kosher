"""
zmanim.py
---------
חישוב 18 זמנים הלכתיים.

כל זמן מוחזר כדקות מחצות UTC (float). None = אין זריחה/שקיעה.
המרה לשעון מקומי: utc_min + utc_offset_hours * 60.

הגדרות הזמנים כאן תואמות את KosherJava 2.5.0, שממנה נגזר המימוש הזה.
tests/data/zmanim_golden.csv.gz מחזיק את התוצאות של הספרייה המקורית
ו-tests/test_zmanim.py מוודא התאמה מולן; ראה tools/zmanim_golden/.

תלויות: astronomy.py (באותה תיקייה).
"""

from .astronomy import (
    _adjusted_zenith,
    _jc,
    _jc_plus_days,
    _solar_noon_utc_minutes,
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

# הדלקת נרות: 18 דקות לפני שקיעה, ברירת המחדל של הספרייה המקורית
# (ZmanimCalendar.candleLightingOffset). ערך אחד לכל הארץ, לא הגדרה ולא נתון
# פר-עיר: אין ממשק לשנות אותו, ה-API דוחה כתיבה אליו, ופרופיל עיר מחזיק
# גאוגרפיה בלבד.
#
# פעם הוא לא היה אף אחד מאלה. cities.json החזיק מספרים פר-עיר (40/20/18)
# שאף אחד בקוד לא קרא, ובמקביל כל composition root החזיק ברירת מחדל משלו —
# כך שאותו תזמון חישב כניסת שבת אחרת תלוי איזה מוצר הריץ אותו.
#
# צאת שבת היתה פעם קבוע מקביל כאן (36 דקות אחרי שקיעה). היא אינה קבוע: הספרייה
# המקורית מחשבת צאת כוכבים לפי זווית ולא לפי דקות, ו-36 היה בסך הכל הערך שאותה
# זווית מקבלת בירושלים בשוויון היום והלילה — מספר של יום אחד בשנה שהוקפא על פני
# כל השנה. ביוני הוא הקדים את צאת השבת בכשש דקות.
CANDLE_OFFSET_MINUTES = 18


def compute_zmanim(year, month, day, lat, lon, altitude=0,
                   candle_offset=CANDLE_OFFSET_MINUTES):
    """
    מחשב את כל 18 הזמנים ההלכתיים לתאריך ומיקום נתונים.

    פרמטרים:
        year, month, day  — תאריך גרגוריאני
        lat               — קו רוחב  (°N חיובי)
        lon               — קו אורך  (°E חיובי)
        altitude          — גובה מעל פני הים (מטרים, אי-שלילי)
        candle_offset     — דקות לפני שקיעה להדלקת נרות (ברירת מחדל: 18,
                            CANDLE_OFFSET_MINUTES — כלל מוצרי לכל הארץ)

    מחזיר dict עם מפתחות:
        alot_hashachar, talit_and_tefillin, netz_hachama,
        sof_zman_shema_gra, sof_zman_shema_mga,
        sof_zman_tfilla_gra, sof_zman_tfilla_mga,
        chatzot_hayom, mincha_gedola, mincha_gedola_30min,
        mincha_ketana, plag_hamincha, shkia,
        tset_hakohavim, tset_hakohavim_shabbat,
        tset_hakohavim_rabeinu_tam, chatzot_halayla, candle_lighting

    ערכים: דקות מחצות UTC (float) או None.
    """
    _validate_location(lat, lon, altitude)
    if not isinstance(candle_offset, int) or not 0 <= candle_offset <= 1440:
        raise ValueError("candle_offset must be an integer in 0..1440")
    jd      = julian_day(year, month, day)
    lon_w   = -lon                           # NOAA: מערב חיובי
    z_elev  = _adjusted_zenith(altitude)     # זווית עם תיקון גובה

    # -----------------------------------------------------------------------
    # 1. זריחה/שקיעה — שני מצבים
    #
    # ההפרדה בין השניים היא הכלל המרכזי של הספרייה המקורית, וקל לטעות בה:
    # getSunrise()/getSunset() תמיד מתוקנות לגובה, אבל כל זמן שנגזר מהן עובר
    # דרך getElevationAdjustedSunrise()/Sunset() שנשלטות ע"י useElevation —
    # והיא כבויה כברירת מחדל. כלומר הספרייה מציגה שקיעה בגובה העיר, ומחשבת
    # את השעות הזמניות מגובה פני הים. אנחנו עושים בדיוק אותו דבר.
    #
    # הנימוק המתועד שם: תיקון הגובה מניח אופק פתוח לים, בעוד שבפועל יש הרים
    # ובניינים במערב — הוא שונה, לא בהכרח מדויק יותר.
    # -----------------------------------------------------------------------

    # א) גובה פני הים — הבסיס לכל זמן נגזר: שעות זמניות, MGA, ר"ת, נרות
    sr_sea = _safe(jd, lat, lon_w, _Z_SEA, True)
    ss_sea = _safe(jd, lat, lon_w, _Z_SEA, False)

    # ב) עם תיקון גובה — הזריחה והשקיעה הנראות, ותו לא
    sr_elev = _safe(jd, lat, lon_w, z_elev, True)
    ss_elev = _safe(jd, lat, lon_w, z_elev, False)

    # ג) זוויות מיוחדות — לעולם ללא תיקון גובה. adjustZenith() במקור מתקן
    #    אך ורק כאשר הזווית היא בדיוק 90°, כך שזווית מפורשת עוברת כמו שהיא.
    alot    = _safe(jd, lat, lon_w, _Z_ALOT,    True)   # עלות השחר 16.1°
    talit   = _safe(jd, lat, lon_w, _Z_TALIT,   True)   # טלית 11.5°
    tzais85 = _safe(jd, lat, lon_w, _Z_TZAIS85, False)  # צאת 8.5°

    # -----------------------------------------------------------------------
    # 2. חצות — מעבר השמש במרידיאן
    #
    # לא ממוצע זריחה/שקיעה. זו נקודת השיא האמיתית של השמש, שאינה תלויה כלל
    # בקו הרוחב או בגובה — רק בקו האורך ובמשוואת הזמן. חצות הלילה הוא אמצע
    # הדרך אל חצות של מחר, ולא חצות ועוד 12 שעות: היממה השמשית אינה 24 שעות
    # מדויקות, ואורכה משתנה לאורך השנה.
    # -----------------------------------------------------------------------
    jc           = _jc(jd)
    chatzos      = _solar_noon_utc_minutes(jc, lon_w)
    chatzos_next = _solar_noon_utc_minutes(_jc_plus_days(jc, 1.0), lon_w) + 1440.0
    chatzot_night = chatzos + (chatzos_next - chatzos) / 2.0

    # -----------------------------------------------------------------------
    # 3. MGA — עלות/צאת 72 דקות מגובה פני הים (alos_72/tzais_72)
    # -----------------------------------------------------------------------
    alos72  = (sr_sea - 72.0) if sr_sea is not None else None
    tzais72 = (ss_sea + 72.0) if ss_sea is not None else None

    # -----------------------------------------------------------------------
    # 4. חישוב כל הזמנים
    # -----------------------------------------------------------------------
    return {
        # עלות השחר — 16.1° לפני זריחה (ללא תיקון גובה)
        'alot_hashachar':             alot,

        # זמן טלית ותפילין — 11.5° לפני זריחה (ללא תיקון גובה)
        'talit_and_tefillin':         talit,

        # נץ החמה — הזריחה הנראית, עם תיקון גובה
        'netz_hachama':               sr_elev,

        # סוף זמן שמע גר"א — 3 שעות זמניות מהזריחה (גובה פני הים)
        'sof_zman_shema_gra':         _shaos(sr_sea, ss_sea, 3),

        # סוף זמן שמע מג"א — 3 שעות זמניות מעלות (72 דק')
        'sof_zman_shema_mga':         _shaos(alos72, tzais72, 3),

        # סוף זמן תפילה גר"א — 4 שעות זמניות
        'sof_zman_tfilla_gra':        _shaos(sr_sea, ss_sea, 4),

        # סוף זמן תפילה מג"א — 4 שעות זמניות
        'sof_zman_tfilla_mga':        _shaos(alos72, tzais72, 4),

        # חצות היום — מעבר השמש במרידיאן
        'chatzot_hayom':              chatzos,

        # מנחה גדולה — 6.5 שעות זמניות מהזריחה
        'mincha_gedola':              _shaos(sr_sea, ss_sea, 6.5),

        # מנחה גדולה 30 דקות — חצות + 30 דקות
        'mincha_gedola_30min':        chatzos + 30.0,

        # מנחה קטנה — 9.5 שעות זמניות
        'mincha_ketana':              _shaos(sr_sea, ss_sea, 9.5),

        # פלג המנחה — 10.75 שעות זמניות
        'plag_hamincha':              _shaos(sr_sea, ss_sea, 10.75),

        # שקיעה — השקיעה הנראית, עם תיקון גובה
        'shkia':                      ss_elev,

        # צאת כוכבים — 8.5° אחרי שקיעה
        'tset_hakohavim':             tzais85,

        # צאת שבת — אותה זווית 8.5°, ובכוונה מפתח נפרד ולא כפילות: זהו המושג
        # המוצרי "מתי שבת יוצאת", והוא זה שתזמונים שמורים מצביעים עליו. אם
        # ייבחר בעתיד שיעור מחמיר יותר לצאת שבת, משנים כאן בלבד וכל התזמונים
        # עוברים איתו. הספרייה המקורית אינה מכירה מושג כזה ומחזיקה tzais אחד.
        'tset_hakohavim_shabbat':     tzais85,

        # רבינו תם — 72 דקות אחרי שקיעה (גובה פני הים)
        'tset_hakohavim_rabeinu_tam': tzais72,

        # חצות הלילה — אמצע הדרך אל חצות של מחר
        'chatzot_halayla':            chatzot_night,

        # הדלקת נרות — N דקות לפני שקיעה בגובה הים
        'candle_lighting':            (ss_sea - candle_offset) if ss_sea is not None else None,
    }
