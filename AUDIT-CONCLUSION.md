# ביקורת ארכיטקטונית — מסקנות

תאריך: 2026-08-14 · ענף: `main` · HEAD: `eda4233`
היקף: 189 קבצים מנוהלים, 6 שפות. שיטה: פנקס כיסוי מכני → תצפית → אינדקס לפי
מושג → שיפוט, מול קבצי טיוטה ולא מול זיכרון.
קודמתה (2026-08-12, ציון 8/10, כל ממצאיה בוצעו) נמצאת בהיסטוריית git.

---

## ציון בריאות: **8.5 / 10**

**הריפו הכליל את השיטה שהאודיט הקודם מצא רק בפינה אחת — ונשארו שני מקומות
שהיא לא הגיעה אליהם.**

האודיט הקודם סיכם: "תשעה מושגים חוצי-יחידות, ולאחד בלבד יש הצמדה", והשורש
שזוהה היה שאין `CLAUDE.md`. שניהם טופלו. המדידה הנוכחית:

| מדד | תוצאה | איך נמדד |
|---|---|---|
| תלויות מעגליות בליבה | **אפס** | AST על 48 מודולים, 108 קשתות |
| הפרות שכבה | **אפס** — אין `domain→adapters`, אין `adapters→application` | אותה סריקה |
| lint | `All checks passed`, exit 0 | `ruff check .` |
| טסטים | **376 עוברים, 1 מדולג, 1457 subtests** ב-4.34 שניות (אחרי התיקונים: **395** ו-1475) | `pytest -q` |
| מושגים חוצי-גבול עם שומר | **7 מתוך 10** | אינדקס מלא, ראה F-02 |
| אינווריאנטים שאומתו | **33 מתוך 33 הוכרעו**: 23 מתקיימים, 8 סוטים, 2 לא ניתנים לאימות | `02-crossref` |
| קוד מת | 5 שמות top-level, כולם עלים | AST + `grep` ממצה |

מה שגורע — שלושה דברים, ואף אחד מהם אינו באג חי:

1. **שני אוצרי מילים חוצי-משטחים נשארו בלי שומר** (F-02). מפתחות הזמן קיבלו
   טסט הצמדה בן שבע מתודות עם נימוק כתוב; `RECURRENCE_TYPES` ו-`ACTION_TYPES`
   חוצים את אותם שלושה משטחים בדיוק ולא קיבלו כלום.
2. **סתירה רדומה בין שני כללי GC** (F-01), שהתכנון הכתוב בקוד עצמו מוביל אליה.
3. **הטסטים והפרודקשן רצים על שני repositories שונים שהם 79% אותו קוד** (F-03).

מה שמצדיק את הציון הגבוה מעבר למספרים: הכללים **נאכפים במכונה, לא בכוונה**.
`remove_flag(SCROLLABLE)` בשמונה מקומות ובדיקת חומרה שמאמתת אותו; שלושה טסטי
הצמדה טקסטואליים; טבלת routes שטסט אוכף ששני הטרנספורטים מכסים במלואה. ה-commit
האחרון (`eda4233`) הסיר `gc.collect()` מחבילת הבדיקות של מוצר א׳ עם הנימוק
"The suite was the only place on product A still doing it" — כלומר הכללים
מתוחזקים נגד הקוד שאמור לשמור עליהם.

---

## ממצאים לפי עדיפות

### P1 — סתירה רדומה שהתכנון הכתוב מוביל אליה

#### F-01 · מדיניות ה-GC מותנית בפלטפורמה, לא במוצר

`CLAUDE.md` מחזיק שני כללים הפוכים בכוונה: במוצר א׳ `gc.collect()` אחרי תחילת
רינדור משחרר draw buffer ש-core-0 סורק (LoadProhibited boot-loop); במוצר ב׳ זו
האסטרטגיה הנכונה. המתג שמפריד ביניהם אינו מוצר:

```python
# src/smart_kosher/web/server.py:16-17
_IS_MICROPYTHON = hasattr(gc, "mem_free")
```

```python
# src/smart_kosher/web/server.py:37-44
if _IS_MICROPYTHON:
    # On a no-PSRAM board every request leaves allocation churn behind;
    @app.after_request
    async def _collect(req, resp):
        gc.collect()
```

הנימוק בהערה הוא חומרת מוצר ב׳; התנאי הנבדק אמיתי גם על מוצר א׳.

**מי תלוי בזה היום:** איש. `products/panel/device/main.py:218-223` מרכיב `Api`
ואינו קורא `create_app`. **אבל זה לא נשאר כך לפי התכנון הכתוב:**

```python
# products/panel/device/brain.py:12-14
#   * No Microdot/HTTP on the panel today. ... the channel is a
#     future flip-switch (web.server.create_app(api=api)), not a rewrite.
```

הפעלת ה-flip-switch הזה רושמת `gc.collect()` אחרי כל תשובת HTTP על הפאנל, אחרי
שה-UI נבנה. הכשל יהיה LoadProhibited בזמן ריצה, לא שגיאת build, ולא ייראה בשום
טסט CPython — שם `hasattr(gc,"mem_free")` שקר.

**תיקון:** פרמטר מפורש ל-`create_app` (`collect_after_request=False` כברירת
מחדל; ה-hub מעביר `True`), כך שההחלטה נעשית בשורש שיודע על איזה מוצר הוא רץ.

### P2 — שומרים חסרים במקומות שהריפו כבר יודע לשמור עליהם

#### F-02 · `RECURRENCE_TYPES` ו-`ACTION_TYPES` בלי מקור ובלי טסט

| משטח | recurrence | action |
|---|---|---|
| domain | `RECURRENCE_TYPES` 11 (`domain/schedules.py:40`) | `ACTION_TYPES` (`domain/actions.py:5`) |
| panel | `RECURRENCE_NAMES` 11 + `RECURRENCE_SIMPLE` 7 (`sched_labels.py:26,38`) | on/off ידניים (`schedule_add.py:133,139`) |
| desktop | `RECURRENCE_LABELS` 11 (`labels.js:24`) | `ACTION_LABELS` (`labels.js:38`) |

```text
$ grep -rn "ACTION_TYPES|RECURRENCE_TYPES|RECURRENCE_NAMES|RECURRENCE_LABELS|ACTION_LABELS" tests/
EXIT=1  (אפס התאמות)
```

**אין סחף חי** — מדידה נתנה 11/11/11 עם `diff=[]`. חסר שומר, לא באג.

**מה ישבר בלעדיו:** `views/schedules.js:75-76,136` בונה את אפשרויות הטופס מתוך
`RECURRENCE_LABELS`. סוג חדש בדומיין לא יופיע בשולחני כלל; סוג שהוסר יישאר
כאפשרות ויקבל 400 בשליחה. זה בדיוק הכשל השקט שטסט הזמנים קיים כדי לתפוס.

#### F-03 · `MemoryRepository` הוא 79% עותק, והטסטים רצים עליו — **והוא הסתיר 500 חי**

> **עודכן בביצוע:** הממצא הזה נוסח כ"סיכון סחף" והתברר כהסתרה של באג פעיל בשני
> המוצרים. הפירוט בסוף המסמך, בסעיף הביצוע. חומרתו בפועל: **גבוהה**.

```text
json_repository stmts=364  memory_repository stmts=87
identical normalized lines shared=59 (79% of memory_repository)
  run of 11 stmts: json_repository.py:179-191  <->  memory_repository.py:23-35
  run of  7 stmts: json_repository.py:378-384  <->  memory_repository.py:86-92
  run of  7 stmts: json_repository.py:388-394  <->  memory_repository.py:93-99
```

- **פרודקשן** מריץ `JsonRepository` בלבד (panel brain, hub main, hwtest).
- **רוב כיסוי ההתנהגות** רץ על `MemoryRepository` — 9 קבצי טסט, ובהם
  `test_api`, `test_routes`, `test_serial`, `test_web`, `test_zigbee_gateway`.

תיקון התנהגות שיוחל על אחד ולא על השני יעבור את ה-suite בירוק בעוד המכשיר
מתנהג אחרת.

### P3 — דיוק ותחזוקה

| # | ממצא | ראיה |
|---|---|---|
| F-04 | חמישה שמות top-level ללא צרכן | `ui_home.py:39`, `astronomy.py:71,245,269`, `reactive.py:114` |
| F-05 | `CLAUDE.md` הצהיר 371+1455; בפועל 376+1457+1 skipped | `pytest -q` |
| F-06 | `pyrightconfig.json:2` על 3.14 מול ליבה נעולה על 3.8 | מול `pyproject.toml:10,34` |
| F-08 | `uart_codec` קורא לכשל prefix ‏`bad_crc`; המפרט וה-C אומרים `bad_frame` | `uart_codec.py:33,36` מול `UART_PROTOCOL.md:31-32` ו-`link.c:101-110` |
| F-11 | `CLAUDE.md` לא תיעד שמוצר ב׳ מושהה ובלי scheduler | `hub/device/main.py:3-17` |

**על F-08:** הצד ה-C מיישם את המפרט נכון ויש לו טסט host ייעודי; רק צד Python
חולק, והטסטים מקבעים את הסטייה (`test_uart_codec.py:81,86`). הנזק אבחוני בלבד —
`zigbee_gateway.py:205` תופס `ValueError` גנרי — אבל בעיית מסגור שמדווחת כבעיית
checksum שולחת את מי שמנפה שגיאות לכיוון הלא נכון.

---

## תוכנית תיקון — **בוצעה במלואה**

בוצעה בסדר עולה של סיכון, כל שלב מאומת לפני הבא.

| סדר | משימה | מה נעשה | ממצא |
|---|---|---|---|
| 1 | `pythonVersion: "3.8"` | אומת מראש שכל 28 קבצי ה-Python שמחוץ לליבה נותחים תחת 3.8 (`FAIL_UNDER_PY38=0`), ולכן אין שגיאות שווא | F-06 |
| 2 | `bad_frame` ב-codec | שני מסלולי prefix שונו + שני assertions בטסטים. `test_bad_crc_raises` נשאר `bad_crc` — שם ה-CRC באמת שגוי | F-08 |
| 3 | הסרת קוד מת | `_nav_cb`, `utc_sun_time`, `hms_to_minutes`, `_jd_from_jc`. אומת שאף אחד אינו ב-`__all__` ואינו מיוצא מ-`zmanim/__init__.py` | F-04 |
| 4 | טסט הצמדה לאוצר המילים | `tests/test_schedule_vocab_is_in_sync.py`, 6 טסטים. אומת במוטציה שהוא תופס את ארבעת כיווני הסחף | F-02 |
| 5 | `collect_after_request` | ברירת מחדל `None` = התנהגות היסטורית (אפס תזוזה לקורא קיים), הרכזת מעבירה `True` במפורש, 3 טסטים חדשים | F-01 |
| 6 | חוזה הרפוזיטורי | `tests/test_repository_contract.py` — **וכאן התגלה באג חי**, ראה להלן | F-03 |

**על משימה 5:** התוכנית המקורית אמרה "ברירת מחדל `False`, וה-hub מעביר `True`",
וזה היה מסוכן: hub שלא יקבל `True` מאבד בשקט את ה-GC שמחזיק לו את ה-heap, ואף
טסט לא היה תופס — הענף מת ב-CPython, ומוצר ב׳ מושהה ובלי חומרה לאימות. `None`
מבטל את הסיכון הזה. הרווח הצדדי: הענף הפך **בר-בדיקה לראשונה**, כי אפשר לכפות
`True` על CPython.

**על משימה 3:** `computed` (`reactive.py:114`) **נשאר** — מתועד ב-`reactive.py:6`
כחלק מה-API של ספריית הסיגנלים שכל ה-UI של הפאנל בנוי עליה, ועולה שש שורות. אם
גם באודיט הבא לא יהיה לו צרכן, להסיר.

---

## מה שהתגלה בביצוע — 500 חי בשני המוצרים

משימה 6 נועדה להיות "טסט שמקבע חוזה". פרוב שהשווה את שני המימושים מצא שבע סטיות,
ואחת מהן הגיעה עד המשתמש.

**השורש** (`json_repository.py:190-195`): `upsert` תפס את ה-`ValueError` של
הדומיין ורים אותו מחדש כ-`RepositoryValidationError`, ש-**ירש מ-`Exception`
ולא מ-`ValueError`**. `api.py:dispatch` ממפה `ValueError`→`bad_request` וכל השאר
→`internal`. לכן:

| בקשה | על `MemoryRepository` (הטסטים) | על `JsonRepository` (המכשיר) |
|---|---|---|
| `POST /api/zones {}` | 400 | **500** |
| `POST /api/zones {"name":""}` | 400 | **500** |
| `POST /api/zones {"name":123}` | 400 | **500** |
| תזמון עם `recurrence_type` לא מוכר | 400 | **500** |
| תזמון עם `action_type: toggle` | 400 | **500** |

כלומר **כל שדה שנדחה בוולידציה החזיר "internal error" בשני המוצרים**, במקום 400
עם הודעת השגיאה האמיתית — והסוויטה הייתה ירוקה לאורך כל הדרך, כי היא בונה את
הלקוחות שלה על המימוש שאינו מבצע את ההמרה הזאת. זה בדיוק המנגנון ש-F-03 תיאר.

**התיקון:** `class RepositoryValidationError(RepositoryError, ValueError)`.
`RepositoryCorruptionError` **לא** קיבל את זה בכוונה — אחסון פגום הוא תקלה
פנימית ו-500 הוא התשובה הנכונה לה. אומת: הטסט החדש נכשל ב-12 טענות בלי התיקון
ועובר איתו.

**מה שנשאר סטייה מקובלת:** מספר ה-revision מתחיל מבסיס שונה בשני המימושים.
`planner.py:74-82` משווה אותו רק לשינוי, אף פעם לא לערך מוחלט, ולכן הטסט מקבע
"משתנה במוטציה" ולא ערך.

### והתיקון עצמו כמעט הפיל את שני הלוחות

הניסוח הראשון היה `class RepositoryValidationError(RepositoryError, ValueError)` —
ירושה מרובה. הוא עבר את כל 395 הטסטים. על החומרה (AtomS3, MicroPython 1.24.1):

```text
MI_DEFINE: FAILS -> TypeError multiple bases have instance lay-out conflict
SINGLE_CATCH_AS_VALUEERROR: yes
```

השגיאה קורית בזמן **הגדרת** המחלקה, כלומר ב-import של `json_repository` — קובץ
ששני שורשי המוצר מייבאים. כלומר: **הליבה לא הייתה נטענת ואף לוח לא היה עולה**,
בעוד הסוויטה ב-CPython ירוקה לחלוטין. זו בדיוק הקטגוריה שכללי הניידות
ב-`CLAUDE.md` קיימים בשבילה, וירושה מרובה לא הייתה בהם.

**מה נעשה:** הטיפוס יורש מ-`ValueError` בלבד — אותה צורה שהדומיין כבר משתמש בה
(`DeviceValidationError`, `ScheduleValidationError`). אומת שאיש אינו תופס
`RepositoryError` כבסיס: הוא נזרק ישירות פעם אחת, לתיקייה שאי אפשר ליצור.

**והשומר:** `tests/test_core_is_micropython_safe.py` סורק ב-AST את כל מה שנצרב
ללוח ואוכף חמישה כללים שאין ל-CPython דרך להיכשל עליהם — ירושה מרובה, f-strings,
annotations, imports אסורים ו-`await` בתוך comprehension. אומת במוטציה: החזרת
הצורה השוברת מייצרת כשל שמצביע על `json_repository.py:26` בשמו.

**ואומת מקצה לקצה על החומרה.** הליבה נצרבה ל-AtomS3, ושתי בקשות נשלחו לערוץ
ה-USB — בדיוק המסלול שהחזיר 500:

```text
zones.create      -> kind=bad_request  "name must be a non-empty string"
schedules.create  -> kind=bad_request  "toggle is not allowed in schedules; use on or off"
```

לפני התיקון שתיהן היו מסווגות `internal`.

---

## חוקים שהוצע לשנות או להסיר — וההכרעה

חמישה אינווריאנטים הועלו בשלב 5. ההכרעה שלך: "תעשה מה שמומלץ" — כלומר כל
חמשת השינויים המומלצים אושרו ובוצעו ב-`CLAUDE.md`.

| חוק | הראיה נגדו | ההכרעה |
|---|---|---|
| "כל `create_task` חייב הפניה חיה" | 13/15 מקיימים. השניים שלא — `zigbee_gateway.py:633` (probe יחיד, `_probe_inflight` מתאפס ב-`finally`) ו-`hub/main.py:144` (sleep ואז `machine.reset`) — קצרים וסופיים, ובuasyncio תור הריצה מחזיק הפניה חזקה | **צומצם** ל"משימה שחורגת מחיי הקורא". אפס שינויי קוד; הכלל עדיין תופס את הכשל האמיתי — משימה שהקורא נוטש |
| "טסט הצמדה רק כשזה בלתי אפשרי (שפות שונות)" | `sched_labels.py` הוא Python ו-import ממנו אפשרי — ובכל זאת `test_zman_keys_are_in_sync.py:81-84` **אוכף** שיישאר בלי import, כי הוא נטען לפני שהתצוגה קיימת | **תוקן** ל"רק כשה-import חסום — שפה אחרת, או אילוץ מכשיר מתועד" |
| `domain ← application ← adapters/web/serial_channel` | `adapters` פונה רק ל-`domain`/`ports` ולעולם לא ל-`application`; שכבת `data` חסרה בניסוח לגמרי | **תוקן** לפי הגרף הנמדד. כל האיסורים נשארו כלשונם — הם אומתו נכונים |
| "כל `validate_*` ממיר ל-`XValidationError`" | 6/8. `validate_json` (primitive פנימי) ו-`validate_entity` (מנתב לוולידטור שכבר מרים נכון) מרימים `ValueError` עירום | **צומצם** ל"כל validator של **ישות**" |
| — (לא היה קיים) | שני כללי ה-GC ההפוכים נשענים על ביטוי שנכון בשני המוצרים | **נוסף** אינווריאנט: בחירת מדיניות GC שייכת לשורש ההרכבה, לא לזיהוי פלטפורמה |

**חוק אחד נבחן והושאר כלשונו:** `MIN_VALID_YEAR` ו-2013 של חוק שעון הקיץ —
"שני מושגים שחולקים מספר במקרה". אומת: הסנטינל מוגדר ב-`ports/clock.py` ומיובא
בארבעה מקומות; חוק ה-DST מחזיק literal נפרד ב-`israel_time.py:19-25` ואינו מייבא
אותו. ההפרדה מכוונת ונשמרת.

---

## דו״ח פערים — מה לא נבדק לעומק, ולמה

כל 189 השורות בפנקס קיבלו סטטוס `reviewed`, אבל עומק הבדיקה לא היה אחיד:

| מה | עומק שהושג | למה לא יותר |
|---|---|---|
| ~~`firmware/h2_coordinator/**`~~ | ~~קריאת קוד בלבד~~ → **טסטי ה-host הורצו: 1234 בדיקות, 0 כשלים** | **הפער הזה נסגר, והרישום המקורי היה שגוי.** הסריקה בדקה את ה-PATH של Windows; שרשרת הכלים חיה ב-WSL, ושם `gcc 15.2`, `make`, `cmake` ו-`~/esp/esp-idf` כולם קיימים. `build_h2_coordinator.ps1:54` אומר את זה במפורש — הוא קורא `wsl bash -lc "source ~/esp/esp-idf/export.sh ..."`. ה-build המלא של ה-firmware עדיין לא הורץ (אין בו שינוי) |
| ~~התאמת MicroPython של הליבה~~ | **נסגר: הליבה המעודכנת נצרבה ל-AtomS3 ועלתה נקי.** תחביר 3.8 על 83 קבצים, חמישה כללים שהפכו לטסט (`tests/test_core_is_micropython_safe.py`), ירושה מרובה אומתה על החומרה, וכל החבילה קומפלה ל-`.mpy` ונטענה | — |
| `products/panel/hwtest/**` ו-`products/*/host/**` | קריאה בלבד | דורש חומרה מחוברת |
| `data-sheets/**` (9 קבצים) | תפקיד, provenance, צרכנים | מסמכי ייחוס של ספק; ה-PDFs מוחרגים מ-git |
| `products/panel/device/fonts/*.bin` (5) | תפקיד, גודל, מי צורך, איך נפרסים | נכסים בינאריים |
| `tests/data/zmanim_golden.csv.gz` | provenance (מחולל Python+Java), אופן הצריכה | ~מיליון ערכים; אומת דרך הטסט שצורך אותו |
| סריקת זמנים מלאה | ברירת המחדל היא מדגם | הסריקה המלאה מותנית ב-`ZMANIM_FULL_REFERENCE` |
| `products/hub/**` | **נבדק בזמן ריצה על החומרה** — בוט נקי, `serial channel ready`, 103KB heap פנוי, ו-`status.get` עונה | מוצר ב׳ עדיין מושהה ובלי scheduler; ה-NanoC6 לא היה מחובר, ולכן `link_down: true` והרדיו עצמו לא נבדק |

**מגבלת תהליך שנרשמה:** ה-suite הורץ פעם אחת בלבד. אף שכל `TEMP`, `TMP`,
`TMPDIR`, `--basetemp` ו-cache הופנו לאזור הטיוטה, כמה טסטים מגדירים בעצמם
נתיבי עבודה תחת `tests/` (`test_application.py:95-143`, `test_storage.py:14-58`,
`test_panel_scheduler.py:20-31`). הם ניקו אחריהם ולא נשאר שינוי, אבל הייתה נגיעה
זמנית מחוץ לאזור הטיוטה, ולכן לא הורץ שוב.

---

## מה שנבדק ונמצא תקין

ראוי לציון, כדי שלא ייבדק שוב מאפס:

- **סמנטיקת המסירה שלמה.** `accepted_by_h2` אינו ב-`EXECUTION_SUCCESS_STATUSES`
  ולכן אינו נכנס ל-journal ומנוסה שוב; `confirmed_by_device` כן. מיפוי ה-ACK
  תואם לטבלת הפרוטוקול.
- **הכלל שהמוח מכבד התערבות ידנית מחזיק.** חיפוש כל הכתיבות ל-`_states` מצא
  assignment יחיד — `_on_state` (`zigbee_gateway.py:476-485`), שנקרא רק
  מ-`attribute_report` ומ-ACK של `read_attr`. פקודות כותבות ל-`_expected` בלבד.
- **`toggle` חסום בתזמון** אחרי ולידציית action, ומותר בשליטה ידנית.
- **החלון והשעון:** `(start_exclusive, end_inclusive]` בדקות UTC שלמות; שני
  ה-RTC adapters קוראים וכותבים UTC; אין שמירת "נראה לאחרונה", ו-boot catch-up
  וטיק רגיל עוברים שניהם ב-`RecoveryService.recover`.
- **`SETTINGS_DEFAULTS` מקור יחיד** ושלושת השורשים מוסיפים `city` בלבד.
- **טבלת ה-routes מקור יחיד**, 27 שורות, ושני הטרנספורטים מכוסים בטסט.
- **איסור הגלילה נאכף במכונה** — `remove_flag(SCROLLABLE)` בשמונה מקומות
  ובדיקת חומרה ב-`hwtest_ui.py:312,344`.
- **ה-SCC בן 11 המודולים ב-`products/panel/device` אינו פגם** — הקשתות deferred
  בכוונה בתוך פונקציות, דפוס ה-lazy import הסטנדרטי לחיסכון בזיכרון.
- **היעדר `kind` ב-envelope של HTTP אינו סתירה** — ל-HTTP יש status codes,
  ול-serial אין, וה-bridge ממיר kind→status כך ששני הטרנספורטים מגיעים ללקוח
  באותה צורה.
