"""
parasha.py
----------
פרשת השבוע.

מחזיר tuple של שמות, למשל ('bereishis',) או ('matos', 'masei').
None = לא רלוונטי לתאריך.

תלויות: hebrew_cal.py (באותה תיקייה).
"""

from .hebrew_cal import (
    gregorian_to_jewish,
    days_in_jewish_year,
    _jewish_year_start_abs,
    _jewish_date_to_abs,
    _jewish_date_from_abs,
    _gregorian_to_abs,
)

# ---------------------------------------------------------------------------
# 54 פרשות — סדר קריאה שנתי
# ---------------------------------------------------------------------------

_UNITS = [
    'bereishis', 'noach', 'lech_lecha', 'vayeira', 'chayei_sarah', 'toldos',
    'vayeitzei', 'vayishlach', 'vayeishev', 'mikeitz', 'vayigash', 'vayechi',
    'shemos', 'vaeirah', 'bo', 'beshalach', 'yisro', 'mishpatim',
    'terumah', 'tetzaveh', 'ki_sisa', 'vayakheil', 'pekudei',
    'vayikra', 'tzav', 'shemini', 'tazria', 'metzora', 'acharei', 'kedoshim',
    'emor', 'behar', 'bechukosai',
    'bamidbar', 'naso', 'behaalosecha', 'shelach', 'korach', 'chukas', 'balak',
    'pinchas', 'matos', 'masei',
    'devarim', 'vaeschanan', 'eikev', 'reei', 'shoftim', 'ki_seitzei', 'ki_savo',
    'nitzavim', 'vayeilech', 'haazinu', 'vezos_haberacha',
]

# ---------------------------------------------------------------------------
# שבתות שמדלגים עליהן (קוראים מפטיר/יו"ט במקום פרשה)
# {חודש: {ימים}}
# ---------------------------------------------------------------------------

_ISRAEL_SKIPS = {
    1: set(range(15, 22)),                         # ניסן 15-21 (פסח ז' ימים)
    3: {6},                                         # סיון ו' (שבועות)
    7: {1, 2, 10} | set(range(15, 22)),            # תשרי: ר"ה, יוה"כ, סוכות
}
_DIASPORA_SKIPS = {
    1: set(range(15, 23)),                          # ניסן 15-22 (פסח ח' ימים)
    3: {6, 7},                                      # סיון ו'-ז' (שבועות ב' ימים)
    7: {1, 2, 10} | set(range(15, 23)),            # תשרי + שמ"ע
}

# ---------------------------------------------------------------------------
# שינויים לפי קביעות
# מפתח: (יום ר"ה, קביעות חשוון-כסלו, יום ניסן א')
# ---------------------------------------------------------------------------

_C = 'chaseirim'
_K = 'kesidran'
_S = 'shelaimim'

_ISRAEL_MODS = {
    (2, _C, 5): [['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _S, 7): [],
    (3, _K, 7): [],
    (5, _C, 1): [],
    (5, _S, 3): [['nitzavim', 'vayeilech']],
    (7, _C, 3): [['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (7, _S, 5): [['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _C, 3): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _S, 5): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (3, _K, 5): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (5, _K, 7): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['matos', 'masei']],
    (5, _S, 1): [['tazria', 'metzora'], ['acharei', 'kedoshim'], ['behar', 'bechukosai'],
                 ['matos', 'masei']],
    (7, _C, 1): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei']],
    (7, _S, 3): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei']],
}

_DIASPORA_MODS = {
    (2, _C, 5): [['chukas', 'balak'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _S, 7): [['matos', 'masei']],
    (3, _K, 7): [['matos', 'masei']],
    (5, _C, 1): [],
    (5, _S, 3): [['nitzavim', 'vayeilech']],
    (7, _C, 3): [['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (7, _S, 5): [['chukas', 'balak'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _C, 3): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
    (2, _S, 5): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['chukas', 'balak'], ['matos', 'masei'],
                 ['nitzavim', 'vayeilech']],
    (3, _K, 5): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['chukas', 'balak'], ['matos', 'masei'],
                 ['nitzavim', 'vayeilech']],
    (5, _K, 7): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei']],
    (5, _S, 1): [['tazria', 'metzora'], ['acharei', 'kedoshim'], ['behar', 'bechukosai'],
                 ['matos', 'masei']],
    (7, _C, 1): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei']],
    (7, _S, 3): [['vayakheil', 'pikudei'], ['tazria', 'metzora'], ['acharei', 'kedoshim'],
                 ['behar', 'bechukosai'], ['matos', 'masei'], ['nitzavim', 'vayeilech']],
}

# ---------------------------------------------------------------------------
# פונקציות עזר
# ---------------------------------------------------------------------------

def _kviah(j_year):
    """
    מחשב קביעות השנה: (יום_ר"ה, סוג_חשוון_כסלו, יום_ניסן_א').
    מחזיר את קביעות השנה הנדרשת לחישוב סדר הפרשות.
    """
    rh_abs   = _jewish_year_start_abs(j_year)
    dow_rh   = rh_abs % 7 + 1        # 1=ראשון ... 7=שבת

    y_days   = days_in_jewish_year(j_year)
    mod      = y_days % 10
    kviah    = _C if mod == 3 else (_K if mod == 4 else _S)

    # ניסן א' — אותו יום בשבוע כמו ניסן ט"ו (פסח) כי 14 = 2×7
    nissan1_abs = _jewish_date_to_abs(j_year, 1, 1)
    dow_pesach  = nissan1_abs % 7 + 1

    return (dow_rh, kviah, dow_pesach)


def _build_units(cycle_year, in_israel):
    """בונה את רשימת הפרשות לשנת המחזור (לאחר שילוב פרשות כפולות)."""
    key  = _kviah(cycle_year)
    mods = (_ISRAEL_MODS if in_israel else _DIASPORA_MODS).get(key, [])

    units = list(_UNITS)
    for pair in mods:
        idx   = units.index(pair[0])
        units = units[:idx] + [pair] + units[idx + 2:]

    return units


def _is_yom_tov_shabbat(abs_date, in_israel):
    """האם שבת זו יוצאת מהמחזור (קוראים מפטיר/יו"ט ולא פרשת השבוע)?"""
    _, j_month, j_day = _jewish_date_from_abs(abs_date)
    skips = _ISRAEL_SKIPS if in_israel else _DIASPORA_SKIPS
    return j_month in skips and j_day in skips[j_month]


def _next_interval_end(start_abs, cycle_end_abs, in_israel):
    """
    מוצא את סוף הפרק הנוכחי: השבת הבאה שאינה יוצאת מהמחזור.
    מדלג על שבתות שבהן קוראים קריאת חג במקום פרשת שבוע.
    """
    dow            = start_abs % 7 + 1
    days_to_shabbat = (7 - dow) % 7
    end_abs        = start_abs + days_to_shabbat

    while end_abs < cycle_end_abs and _is_yom_tov_shabbat(end_abs, in_israel):
        end_abs += 7

    return min(end_abs, cycle_end_abs)

# ---------------------------------------------------------------------------
# ממשק ראשי
# ---------------------------------------------------------------------------

def parasha(year, month, day, in_israel=True):
    """
    מחזיר את פרשת השבוע לתאריך הגרגוריאני הנתון.

    לכל יום בשבוע: הפרשה הנקראת בשבת אותה שבוע.
    לשבת עצמה: הפרשה הנקראת היום.
    לשבת יוצאת מהמחזור (פסח, שבועות וכו'): הפרשה שתיקרא בשבת הבאה.

    מחזיר:
        tuple של מחרוזות — ('bereishis',) או ('matos', 'masei')
        None — אם מחוץ לתחום (לא אמור לקרות בתאריכים 2024-2034)
    """
    target_abs = _gregorian_to_abs(year, month, day)
    j_year, _, _ = gregorian_to_jewish(year, month, day)

    # --- מציאת שנת המחזור ---
    # מחזור מתחיל בתשרי כ"ג (ישראל) או כ"ד (חו"ל) = יום שאחרי שמחת תורה
    anchor_day = 23 if in_israel else 24

    cycle_year = j_year
    if _jewish_date_to_abs(cycle_year, 7, anchor_day) > target_abs:
        cycle_year -= 1

    cycle_start_abs = _jewish_date_to_abs(cycle_year,     7, anchor_day)
    cycle_end_abs   = _jewish_date_to_abs(cycle_year + 1, 7, anchor_day) - 1

    # --- בניית רשימת הפרשות לשנה זו ---
    units = _build_units(cycle_year, in_israel)

    # --- מעבר על הפרקים עד למציאת הפרשה ---
    interval_start = cycle_start_abs
    for unit in units:
        interval_end = _next_interval_end(interval_start, cycle_end_abs, in_israel)

        if interval_start <= target_abs <= interval_end:
            return tuple(unit) if isinstance(unit, list) else (unit,)

        if interval_end >= cycle_end_abs:
            break

        interval_start = interval_end + 1

    return None
