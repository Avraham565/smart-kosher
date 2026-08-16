# תוכנית תיקון — לוח הקיר (`products/panel`)

מקור: סקירה לעומק, 2026-08-15. HEAD: `eda4233`.
היקף: 5,035 שורות ב-38 קבצים. שיטה: בדיקה מכנית של כל האינווריאנטים + קריאה מלאה
של שורש ההרכבה ושכבת ה-UI + אימות ידני של כל שרשרת השלכה עד למה שנראה על הזכוכית.

> **סטטוס: אף ממצא לא תוקן.** תוכנית עבודה, לא תיאור מצב.

מסמך אחות: `docs/h2-remediation-plan.md` (קושחת הרכזת).

---

## מה נבדק ונמצא נקי

בדיקה מכנית על כל 38 הקבצים — **אפס הפרות**:

| כלל | תוצאה |
|---|---|
| אין f-strings | 0 |
| אין type annotations | 0 |
| אין `dataclasses`/`typing`/`abc` | 0 |
| אין `await` בתוך comprehension | 0 |
| אין `gc.collect()`/`gc.threshold()` | 0 (כל אזכור הוא הערה שמסבירה את האיסור) |
| אין אנימציית מסך-מלא | 0 — כל ניווט הוא `lv.screen_load` |
| `toggle` לא זמין בתזמון | מאושר (`schedule_add.py:139` מציע on/off בלבד) |
| `create_task` עם הפניה חיה **בפאנל** | מאושר (`main.py:183-192`, `bridge.py:56-58`) |

הכללים הכתובים מקוימים. הממצאים הם במקומות שאף כלל לא כיסה.

---

## הממצאים

| # | ממצא | חומרה | file:line |
|---|---|---|---|
| P-1 | effect יתום כותב לתווית משוחררת אחרי מחיקת מסך | P0 | `shell.py:51-54` + `room_page.py:207` |
| P-2 | חריגה במשימה אחת הורגת את הפאנל, והמסך נשאר נראה חי | P0 | `main.py:197,172-179` |
| P-3 | רשימות ללא תקרה על מסך שאי אפשר לגלול בו | P1 | `rooms_page.py:72-75` ועוד |
| P-4 | `_probe_link` יוצר משימה בלי הפניה, ואז ננעל | P1 | `zigbee_gateway.py:631-633` |
| P-5 | פעולות כתיבה בלי `on_err`, וניווט לפני שהתשובה חוזרת | P2 | `schedule_add.py:296-306` |
| P-6 | `RECURRENCE_NAMES` עותק פרטי ללא הצמדה | P2 | `sched_labels.py:26-33` |
| P-7 | `settime` משכפל ולידציה של `device_time` | P3 | `settime.py:132-140` |
| P-8 | בחירת סימן ההיסט מוחקת את המספר שהוקלד | P3 | `schedule_add.py:225-228` |

### P-1 · effect יתום כותב לזיכרון משוחרר

`shell.py:51-54` — כל תת-עמוד בונה שעון פינתי וקורא `clock.bind_time(mini)`.
**ערך ההחזרה נזרק.**

השרשרת מאומתת שורה-בשורה:

1. `clock.bind_time` מחזיר `bind_text(label, _time_text)` (`clock.py:43`)
2. `_time_text` קורא `store.now.get()` (`clock.py:16`) → ה-effect נרשם ל-Signal
   (`reactive.py:73-74`)
3. `Signal._observers` מחזיק הפניה חזקה (`reactive.py:50`) → ה-effect לא ייאסף
   ולא ניתן לשחרור, כי ההפניה היחידה אליו נזרקה
4. `room_page.py:207` / `device_page.py:175` / `zone_picker.py:55` מוחקים מסך
   שנבנה דרך `shell.sub_page`/`page_create` (`room_page.py:156`,
   `device_page.py:119`, `zone_picker.py:29`)
5. `_teardown()` משחרר רק את `_effects`/`_row_effects` שהמודול עצמו צבר
   (`room_page.py:145-151`, `device_page.py:111-114`). ה-effect של ה-shell לא
   באף רשימה. ל-`zone_picker` אין רשימה בכלל
6. `_clock_refresh` (`main.py:118`) כותב ל-`store.now` בשינוי הדקה הבא →
   `observer._notify()` → `set_text` על תווית משוחררת
7. `_Effect._run`'s `except Exception` (`reactive.py:87`) לא תופס תקלת native

**זה מתועד אצלכם.** `hwtest/hwtest_ui.py:348-357`:

> *"a bound effect is held by the Signal it read (store.today, store.now) --
> nothing here can unsubscribe them. Deleting the screen frees the labels while
> nineteen live effects still hold their set_text, so the next write to either
> Signal would call a method on freed memory."*

הטסט נמנע ממחיקה בגלל זה. שלושת עמודי הייצור מוחקים.

**למשתמש:** פותחים חדר א', עוברים לחדר ב'. תוך פחות מדקה — LoadProhibited.
ניווט שגרתי לחלוטין. כל פתיחה נוספת מוסיפה יתום.

### P-2 · מוות שקט של הפאנל

`main.py:197` — `asyncio.gather(...)` על שבע משימות **בלי `return_exceptions=True`**
ובלי supervisor.

`scheduler.run()` מוקשח מפורשות, עם הערה שמנסחת בדיוק את הסיכון:
*"A tick must never kill the loop: a raise here would leave the panel rendering
happily with automation dead and no symptom."* שתי שכנות באותו gather חשופות:

- `_zigbee_reader` (`main.py:172-179`) — `await reader.readline()` **מחוץ** ל-try;
  רק `process_line` מוגן
- `gateway.watchdog()` (`zigbee_gateway.py:637-647`) — `while True: await self.ping()`
  בלי try. `ping` → `_command` → `_write_cmd` → `self._uart.write(...)`
  (`zigbee_gateway.py:171`) חשוף

**למשתמש:** gather מרים → `asyncio.run` חוזר → `main()` מסתיים. ולפי
`host/clean_board.py:5-7`, ה-DMA של ה-RGB ממשיך לשדר את ה-framebuffer לנצח גם
אחרי ש-main.py חזר. לוח קיר שמציג שעה, חדרים וכפתורים — ולא מגיב למגע, לא מעדכן
שעון, ולא מפעיל תזמון. רק ניתוק חשמל מרפא.

### P-3 · רשימות ללא תקרה, מסך ללא גלילה

`rooms_page.py:72-75` מוסיף כרטיס לכל חדר בלי תקרה. אותו דבר ב-`room_page`
(מכשירים) וב-`schedules_page` (תזמונים).

הגלילה מבוטלת בשני מקומות מפורשות: `widgets.py:30` (`w_group` עושה
`remove_flag(SCROLLABLE)`) ו-`shell.py:63` (ל-body). אין scrollbar, אין paging,
אין תקרה — פריט שלא נכנס לגובה מצויר מתחת לקצה הזכוכית ואבוד בשקט.

**הניגוד שהופך את זה לממצא:** `city_picker.py` ו-`settime.py` נושאים תקציב
פיקסלים מדוד בדוקסטרינג ומכוסים ב-`hwtest_ui.py`
(`test_no_widget_escapes_its_parent`, `test_settime_still_fits_with_the_city_row`).
שלושת העמודים עם הרשימות הדינמיות — היחידים שגדלים עם השימוש — לא מכוסים שם כלל.

**למשתמש:** המכשיר הרביעי בחדר קיים באחסון ויורה לפי תזמון, אבל השורה שלו וכפתור
ההדלקה בלתי נגישים. תזמון שאי אפשר לראות, לכבות או למחוק.

### P-4 · `_probe_link` — משימה ללא הפניה, ונעילה

`zigbee_gateway.py:631-633`:

```python
self._probe_inflight = True
try:
    asyncio.create_task(probe())
```

הפרה ישירה של אינווריאנט ב-`CLAUDE.md`. אותו קובץ מקיים אותו נכון ב-`_deliver`
(`:717`) — הקובץ שה-`CLAUDE.md` מצטט כדוגמה טובה.

הנזק גרוע מ"הבדיקה לא רצה": הדגל מורם **לפני** ה-`create_task`. אם המשימה נאספת,
ה-`finally` (`:629`) לא מתבצע, `_probe_inflight` נשאר `True` לתמיד, והשורה 622
חוסמת כל בדיקה עתידית. סיווג timeouts מת עד ריסטרט.

**למה זה שרד:** `tests/test_zigbee_gateway.py:172-185` מכסה את זה — על CPython,
שם הלולאה מחזיקה את המשימה. הטסט עובר וההתנהגות על המכשיר בלתי נראית.

### P-5 · כתיבה בלי מסלול שגיאה

`schedule_add.py:296-306` שולח `schedules.create`/`update` עם `on_ok` בלבד — בלי
`on_err` — ואז `lv.screen_load(_return)` ללא תנאי.

וזה מגיע: ההיסט נלקח מ-`int(buf or "0")` בלי בדיקת טווח (`:232-236`), בזמן
ש-`domain/schedules.py:96` דוחה מחוץ ל-±2880. אותו קובץ **כן** בודק טווח לשעה
ולדקה (`:192-194`) — השמטה, לא החלטה.

`toast.py` קיים בדיוק לזה ומשומש נכון ב-`device_page.py:72-74`.

אותה צורה, קלה יותר: `dev_common.py:23-37` (הדלקה אופטימית ללא `on_ok`/`on_err`,
מתהפכת בשקט אחרי ~3 שניות כשה-poll מחזיר את האמת — ו-`executor.py:58-63` מחזיר
`{"status": "failed"}` כתוצאה מוצלחת, אז גם `on_err` לבדו לא היה תופס),
`rooms_page.py:31`, `room_page.py:71`, `device_page.py:46`,
`schedules_page.py:31,43`.

### P-6 · `RECURRENCE_NAMES` עותק פרטי

`sched_labels.py:26-33` מכריז מחדש את אחת-עשרה מפתחות החזרתיות ש-
`domain/schedules.py:40-45` הוא הבעלים שלהם.

הפאנל **יכול** לייבא מהליבה — `city_picker.py:20` ו-`settime.py:28` עושים בדיוק
את זה — אז מסלול המילוט "שפות שונות → טסט הצמדה" לא חל. ואין טסט:
`test_zman_keys_are_in_sync.py` מצמיד את `ZMAN_NAMES` **באותו קובץ**.

**ביום הפרישה:** `sched_describe.py:36` עושה `.get(recurrence, "")` ומשמיט חלק
ריק, אז שורת התזמון תיקרא "סלון · הדלק · בשעה 07:00" — תיאור של כלל יומי, על
תזמון שיורה רק בראש חודש.

### P-7 · `settime` משכפל ולידציה

`settime.py:132-140` מיישם מחדש את `application/device_time.py:103-110`, כולל
`_days_in_month` פרטי (`:58-62`) שמשכפל את דחיית 30 בפברואר ש-
`gregorian_day_number` כבר מבצע. הפרה של "ולידציה עסקית חיה ב-`api.py`".
מסכים היום (גבולות השנה מיובאים נכון מ-`ports/clock.py`) — אבל זו הגרסה שממנה
מגיעה הודעת השגיאה שהמשתמש רואה.

### P-8 · מחיקת ההיסט בבחירת סימן

`schedule_add.py:225-228` — הקשה על "לפני"/"אחרי" קוראת ל-`_render()`, שמריצה
מחדש `_offset()` → `_numeric()` → `global _buf; _buf = ""` (`:154-155`). הקלדת
`20` ואז בחירת "לפני" מוחקת את ה-20 בשקט; התצוגה חוזרת ל-"0 דק׳".

---

## סדר הפעולות

הסדר לפי סיכון: קודם מה שיכול להפיל את הלוח, ואחר כך מה שמטעה את המשתמש.

### שלב 1 · P-1 (use-after-free)

**1.1 — `shell.sub_page` יחזיר את ה-effect.** שנו את החתימה כך שתחזיר גם את
ה-effect של השעון (או קבלו רשימה שאליה הוא נצבר). `page_create` מעביר הלאה.

**1.2 — כל אתר מחיקה משחרר לפני `delete()`.** `room_page.py:207`,
`device_page.py:175`, `zone_picker.py:55`. ל-`zone_picker` צריך להיווסף
`_teardown` — אין לו רשימה כלל.

**1.3 — הכלל המבני, ולא רק התיקון:** `bind_text`/`effect` שנוצר בתוך מסך חייב
להיצבר ברשימה של אותו מסך. שקלו לעטוף את זה ב-`shell` עצמו — מסך שיודע לפרק את
עצמו — כדי שהעמוד הבא שייבנה לא יוכל לחזור על זה.

**1.4 — הסירו את מגבלת הבדיקה:** אחרי התיקון, `hwtest_ui.py:348-357` יכול למחוק
את מסך הזמנים, וההערה שם צריכה להתעדכן. **המחיקה הזו היא הטסט** — היא בדיוק
התרחיש שנשבר היום.

→ קומיט.

### שלב 2 · P-2 (מוות שקט)

**2.1 — עטפו כל משימה ארוכת-חיים ב-supervisor** שרושם ומפעיל מחדש, במקום להסתמך
על שבע לולאות שכל אחת נזכרת להתגונן בעצמה. `scheduler.run()` כבר מוכיח את הדפוס.

**2.2 — הכניסו את `readline()` לתוך ה-try** ב-`_zigbee_reader` (`main.py:174`),
ועטפו את `await self.ping()` ב-`watchdog` (`zigbee_gateway.py:642`).

**2.3 — `return_exceptions=True` ב-gather** (`main.py:197`) כרשת אחרונה, עם הדפסה
לקונסולה — כדי שגם משימה שנופלת חרף 2.1 לא תיקח את כולן.

**2.4 — סנטינל חי:** שקלו שהמשך ההדפסה של `BOOT_SENTINEL` (או מקבילה תקופתית)
יאפשר להבחין בין "הלוח קפא" ל"הלוח עובד" מהקונסולה. היום אין אות חיים.

→ קומיט.

### שלב 3 · P-3 (חריגה מהמסך)

**3.1 — הרחיבו את `hwtest_ui` לשלושת העמודים.** `_escapes()` כבר קיים שם ועובד;
מה שחסר הוא לזרוע N חדרים / N מכשירים / N תזמונים ולהריץ אותו. **כתבו את הטסט
לפני התיקון** — הוא זה שיקבע את המספר האמיתי, ולא אריתמטיקה על הנייר.

**3.2 — החליטו על מדיניות הגלישה, מוצרית.** שלוש אפשרויות, וזו החלטה שלכם:
paging (עקבי עם איסור הגלילה), הקטנת כרטיס דינמית, או תקרה מוצהרת עם הודעה. מה
שאסור הוא מה שקורה היום — פריט שנעלם בשקט.

**3.3 — תקציב פיקסלים בדוקסטרינג** לכל אחד משלושת העמודים, כמו ב-`city_picker.py`
ו-`settime.py`. זה מה שמאפשר לטסט לתפוס רגרסיה במקום למדוד מחדש.

→ קומיט.

### שלב 4 · P-4 (`_probe_link`)

```python
self._probe_inflight = True
try:
    self._probe_task = asyncio.create_task(probe())
except Exception:
    self._probe_inflight = False
```

הפניה חיה על המופע. ובנוסף — **הדגל צריך תפוגה**, לא רק `finally`: משימה שנאספה
לא מריצה `finally` בהגדרה, אז זמן תפוגה על `_probe_inflight` הוא מה שהופך את
הנעילה לבלתי אפשרית ולא רק לבלתי סבירה.

טסט: אין דרך לשחזר איסוף-זבל של MicroPython על CPython. מה שכן אפשר לבדוק הוא
שהדגל משתחרר גם כאשר ה-probe לא הריץ את ה-`finally` שלו.

→ קומיט.

### שלב 5 · P-5 (מסלולי שגיאה)

**5.1 — בדיקת טווח להיסט** ב-`schedule_add.py:232-236`, כמו זו שכבר קיימת לשעה
ולדקה ב-`:192-194`.

**5.2 — `on_err` + toast בכל פעולת כתיבה**, וניווט **רק** מתוך `on_ok`. הרשימה:
`schedule_add.py:296-306`, `rooms_page.py:31`, `room_page.py:71`,
`device_page.py:46`, `schedules_page.py:31,43`.

**5.3 — `dev_common.py:23-37` דורש יותר מ-`on_err`:** `executor.py:58-63` מחזיר
`{"status": "failed"}` כדיספאץ' מוצלח, אז יש לבדוק את ה-`status` בתוך `on_ok`.
לפי סמנטיקת המסירה ב-`CLAUDE.md`, הצגת מצב לא מוכח כמילת המכשיר עצמו היא בדיוק
מה שאסור.

→ קומיט.

### שלב 6 · P-6, P-7, P-8

- `sched_labels.py` מייבא `RECURRENCE_TYPES` מהדומיין; המילון שנשאר ממפה מפתח
  לתווית עברית בלבד, וטסט מוודא שהוא מכסה את הדומיין במלואו — בדיוק כמו
  `test_zman_keys_are_in_sync.py` באותו קובץ
- `settime.py` קורא ל-ולידציה של `device_time` במקום לשכפל אותה
- `_numeric()` שומר את `_buf` על render חוזר

→ קומיט.

### שלב 7 · אימות

```powershell
$env:PYTHONPATH = "src"; python -m pytest -q
ruff check .
```

ועל חומרה — ואין לזה תחליף בענף הזה, כי LVGL לא רץ מחוץ ללוח:

```powershell
python products/panel/host/run_hwtest_ui.py      # קריטי: P-1 ו-P-3
python products/panel/host/run_hwtest.py
```

**`run_hwtest_ui.py` הוא הבדיקה המכריעה כאן.** אחרי שלב 1 הוא אמור למחוק מסכים
בלי תקלה; אחרי שלב 3 הוא אמור לתפוס חריגה בשלושת העמודים.

---

## מה לא נבדק

- **התנהגות LVGL בפועל.** כל הממצאים נובעים מקריאה והצלבה מול האינווריאנטים
  הכתובים, לא מהרצה — LVGL לא ניתן להרצה מחוץ ללוח, וזה הפער שהאודיט הקודם הצהיר
  עליו. הספירה המדויקת ב-P-3 (כמה פריטים נכנסים) חייבת להימדד על החומרה; הפגם
  המבני — רשימה ללא תקרה במיכל שלא ניתן לגלול — ודאי.
- **מסלול המגע.** `display.py` וכיול המגע לא נסקרו לעומק.
- **`hwtest/` עצמו** (317 + 422 + 42 שורות) נקרא רק במידה שנדרשה כדי לאמת ממצא.
