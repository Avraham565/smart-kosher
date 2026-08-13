# CLAUDE.md — אינווריאנטים של הפרויקט

כל כלל כאן אומת מול הקוד באודיט 2026-08-12 (`AUDIT-CONCLUSION.md`).
אינווריאנט שנשבר בקוד — תקן את הקוד או ערער על הכלל. אל תשבור בשקט.

## מוצרים

- **מוצר א׳** — CrowPanel S3 + H2: UI + מוח + רדיו בתהליך MicroPython אחד
  (`products/panel/`). **מוצר ב׳** — AtomS3 Lite + NanoC6: hub חסר-מסך (`products/hub/`).
  שניהם מייבאים את אותה ליבה מ-`src/smart_kosher/`.

## שכבות

- כיוון התלות: `domain` ← `application` ← `adapters`/`web`/`serial_channel`.
  `ports/` הם עלים מוחלטים. `zmanim/` הוא עלה טהור (אפס תלויות) ולכן `domain`
  רשאי לייבא ממנו. **אין מעגלים, ואין `domain→adapters` או `adapters→application`.**
- `web/`, `serial_channel.py` ו-`apps/desktop/` הם **תרגום טרנספורט בלבד**. ולידציה
  עסקית וסיווג שגיאות חיים ב-`application/api.py`.

## ניידות CPython ↔ MicroPython

- הליבה חייבת לייבא ולרוץ על MicroPython. `requires-python = ">=3.8"`.
- **`.format()` בלבד — אין f-strings ואין type annotations בליבה.**
- אין `dataclasses`, אין `typing`, אין `abc`. פורט = מחלקה עם `NotImplementedError`.
- I/O אופציונלי דרך `try: import ujson as json / except ImportError`, וזיהוי
  פלטפורמה דרך `hasattr(gc, "mem_free")`.
- `await` בתוך comprehension אסור. `json.dumps` לא מקבל kwargs.
- כל `asyncio.create_task()` חייב הפניה חיה ב-local/set — אחרת המשימה נאספת
  לפני שרצה (`products/panel/device/bridge.py:_pending`, `zigbee_gateway.py:_deliver`).

## דומיין

- ישויות הן `dict` + `validate_*()`. **אין מחלקות עצם-ערך** מלבד `Event`.
- כל `validate_*` מרים `ValueError` פנימי וממיר בגבול ל-`XValidationError(ValueError)`,
  ומחזיר `True`.
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
ורק כשזה בלתי אפשרי (שפות שונות) — טסט הצמדה.
- מקור אחד: `web/route_table.py`, `adapters/_atomic_io.py`,
  `ports/clock.py:MIN_VALID_YEAR`, אוצר המילים בדומיין, `SETTINGS_DEFAULTS`.
- טסט הצמדה: `tests/test_zman_keys_are_in_sync.py` — 18 מפתחות על פני חמישה
  משטחים, כולל פרסינג טקסטואלי של JS ושל MicroPython, כי שם באמת אי אפשר לייבא.

## פקודות

```
$env:PYTHONPATH = "src"; python -m pytest -q     # 371 טסטים + 1455 subtests
ruff check .                                      # חייב לעבור נקי
python tools/dev_server.py                        # API על localhost:5004
```

`tools/zigbee_probe/` מוחרג מ-lint בכוונה — הוא מכיל סקריפטי חקירה בלבד.
`firmware/h2_coordinator/` היא **קושחת הייצור החיה** של הרכזת, ונבנית דרך
`firmware/tools/build_h2_coordinator.ps1`. `experiments/` חוסל (2026-08-12);
שושלת קוד התצוגה ונתיבי השחזור מ-git עברו ל-`docs/display-lineage.md`.
