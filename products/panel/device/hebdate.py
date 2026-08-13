# Hebrew date presentation -- turns the brain's numeric Jewish date
# (j_year, j_month, j_day, dow) into display text (gematria + month/day names).
#
# The brain (zmanim) is numeric on purpose; formatting is a UI concern, so it
# lives here. Pure Python (no LVGL), so it is unit-tested on CPython.
#
# Month numbering matches hebrew_cal.date_info: 1=ניסן, 7=תשרי, 12=אדר,
# 13=אדר ב׳. In a leap year month 12 reads אדר א׳.

_ONES = ("", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט")
_TENS = ("", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ")
_HUNDREDS = ("", "ק", "ר", "ש", "ת", "תק", "תר", "תש", "תת", "תתק")

_MONTHS = {
    1: "ניסן", 2: "אייר", 3: "סיון", 4: "תמוז", 5: "אב", 6: "אלול",
    7: "תשרי", 8: "חשון", 9: "כסלו", 10: "טבת", 11: "שבט",
    12: "אדר", 13: "אדר ב׳",
}
_DOW = {1: "יום א׳", 2: "יום ב׳", 3: "יום ג׳", 4: "יום ד׳",
        5: "יום ה׳", 6: "יום ו׳", 7: "שבת"}


def _gematria(n):
    """Hebrew numeral letters for 1..999 (no punctuation). 15/16 use טו/טז."""
    out = _HUNDREDS[n // 100]
    n %= 100
    if n == 15:
        return out + "טו"
    if n == 16:
        return out + "טז"
    return out + _TENS[n // 10] + _ONES[n % 10]


def _punct(letters):
    """Add geresh (׳) to a single letter, gershayim (״) before the last."""
    if len(letters) <= 1:
        return letters + "׳"
    return letters[:-1] + "״" + letters[-1]


def _is_leap(j_year):
    return (7 * j_year + 1) % 19 < 7


def month_name(j_month, j_year):
    if j_month == 12 and _is_leap(j_year):
        return "אדר א׳"
    return _MONTHS.get(j_month, "")


def day_of_week(dow):
    return _DOW.get(dow, "")


def date_str(j_year, j_month, j_day):
    """e.g. (5786, 5, 15) -> 'ט״ו באב תשפ״ו'. Year drops the 5000s (א׳ אלפים)."""
    return "{} ב{} {}".format(
        _punct(_gematria(j_day)),
        month_name(j_month, j_year),
        _punct(_gematria(j_year % 1000)))


# Parasha transliterations (from zmanim.parasha._UNITS) -> Hebrew.
_PARASHA = {
    "bereishis": "בראשית", "noach": "נח", "lech_lecha": "לך לך",
    "vayeira": "וירא", "chayei_sarah": "חיי שרה", "toldos": "תולדות",
    "vayeitzei": "ויצא", "vayishlach": "וישלח", "vayeishev": "וישב",
    "mikeitz": "מקץ", "vayigash": "ויגש", "vayechi": "ויחי",
    "shemos": "שמות", "vaeirah": "וארא", "bo": "בא", "beshalach": "בשלח",
    "yisro": "יתרו", "mishpatim": "משפטים", "terumah": "תרומה",
    "tetzaveh": "תצוה", "ki_sisa": "כי תשא", "vayakheil": "ויקהל",
    "pekudei": "פקודי", "pikudei": "פקודי", "vayikra": "ויקרא", "tzav": "צו",
    "shemini": "שמיני", "tazria": "תזריע", "metzora": "מצורע",
    "acharei": "אחרי מות", "kedoshim": "קדושים", "emor": "אמור",
    "behar": "בהר", "bechukosai": "בחוקותי", "bamidbar": "במדבר",
    "naso": "נשא", "behaalosecha": "בהעלותך", "shelach": "שלח",
    "korach": "קרח", "chukas": "חוקת", "balak": "בלק", "pinchas": "פנחס",
    "matos": "מטות", "masei": "מסעי", "devarim": "דברים",
    "vaeschanan": "ואתחנן", "eikev": "עקב", "reei": "ראה", "shoftim": "שופטים",
    "ki_seitzei": "כי תצא", "ki_savo": "כי תבוא", "nitzavim": "נצבים",
    "vayeilech": "וילך", "haazinu": "האזינו", "vezos_haberacha": "וזאת הברכה",
}


def parasha_str(names):
    """today.get's parasha is a tuple of transliterations (double parshiyot ->
    two); return the Hebrew, joined with a maqaf. '' when there is none."""
    if not names:
        return ""
    return "־".join(_PARASHA.get(name, name) for name in names)
