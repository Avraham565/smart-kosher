# CLAUDE.md — אינווריאנטים של הפרויקט

כל כלל כאן אומת מול הקוד באודיט 2026-08-14 (`AUDIT-CONCLUSION.md`).
אינווריאנט שנשבר בקוד — תקן את הקוד או ערער על הכלל. אל תשבור בשקט.

## מוצרים

- **מוצר א׳** — CrowPanel S3 + H2: UI + מוח + רדיו בתהליך MicroPython אחד
  (`products/panel/`). **מוצר ב׳** — AtomS3 Lite + NanoC6: hub חסר-מסך (`products/hub/`).
  שניהם מייבאים את אותה ליבה מ-`src/smart_kosher/`.
- **מוצר ב׳ מושהה מ-2026-08-05 ואינו מפעיל scheduler** — תזמון שנשמר בו נאגר
  ולעולם לא יורה (`products/hub/device/main.py`, ראש הקובץ). כללי התזמון שלהלן
  מתארים את מוצר א׳; במוצר ב׳ הם קוד קיים שלא חובר.

## שכבות

- כיוון התלות: `domain` ← `application` ← `web`/`serial_channel`.
  `adapters/` מייבא `domain`/`ports` **בלבד**; `data/` מייבא `domain` בלבד.
  `ports/` הם עלים מוחלטים. `zmanim/` הוא עלה טהור (אפס תלויות) ולכן `domain`
  רשאי לייבא ממנו. **אין מעגלים, ואין `domain→adapters` או `adapters→application`.**
- `web/`, `serial_channel.py` ו-`apps/desktop/` הם **תרגום טרנספורט בלבד**. ולידציה
  עסקית וסיווג שגיאות חיים ב-`application/api.py`.

## ניידות CPython ↔ MicroPython

- הליבה חייבת לייבא ולרוץ על MicroPython. `requires-python = ">=3.8"`.
- **`.format()` בלבד — אין f-strings ואין type annotations בליבה.**
- אין `dataclasses`, אין `typing`, אין `abc`. פורט = מחלקה עם `NotImplementedError`.
- **אין ירושה מרובה.** MicroPython מרים `TypeError: multiple bases have instance
  lay-out conflict` בזמן **הגדרת** המחלקה, כלומר ב-import — הליבה כולה לא נטענת
  והלוח לא עולה, בעוד CPython ירוק לגמרי. אומת על החומרה (MicroPython 1.24.1,
  ESP32-S3) על `class X(MyError, ValueError)`. שגיאת ולידציה חדשה יורשת מ-
  `ValueError` **בלבד**, כמו בדומיין.
- I/O אופציונלי דרך `try: import ujson as json / except ImportError`, וזיהוי
  פלטפורמה דרך `hasattr(gc, "mem_free")`.
- `await` בתוך comprehension אסור. `json.dumps` לא מקבל kwargs.
- הכללים שלמעלה שאפשר לאכוף מהמקור נאכפים ב-`tests/test_core_is_micropython_safe.py`
  (ירושה מרובה, f-strings, annotations, imports אסורים, `await` ב-comprehension).
  זו הקטגוריה ש-CPython **לא יכול** להיכשל עליה, ולכן סוויטה ירוקה אינה ראיה.
- **משימה שחורגת מחיי הקורא** חייבת הפניה חיה ב-local/set — אחרת היא נאספת
  לפני שרצה (`products/panel/device/bridge.py:_pending`, `zigbee_gateway.py:_deliver`).
  fire-and-forget קצר וסופי שתור הריצה מחזיק עד סופו מותר, ומכוון בשני מקומות:
  `zigbee_gateway.py:_probe_link` ו-`hub/device/main.py:system_reboot`.

## דומיין

- ישויות הן `dict` + `validate_*()`. **אין מחלקות עצם-ערך** מלבד `Event`.
- כל validator **של ישות** מרים `ValueError` פנימי וממיר בגבול
  ל-`XValidationError(ValueError)`. **כל** `validate_*` מחזיר `True` בהצלחה.
  `_values.validate_json` (primitive) ו-`entities.validate_entity` (מנתב לוולידטור
  הייעודי, שכבר מרים נכון) מרימים `ValueError` עירום — וזה מכוון.
- **שגיאת ולידציה חייבת להישאר `ValueError` בכל שכבה שהיא עוברת בה.** על זה
  נשען `api.py:dispatch`, שממפה `ValueError`→`bad_request` וכל השאר→`internal`.
  שכבה שעוטפת ולידציה בטיפוס שאינו `ValueError` הופכת שגיאת קלט ל-500: זה בדיוק
  מה ש-`RepositoryValidationError` עשה. שגיאת **אחסון** (`RepositoryCorruptionError`)
  אינה `ValueError` — 500 הוא התשובה הנכונה לה.
- אוצר מילים מוגדר **פעם אחת**, בדומיין:
  `ACTION_TYPES` · `TARGET_TYPES` · `TARGET_COLLECTIONS` · `CONFIG_ENTITY_TYPES` /
  `ALL_ENTITY_TYPES` · `ZMAN_KEYS` · `RECURRENCE_TYPES`.
  שכבות מעליו **מייבאות, לא כותבות מחדש** — גם כשזה שתי מילים.
- **`toggle` אסור בלוחות זמנים** (`domain/schedules.py`) — הוא לא אטומי. מותר
  בשליטה ידנית בלבד.
- זמן שהוצא משימוש נכנס ל-`RETIRED_ZMAN_KEYS`, ו-`application/migrations.py`
  מנקה רשומות קיימות ומדווח. ולידציה לבדה משאירה מתג שלא יורה, בשקט.

## סמנטיקת מסירה

- `accepted_by_h2` = נלקח, **לא** הוכח → **לא** נכנס ל-journal ומנוסה שוב.
  `confirmed_by_device` = APS confirm מהמכשיר עצמו → journalable.
  הסולם המלא: `ports/device_gateway.py` + `docs/UART_PROTOCOL.md`.
- קבוצה נמדדת לפי החבר הגרוע ביותר (`_STATUS_RANK`).
- `_states` = מילת המכשיר עצמו (attribute_report / read_attr ack) בלבד.
  `_expected` = מה שציווינו. **אסור לכתוב ל-`_states` משום מקור אחר** — עליו
  נשען הכלל שהמוח מתקן סטייה שנוצרה מעצמה אך **מכבד** התערבות ידנית.

## תזמון

- `event_id` דטרמיניסטי + journal עמיד = השמעה חוזרת של חלון חינם. לכן **אין
  שמירת "נראה לאחרונה"**, ו-catch-up בבוט וטיק רגיל הם אותו מסלול קוד.
- חלון = `(start_exclusive, end_inclusive]` בדקות UTC שלמות.
- ה-RTC מחזיק **UTC**. זמן מקומי תמיד נגזר ממנו + היסט ההגדרות.
- שנה < `ports/clock.py:MIN_VALID_YEAR` = השעון מעולם לא נקבע → לא יורים כלום.
  אותו ערך (2013) הוא גם תחילת חוק שעון הקיץ הישראלי ב-`zmanim/israel_time.py`.
  **שני מושגים שחולקים מספר במקרה** — אל תאחד ואל תערוך אותם יחד.

## הגדרות

- `application/views.py:SETTINGS_DEFAULTS` הוא המקור היחיד. שורש הרכבה רשאי
  להוסיף `city` בלבד. עותק פרטי = הבאג שהחזיק שתי שעות כניסת שבת.
- `candle_offset` (18) ו-צאת שבת (זווית) הם **כללי מוצר**, לא הגדרות. לא ניתנים
  לכתיבה ולא נשמרים בנתוני עיר.

## זיכרון ורינדור

- **מוצר א׳:** אסור `gc.collect()`/`gc.threshold()` אחרי תחילת רינדור — משחרר
  draw buffer חלקי ש-core-0 עדיין מצביע אליו (LoadProhibited boot-loop). אסורות
  גם אנימציית מסך-מלא וגלילה.
- **מוצר ב׳:** שם זו האסטרטגיה **הנכונה** ומופעלת בכוונה
  (`web/server.py`, after_request) — אין PSRAM ואין RGB scanout.
- **בחירת מדיניות ה-GC שייכת לשורש ההרכבה, לא לזיהוי פלטפורמה.** הפלטפורמה לא
  יודעת על איזה מוצר היא רצה: `hasattr(gc, "mem_free")` אמיתי בשני המוצרים ולכן
  אינו יכול להפריד בין איסור לחובה. `create_app(collect_after_request=...)` הוא
  ההחלטה: הרכזת מעבירה `True` במפורש, וכל קורא בפאנל **חייב** להעביר `False`.
  `None` = ברירת המחדל ההיסטורית לפי פלטפורמה, ונשארה רק כדי לא להזיז קורא קיים.
- LVGL נשאב מלולאת ה-asyncio (`products/panel/device/lvgl_loop.py`), **לא** מ-`TaskHandler` —
  אחרת callbacks מתנגשים עם ה-pump.
- אל תחקור UI מה-REPL תוך כדי ריצה; זה מפיל את הלוח.

## משטח ה-REST

`web/route_table.py` הוא **המקור היחיד** למיפוי URL→op. הרכזת רושמת ממנו את
ה-routes שלה (`web/routes/register_all`) והלקוח השולחני פותר מולו נתיב כשהבקשה
נוסעת ב-USB (`apps/desktop/bridge.rest_to_op`). נתיב חדש = שורה אחת בטבלה; שני
הטרנספורטים מקבלים אותו.
אל תוסיף route ישירות באחד הצדדים — כך בדיוק נוצר המצב שבו יכולת עבדה ב-WiFi
והחזירה 404 ב-USB בשקט. `tests/test_route_table.py` אוכף ששני הצדדים מכסים את
הטבלה במלואה.

## כשמושג חוצה גבול

אותו מושג בשני קבצים או יותר שאין ביניהם import — **מקור אחד ששניהם מייבאים**,
ורק כשה-import **חסום** — טסט הצמדה. חסום = שפה אחרת, או אילוץ מכשיר מתועד.
- מקור אחד: `web/route_table.py`, `adapters/_atomic_io.py`,
  `ports/clock.py:MIN_VALID_YEAR`, אוצר המילים בדומיין, `SETTINGS_DEFAULTS`.
- טסט הצמדה: `tests/test_zman_keys_are_in_sync.py` — 18 מפתחות על פני חמישה
  משטחים, כולל פרסינג טקסטואלי של JS ושל MicroPython. `labels.js` הוא שפה אחרת;
  `sched_labels.py` הוא אילוץ מכשיר — הוא נטען לפני שהתצוגה קיימת, ולכן הטסט
  עצמו אוכף שיישאר בלי import.
- טסט הצמדה: `tests/test_schedule_vocab_is_in_sync.py` — `RECURRENCE_TYPES`
  ו-`ACTION_TYPES` על פני דומיין, פאנל ושולחני. ה-labels נבדקים כשוויון מלא;
  `RECURRENCE_SIMPLE` כתת-קבוצה בלבד, כי הפאנל מציע 7 מתוך 11 **בכוונה**.

## פורט עם יותר ממימוש אחד

`MemoryRepository` ו-`JsonRepository` מממשים את אותו port, אבל הטסטים בונים
fixtures על הראשון ושני המוצרים רצים על השני. **הבדל התנהגותי ביניהם אינו נראה:**
הסוויטה ירוקה והמכשיר לא. כך 500 חי שרד — הרפוזיטורי של הקבצים עטף ולידציה
בטיפוס שאינו `ValueError`, וכל שדה שנדחה החזיר "internal error" במקום 400.
`tests/test_repository_contract.py` מריץ את אותן טענות, ואת אותה בקשת HTTP,
פעם אחת לכל מימוש. מימוש חדש של port קיים = שורה בקובץ הזה.

## פקודות

```
$env:PYTHONPATH = "src"; python -m pytest -q     # 400 עוברים, 1 מדולג, 1475 subtests
bash firmware/h2_coordinator/host_test/run.sh    # ב-WSL: 1234 בדיקות C
ruff check .                                      # חייב לעבור נקי
python tools/dev_server.py                        # API על localhost:5004
```

`tools/zigbee_probe/` מוחרג מ-lint בכוונה — הוא מכיל סקריפטי חקירה בלבד.
`firmware/h2_coordinator/` היא **קושחת הייצור החיה** של הרכזת, ונבנית דרך
`firmware/tools/build_h2_coordinator.ps1`. `experiments/` חוסל (2026-08-12);
שושלת קוד התצוגה ונתיבי השחזור מ-git עברו ל-`docs/display-lineage.md`.
