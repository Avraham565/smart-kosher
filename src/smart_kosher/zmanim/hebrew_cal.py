"""
hebrew_cal.py
-------------
לוח עברי: המרת תאריכים, חגים, עומר, יום בשבוע.

תואם MicroPython ו-CPython. ללא תלויות חיצוניות.
"""

# ---------------------------------------------------------------------------
# קבועים — זהים ל-JewishDate
# ---------------------------------------------------------------------------

_JEWISH_EPOCH        = -1373429
_CHALAKIM_PER_MINUTE =  18
_CHALAKIM_PER_HOUR   =  18 * 60          # 1,080
_CHALAKIM_PER_DAY    =  _CHALAKIM_PER_HOUR * 24    # 25,920
_CHALAKIM_PER_MONTH  =  int(_CHALAKIM_PER_DAY * 29.5) + 793   # 765,433
_CHALAKIM_MOLAD_TOHU =  _CHALAKIM_PER_DAY + (_CHALAKIM_PER_HOUR * 5) + 204  # 31,524

# ימים לפני כל חודש גרגוריאני (ינואר=1)
_DAYS_BEFORE_MONTH = (0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)

# ---------------------------------------------------------------------------
# גרגוריאני
# ---------------------------------------------------------------------------

def _is_gregorian_leap(year):
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def _gregorian_to_abs(year, month, day):
    """
    ממיר תאריך גרגוריאני למספר מוחלט (= Python date.toordinal()).
    Jan 1, year 1 = 1.
    """
    if not isinstance(year, int) or year < 1:
        raise ValueError("year must be a positive integer")
    if not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("month must be in 1..12")
    if not isinstance(day, int):
        raise ValueError("day must be an integer")
    month_days = (31, 29 if _is_gregorian_leap(year) else 28,
                  31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not 1 <= day <= month_days[month - 1]:
        raise ValueError("day is outside the selected month")

    y = year - 1
    d = _DAYS_BEFORE_MONTH[month]
    if month > 2 and _is_gregorian_leap(year):
        d += 1
    return y * 365 + y // 4 - y // 100 + y // 400 + d + day


def _abs_to_gregorian(n):
    """
    ממיר מספר מוחלט לתאריך גרגוריאני (year, month, day).
    מקביל ל-date.fromordinal(n). n=1 → (1, 1, 1).
    """
    # הערכת שנה ותיקון קטן אם צריך (בד"כ 0-1 איטרציות)
    year = (n - 1) // 365 + 1
    while _gregorian_to_abs(year + 1, 1, 1) <= n:
        year += 1
    while _gregorian_to_abs(year, 1, 1) > n:
        year -= 1

    # יום בשנה (0-מבוסס)
    doy = n - _gregorian_to_abs(year, 1, 1)

    # מציאת חודש (מהסוף לתחילה)
    for month in range(12, 0, -1):
        preceding = _DAYS_BEFORE_MONTH[month]
        if month > 2 and _is_gregorian_leap(year):
            preceding += 1
        if doy >= preceding:
            return year, month, doy - preceding + 1

    return year, 1, doy + 1  # fallback (לא אמור לקרות)


def day_of_week(year, month, day):
    """
    יום בשבוע (1=ראשון ... 7=שבת) לתאריך גרגוריאני נתון.
    """
    return _gregorian_to_abs(year, month, day) % 7 + 1


def gregorian_day_number(year, month, day):
    """מחזיר מספר יום רציף; 1 בינואר 1 הוא יום 1."""
    return _gregorian_to_abs(year, month, day)


def gregorian_from_day_number(day_number):
    """ממיר מספר יום רציף לתאריך גרגוריאני."""
    if not isinstance(day_number, int) or day_number < 1:
        raise ValueError("day_number must be a positive integer")
    return _abs_to_gregorian(day_number)


def add_gregorian_days(year, month, day, days):
    """מוסיף מספר שלם של ימים לתאריך גרגוריאני."""
    if not isinstance(days, int):
        raise ValueError("days must be an integer")
    return gregorian_from_day_number(_gregorian_to_abs(year, month, day) + days)

# ---------------------------------------------------------------------------
# לוח עברי — פונקציות ליבה
# ---------------------------------------------------------------------------

def is_jewish_leap_year(year):
    """שנה מעוברת?"""
    return ((7 * year) + 1) % 19 < 7


def months_in_jewish_year(year):
    return 13 if is_jewish_leap_year(year) else 12


def _month_number_from_tishrei(year, month):
    """מיקום החודש בשנה כאשר תשרי=1."""
    leap = is_jewish_leap_year(year)
    return 1 + ((month + (6 if leap else 5)) % (13 if leap else 12))


def _chalakim_since_molad_tohu(year, month):
    prev_year = year - 1
    months = _month_number_from_tishrei(year, month) - 1
    cycles, remainder = divmod(prev_year, 19)
    months += (235 * cycles +
               12 * remainder +
               int(((7 * remainder) + 1) / 19))
    return _CHALAKIM_MOLAD_TOHU + (_CHALAKIM_PER_MONTH * months)


def _molad_components_for_year(year):
    chalakim = _chalakim_since_molad_tohu(year, 7)
    days, remainder = divmod(chalakim, _CHALAKIM_PER_DAY)
    return int(days), int(remainder)


def _dechiyos_count(year, days, remainder):
    count = 0
    rosh_hashana_day = (days + 1) % 7
    if (remainder >= 19440) or \
       (rosh_hashana_day == 3 and remainder >= 9924  and not is_jewish_leap_year(year)) or \
       (rosh_hashana_day == 2 and remainder >= 16789 and is_jewish_leap_year(year - 1)):
        count = 1
    if ((rosh_hashana_day + count) % 7) in (1, 4, 6):
        count += 1
    return count


_CACHE_LIMIT = 32


def _store_bounded(cache, key, value):
    if key not in cache and len(cache) >= _CACHE_LIMIT:
        del cache[min(cache)]
    cache[key] = value
    return value


_cache_elapsed = {}   # cache לחישוב יקר — קריטי לביצועים ב-MicroPython

def _jewish_calendar_elapsed_days(year):
    if year not in _cache_elapsed:
        days, remainder = _molad_components_for_year(year)
        _store_bounded(_cache_elapsed, year, days + _dechiyos_count(year, days, remainder))
    return _cache_elapsed[year]


_cache_year_days = {}

def days_in_jewish_year(year):
    if year not in _cache_year_days:
        _store_bounded(
            _cache_year_days,
            year,
            _jewish_calendar_elapsed_days(year + 1) - _jewish_calendar_elapsed_days(year),
        )
    return _cache_year_days[year]


def is_cheshvan_long(year):
    return days_in_jewish_year(year) % 10 == 5


def is_kislev_short(year):
    return days_in_jewish_year(year) % 10 == 3


def days_in_jewish_month(month, year):
    """
    מספר ימים בחודש עברי.
    month: 1=ניסן ... 12=אדר ... 13=אדר ב'.
    """
    if month in (2, 4, 6, 10, 13):          # אייר, תמוז, אלול, טבת, אדר ב
        return 29
    if month == 8 and not is_cheshvan_long(year):   # חשוון קצר
        return 29
    if month == 9 and is_kislev_short(year):         # כסלו קצר
        return 29
    if month == 12 and not is_jewish_leap_year(year): # אדר בשנה פשוטה
        return 29
    return 30


_cache_months = {}

def sorted_months_in_jewish_year(year):
    """
    חודשי השנה בסדר כרונולוגי — תשרי ראשון.
    דוגמה (שנה פשוטה): [7,8,9,10,11,12,1,2,3,4,5,6]
    """
    if year not in _cache_months:
        n = months_in_jewish_year(year)
        months = list(range(1, n + 1))
        _store_bounded(
            _cache_months,
            year,
            sorted(months, key=lambda m: (0 if m >= 7 else 1, m)),
        )
    return _cache_months[year]


# ---------------------------------------------------------------------------
# המרות תאריך
# ---------------------------------------------------------------------------

def _jewish_year_start_abs(year):
    return _jewish_calendar_elapsed_days(year) + _JEWISH_EPOCH + 1


def _jewish_date_to_abs(year, month, day):
    if not isinstance(year, int) or year < 1:
        raise ValueError("Jewish year must be a positive integer")
    if not isinstance(month, int) or month not in sorted_months_in_jewish_year(year):
        raise ValueError("invalid Jewish month for the selected year")
    if not isinstance(day, int) or not 1 <= day <= days_in_jewish_month(month, year):
        raise ValueError("invalid Jewish day for the selected month")
    months = sorted_months_in_jewish_year(year)
    month_idx = months.index(month)
    prior = sum(days_in_jewish_month(m, year) for m in months[:month_idx])
    return prior + day + _jewish_year_start_abs(year) - 1


def _jewish_date_from_abs(abs_date):
    # הערכת שנה
    year = int((abs_date - _JEWISH_EPOCH) / 366)
    while abs_date >= _jewish_year_start_abs(year + 1):
        year += 1
    while abs_date < _jewish_year_start_abs(year):
        year -= 1

    months = sorted_months_in_jewish_year(year)
    # מציאת חודש
    month = months[-1]
    for i in range(len(months) - 1):
        if abs_date < _jewish_date_to_abs(year, months[i + 1], 1):
            month = months[i]
            break

    day = abs_date - _jewish_date_to_abs(year, month, 1) + 1
    return year, month, day


def gregorian_to_jewish(year, month, day):
    """
    ממיר תאריך גרגוריאני לתאריך עברי.
    מחזיר (j_year, j_month, j_day).
    j_month: 1=ניסן, 7=תשרי, 12=אדר, 13=אדר ב'.
    """
    return _jewish_date_from_abs(_gregorian_to_abs(year, month, day))


def jewish_to_gregorian(j_year, j_month, j_day):
    """
    ממיר תאריך עברי לגרגוריאני.
    מחזיר (year, month, day).
    """
    return _abs_to_gregorian(_jewish_date_to_abs(j_year, j_month, j_day))

# ---------------------------------------------------------------------------
# ימים מיוחדים
# ---------------------------------------------------------------------------

def significant_day(j_year, j_month, j_day, dow, in_israel=True):
    """
    מחזיר שם היום המיוחד (string) או None.
    dow: יום בשבוע (1=ראשון ... 7=שבת).
    in_israel: האם בארץ ישראל.

    שמות אפשריים:
    erev_rosh_hashana, rosh_hashana, tzom_gedalyah,
    erev_yom_kippur, yom_kippur,
    erev_succos, succos, chol_hamoed_succos, hoshana_rabbah,
    shemini_atzeres, simchas_torah,
    chanukah, tenth_of_teves, tu_beshvat,
    taanis_esther, purim, shushan_purim, purim_katan, shushan_purim_katan,
    erev_pesach, pesach, chol_hamoed_pesach, pesach_sheni,
    lag_baomer, erev_shavuos, shavuos,
    seventeen_of_tammuz, tisha_beav, tu_beav
    """
    leap = is_jewish_leap_year(j_year)

    if j_month == 7:      # תשרי
        if j_day in (1, 2):
            return 'rosh_hashana'
        if (j_day == 3 and dow != 7) or (j_day == 4 and dow == 1):
            return 'tzom_gedalyah'
        if j_day == 9:
            return 'erev_yom_kippur'
        if j_day == 10:
            return 'yom_kippur'
        if j_day == 14:
            return 'erev_succos'
        if j_day == 15 or (j_day == 16 and not in_israel):
            return 'succos'
        if 16 <= j_day <= 20:
            return 'chol_hamoed_succos'
        if j_day == 21:
            return 'hoshana_rabbah'
        if j_day == 22:
            return 'shemini_atzeres'
        if j_day == 23 and not in_israel:
            return 'simchas_torah'

    elif j_month == 6:    # אלול
        if j_day == 29:
            return 'erev_rosh_hashana'

    elif j_month == 9:    # כסלו
        if j_day >= 25:
            return 'chanukah'

    elif j_month == 10:   # טבת
        chanukah_days = [1, 2] + ([3] if is_kislev_short(j_year) else [])
        if j_day in chanukah_days:
            return 'chanukah'
        if j_day == 10:
            return 'tenth_of_teves'

    elif j_month == 11:   # שבט
        if j_day == 15:
            return 'tu_beshvat'

    elif j_month == 12:   # אדר (או אדר א' בשנה מעוברת)
        if leap:
            if j_day == 14:
                return 'purim_katan'
            if j_day == 15:
                return 'shushan_purim_katan'
        else:
            return _purim_significant_day(j_day, dow)

    elif j_month == 13:   # אדר ב'
        return _purim_significant_day(j_day, dow)

    elif j_month == 1:    # ניסן
        if j_day == 14:
            return 'erev_pesach'
        pesach_days = [15, 21] + ([16, 22] if not in_israel else [])
        if j_day in pesach_days:
            return 'pesach'
        if 16 <= j_day <= 20:
            return 'chol_hamoed_pesach'

    elif j_month == 2:    # אייר
        if j_day == 14:
            return 'pesach_sheni'
        if j_day == 18:
            return 'lag_baomer'

    elif j_month == 3:    # סיון
        if j_day == 5:
            return 'erev_shavuos'
        shavuos_days = [6] + ([7] if not in_israel else [])
        if j_day in shavuos_days:
            return 'shavuos'

    elif j_month == 4:    # תמוז
        if (j_day == 17 and dow != 7) or (j_day == 18 and dow == 1):
            return 'seventeen_of_tammuz'

    elif j_month == 5:    # אב
        if (j_day == 9 and dow != 7) or (j_day == 10 and dow == 1):
            return 'tisha_beav'
        if j_day == 15:
            return 'tu_beav'

    return None


def _purim_significant_day(j_day, dow):
    if (j_day == 13 and dow != 7) or (j_day == 11 and dow == 5):
        return 'taanis_esther'
    if j_day == 14:
        return 'purim'
    if j_day == 15:
        return 'shushan_purim'
    return None


_YOM_TOV_ASSUR = frozenset([
    'pesach', 'shavuos', 'rosh_hashana', 'yom_kippur',
    'succos', 'shemini_atzeres', 'simchas_torah'
])


def is_yom_tov_assur_bemelacha(sig_day):
    return sig_day in _YOM_TOV_ASSUR


def is_assur_bemelacha(dow, sig_day):
    """
    האם יום זה אסור במלאכה?
    dow: יום בשבוע (7=שבת).
    """
    return dow == 7 or is_yom_tov_assur_bemelacha(sig_day)


def is_yom_tov(sig_day):
    if sig_day is None:
        return False
    return (not sig_day.startswith('erev_')
            and sig_day not in ('seventeen_of_tammuz', 'tisha_beav',
                                'tzom_gedalyah', 'tenth_of_teves', 'taanis_esther'))



def is_chol_hamoed(sig_day):
    if sig_day is None:
        return False
    return sig_day.startswith('chol_hamoed_') or sig_day == 'hoshana_rabbah'


def is_taanis(sig_day):
    return sig_day in ('seventeen_of_tammuz', 'tisha_beav', 'tzom_gedalyah',
                       'yom_kippur', 'tenth_of_teves', 'taanis_esther')


def is_rosh_chodesh(j_month, j_day):
    return j_day == 30 or (j_day == 1 and j_month != 7)


# ---------------------------------------------------------------------------
# עומר
# ---------------------------------------------------------------------------

def day_of_omer(j_month, j_day):
    """
    יום ספירת העומר (1-49) או None.
    """
    if j_month == 1 and j_day > 15:
        return j_day - 15
    if j_month == 2:
        return j_day + 15
    if j_month == 3 and j_day < 6:
        return j_day + 44
    return None


# ---------------------------------------------------------------------------
# ממשק ראשי
# ---------------------------------------------------------------------------

def date_info(year, month, day, in_israel=True):
    """
    מחזיר dict עם כל המידע על תאריך נתון.

    פרמטרים:
        year, month, day — תאריך גרגוריאני
        in_israel        — האם בארץ ישראל (משפיע על חגים)

    מחזיר:
        {
          'j_year': int, 'j_month': int, 'j_day': int,
          'dow': int,           # 1=ראשון ... 7=שבת
          'significant_day': str or None,
          'is_assur_bemelacha': bool,
          'is_yom_tov': bool,
          'is_erev_yom_tov': bool,             # מחר יום טוב אסור במלאכה
          'is_motzei_assur_bemelacha': bool,   # היום אסור AND מחר לא אסור
          'is_chol_hamoed': bool,
          'is_taanis': bool,
          'is_rosh_chodesh': bool,
          'is_shabbat': bool,
          'day_of_omer': int or None,
        }
    """
    j_year, j_month, j_day = gregorian_to_jewish(year, month, day)
    dow = day_of_week(year, month, day)
    sig = significant_day(j_year, j_month, j_day, dow, in_israel)
    omer = day_of_omer(j_month, j_day)
    _assur = is_assur_bemelacha(dow, sig)

    tomorrow_dow = dow % 7 + 1
    t_j_year, t_j_month, t_j_day = _jewish_date_from_abs(_gregorian_to_abs(year, month, day) + 1)
    tomorrow_sig = significant_day(t_j_year, t_j_month, t_j_day, tomorrow_dow, in_israel)
    tomorrow_assur = is_assur_bemelacha(tomorrow_dow, tomorrow_sig)

    return {
        'j_year':             j_year,
        'j_month':            j_month,
        'j_day':              j_day,
        'dow':                dow,
        'significant_day':    sig,
        'is_assur_bemelacha':        _assur,
        'is_yom_tov':                is_yom_tov(sig),
        'is_erev_yom_tov':           tomorrow_sig in _YOM_TOV_ASSUR,
        'is_motzei_assur_bemelacha': _assur and not tomorrow_assur,
        'is_chol_hamoed':            is_chol_hamoed(sig),
        'is_taanis':                 is_taanis(sig),
        'is_rosh_chodesh':           is_rosh_chodesh(j_month, j_day),
        'is_shabbat':                dow == 7,
        'day_of_omer':               omer,
    }
