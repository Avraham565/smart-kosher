# תוכנית עבודה ל-Claude Code — smart-kosher

מקור: סקירה מלאה של הריפו, 2026-08-15, מול `main` בקומיט `eda4233`.
מסמכי רקע: `docs/review-2026-08-15-conclusions.md`, `docs/h2-remediation-plan.md`,
`docs/panel-remediation-plan.md`, `docs/panel-update-model.md`.

> ## מצב — עודכן 2026-08-20, ענף `fix/review-2026-08` (37 קומיטים, נדחף)
>
> **הסוויטה: 462 עוברים, 1 מדולג, 1,500 subtests.**
> `ruff` נקי. הסריקה הממצה של הזמנים עוברת.
>
> ### בוצע
>
> | # | מה | אימות |
> |---|---|---|
> | 1 | effect של השעון משוחרר במחיקת מסך | ✅ **חומרה** — `0 -> 0`, `4 -> 4` |
> | 2 | משימה שנופלת + **סנטינל חי** (סעיף 2.4) | ✅ **חומרה** — `dead tasks: status`, מונה 2987→2489 |
> | 3 | רשימות מדפדפות (paging) | ✅ **חומרה** — 4/3/4 = מדידה בדיוק |
> | 4 | מסלולי שגיאה בכתיבות | ✅ **חומרה** — CAS: 172ms מול 365ms |
> | 5 | `RECURRENCE_NAMES` | ⛔ **הממצא לא מתקיים** — ראה שם |
> | 6 | שני P3 בפאנל | ✅ 64,282 השוואות תאריך |
> | 7 | עמידות רישום ה-Zigbee | ✅ 6/7 טסטים נכשלים על הקוד הישן |
> | 8 | sync בכל append ליומן | ✅ נכשל על הישן (1 מתוך 3) |
> | 9 | קריאת יומן ריק/לא-מפוענח | ✅ 2 נכשלים על הישן |
> | 10 | `ack_unjournaled` לא נשלח מחדש | ✅ שלוש מוטציות, כל אחת האדימה |
> | 11 | נעילת ה-probe נושאת תפוגה | ✅ מוטציה — רק הטסט החדש האדים |
> | 12 | `wait_for_report` מבחין לפי endpoint | ⚠️ **הפרימיטיב בלבד — התסמין חי בייצור.** אף קורא לא מעביר endpoint, ולכן החיובי-הכוזב עדיין מתרחש. **משימה 25 סוגרת.** מוטציות: 2 ו-1 האדימו |
> | 14 | `RepositoryValidationError` | היה בבסיס |
>
> **כל ארבעת ה-P0 סגורים.**
>
> ### עבודות שנוספו ולא היו ברשימה
>
> - **פריסת האשף** (`schedule_add`) — בלוק תגיות משוריין + דפדוף. ✅ חומרה
> - **`zmanim_page` + `clock.bind_date`** — אותה משפחה של משימה 1
> - **`tests/test_hwtest_payload_is_complete.py`** — ה-PAYLOAD פספס 14 שמות,
>   ואף רץ לא סנכרן את הליבה. `sync_core` בשלושת הרצים (21 שניות, נמדד)
> - **`data-sheets/MINI-ZB2GS.md`** — אין כפתור לערוץ
> - **`CLAUDE.md`: "כשבדיקה חוזרת ירוקה"** — חמישה ירוקים כוזבים ביום אחד
>
> ### נותרו — כולן P1/P2, אף אחת לא יכולה להשבית לוח או למחוק בית
>
> **13, 15, 17** (`zigbee_gateway`) · **16** (`api`/`views`) · **18–22**
> (קושחת H2) · **23** (hub/web/tools) · **24, 25** (`control_service`)
>
> **ההכרעה במשימה 10, לתיעוד:** אוצר המילים גר אצל **היצרן** — ארבעה קבועי
> מודול ב-`executor.py`, ו-`scheduler`/`control_service` מייבאים. **המדיניות**
> — אילו סטטוסים לא נשלחים שוב — נשארה אצל המתזמן כ-`_SETTLED`, כי היא שלו.
> `EXECUTION_SUCCESS_STATUSES` ב-`ports/` הוא **אוצר מילים אחר** (של הגייטוויי)
> — לא מוזג. שתי השכבות חולקות את הערך `"failed"` בפועל: הקושחה פולטת אותו על
> החוט (`zb.c:285,316`), `zigbee_gateway.py:663` מתרגם אותו ל-`error`,
> ו-`executor.py:33` דוחה כל סטטוס מחוץ ל-`GATEWAY_ALL_STATUSES`. **ההפרדה
> נשענת על שלוש נקודות, לא על אחת** — אל תסיר אף אחת מהן בלי לבדוק את השתיים.
>
> ### חוב מדידה שהצטבר — הרצת חומרה אחת פותרת שלושתם
>
> 1. `_save_registry` = 3 פעולות קובץ — האם לאחד כתיבות בהצטרפות
> 2. `_append` + sync בכל ירייה — מה עולה שבת עמוסה
> 3. חלון 2.6 שניות מול הנחת 355ms ב-`main.py:56-62` (`docs/panel-update-model.md`)

> ## עדכון — בסיס העבודה הוא `60ba7e3`, לא `eda4233`
>
> הענף `wip/pre-review-state` נסקר ואומת: **400 טסטים + 1,475 subtests עוברים,
> ruff נקי, הסריקה הממצה של הזמנים עוברת, והצלבה עצמאית מול `pyluach` על 73,414
> ימים מחזירה אפס אי-התאמות.** מזג אותו ל-`main` לפני שתתחיל; ענף התיקונים יוצא
> ממנו.
>
> **מה שהוא כבר מכיל, ומשנה את הרשימה למטה:**
>
> - **משימה 14 בוצעה.** `RepositoryValidationError` יורש מ-`ValueError`. **דלג.**
> - **משימה 5 השתנתה.** טסט ההצמדה כבר קיים; נשארה רק הסרת הכפילות. ראה שם.
> - שלושה טסטי הצמדה חדשים — `test_core_is_micropython_safe.py`,
>   `test_schedule_vocab_is_in_sync.py`, `test_repository_contract.py` — הם
>   **רשת הביטחון של כל שאר העבודה**. אם אחד מהם נכשל אחרי שינוי שלך, ההנחה
>   הראשונה היא שהשינוי שגוי.
> - שינויים נוספים שאינם נוגעים לאף משימה: `collect_after_request` מפורש בכל
>   מוצר, `bad_frame` מול `bad_crc` ב-`uart_codec`, `pyrightconfig` ל-3.8,
>   והסרת קוד מת ב-`astronomy.py` ו-`ui_home.py` (אומת: אפס הפניות תלויות).

---

## הוראות הפעלה — קרא אותן לפני המשימה הראשונה

אתה עומד לבצע **22 משימות עצמאיות** (14 כבר בוצעה). הן ממוינות לפי סיכון ולפי
אזור בקוד.

### חוקי ברזל

1. **משימה אחת בכל פעם.** אל תתחיל משימה לפני שהקודמת סגורה לגמרי — כולל אימות
   וקומיט. אל תקרא קדימה ואל תתכנן שתי משימות יחד.
2. **קומיט אחד למשימה.** לא קומיט אחד לשתיים, לא שתי משימות בקומיט.
3. **אל תיגע בכלום מחוץ להיקף המשימה.** כל משימה מפרטת `קבצים בהיקף`. קובץ שלא
   מופיע שם — אל תערוך אותו, גם אם אתה רואה בו משהו שנראה שגוי. אם מצאת בעיה
   מחוץ להיקף, **רשום אותה בסוף התשובה שלך ותמשיך**.
4. **אמת את הממצא לפני שאתה מתקן.** מספרי השורות במסמך נכונים ל-`eda4233`,
   והבסיס שלך הוא `60ba7e3` — **ייתכן שהם זזו**. קרא את הקוד ואשר שהבעיה קיימת.
   **אם הממצא לא מתקיים — אל תתקן, דווח, ועבור הלאה.**
5. **אל תעבור משימה שהאימות שלה נכשל.** עצור ודווח.
6. **אל תשנה טסטים כדי שיעברו.** אם טסט קיים נכשל אחרי שינוי — או שהשינוי שגוי,
   או שהטסט מקבע התנהגות שגויה. הכרע במפורש והסבר.
7. **אל תעשה refactor.** תיקון מינימלי בלבד.

### פקודות האימות

הרץ אחרי כל משימה. שלוש הראשונות תמיד; רביעית רק במשימות קושחה.

```bash
PYTHONPATH=src python -m pytest -q          # ציפייה: 400 passed, 1 skipped
ruff check .                                # ציפייה: All checks passed
PYTHONPATH=src ZMANIM_FULL_REFERENCE=1 python -m pytest -q tests/test_zmanim_reference.py
bash firmware/h2_coordinator/host_test/run.sh   # קושחה בלבד. ציפייה: 0 failures
```

> ב-PowerShell: `$env:PYTHONPATH = "src"` במקום התחילית.

### מסך החומרה

משימות מסומנות **[חומרה]** אי אפשר לאמת בלי הלוח. **בצע אותן, קומט אותן, ואל
תסמן אותן כגמורות** — הן ממתינות ל:

```powershell
python products/panel/host/run_hwtest_ui.py
python products/panel/host/run_hwtest.py
python products/panel/host/run_hwtest_zmanim.py
```

ולקושחה: `firmware/tools/build_h2_coordinator.ps1` ואז `run_hwtest.py`.

### סגנון קומיט

התבנית של הריפו: `fix(scope): משפט שאומר מה השתנה מבחינת התנהגות`.
דוגמה מההיסטוריה: `fix(panel): the UI suite stops breaking the rules it exists to protect`.
הודעות באנגלית.

### לפני הכול

```bash
git checkout -b fix/review-2026-08
PYTHONPATH=src python -m pytest -q && ruff check .
```

**אם הבסיס לא ירוק — עצור ודווח. אל תתחיל.**

---

# בלוק א׳ — לוח הקיר (`products/panel`)

## משימה 1 — [חומרה] שחרור effect של השעון בעת מחיקת מסך

**חומרה: P0.** גורם לכתיבה לזיכרון משוחרר בניווט רגיל בין חדרים.

**קבצים בהיקף:** `products/panel/device/shell.py`, `room_page.py`,
`device_page.py`, `zone_picker.py`

**הרקע.** `shell.py:51-54` בונה שעון פינתי בכל תת-עמוד וקורא `clock.bind_time(mini)`
**וזורק את ערך ההחזרה**. ה-effect נרשם ל-`store.now` ומוחזק חזק ב-`_observers`
(`reactive.py:50,73-74`), ולכן לא ניתן לאיסוף ולא ניתן לשחרור — ההפניה היחידה
אליו אבדה.

שלושה עמודים מוחקים מסך שנבנה דרך ה-shell: `room_page.py:207`,
`device_page.py:175`, `zone_picker.py:55`. ה-`_teardown()` שלהם משחרר רק effects
שהמודול עצמו צבר (`room_page.py:145-151`, `device_page.py:111-114`) — של ה-shell
אינו באף רשימה. ל-`zone_picker` אין רשימה כלל.

`_clock_refresh` (`main.py:118`) כותב ל-`store.now` בשינוי הדקה הבא, וה-effect
היתום קורא `set_text` על תווית משוחררת. `reactive.py:87` תופס `Exception` — לא
תקלת native.

**זה מתועד אצלכם:** `products/panel/hwtest/hwtest_ui.py:348-357` מתאר בדיוק את
הסכנה ונמנע ממחיקת המסך בגללה.

**מה לעשות.**

1. `shell.sub_page` יחזיר גם את ה-effect של השעון (או יקבל רשימה שאליה יצבור
   אותו). `page_create` מעביר הלאה. שמור על תאימות הקוראים הקיימים.
2. שלושת אתרי המחיקה משחררים את ה-effect **לפני** `delete()`.
3. הוסף `_teardown` ל-`zone_picker.py` — אין לו.
4. עדכן את ההערה ב-`hwtest_ui.py:348-357` והפוך את המחיקה לאפשרית. **המחיקה
   הזאת היא הטסט.**

**אימות:** שלוש הפקודות. ואז [חומרה] `run_hwtest_ui.py` — הוא אמור למחוק מסכים
בלי תקלה.

**אל תעשה:** אל תשנה את מודל ה-Signal/effect ב-`reactive.py`. אל תיגע בעמודים
שלא מוחקים מסכים.

---

## משימה 2 — [חומרה] המשימות של הפאנל לא יורידו את הלוח

**חומרה: P0.** חריגה במשימה אחת מקפיאה את כל הלוח, והמסך נשאר נראה תקין.

**קבצים בהיקף:** `products/panel/device/main.py`,
`src/smart_kosher/adapters/zigbee_gateway.py` (רק `watchdog`)

**הרקע.** `main.py:197` — `asyncio.gather` על שבע משימות **בלי
`return_exceptions=True`** ובלי supervisor.

`scheduler.run()` מוקשח מפורשות, עם הערה שמנסחת את הסיכון: *"A tick must never
kill the loop: a raise here would leave the panel rendering happily with
automation dead and no symptom."* שתי שכנות חשופות:

- `_zigbee_reader` (`main.py:172-179`) — `await reader.readline()` **מחוץ** ל-try
- `gateway.watchdog()` (`zigbee_gateway.py:641-647`) — `while True: await self.ping()`
  בלי try. `ping` → `_command` → `_write_cmd` → `self._uart.write(...)`
  (`zigbee_gateway.py:171`) חשוף

`asyncio.run` חוזר, `main()` מסתיים — ולפי `products/panel/host/clean_board.py:5-7`
ה-DMA של ה-RGB ממשיך לשדר את ה-framebuffer לנצח. לוח שנראה חי ומת.

**מה לעשות.**

1. הכנס את `readline()` לתוך ה-try ב-`_zigbee_reader` (`main.py:174`).
2. עטוף `await self.ping()` ב-`watchdog` (`zigbee_gateway.py:642`) ב-try/except
   שמדפיס וממשיך. הלולאה חייבת לשרוד.
3. `return_exceptions=True` ב-gather (`main.py:197`), עם הדפסה של כל חריגה
   שחוזרת — כרשת אחרונה.

**אימות:** שלוש הפקודות. ואז [חומרה] `run_hwtest.py`.

**אל תעשה:** אל תבנה מנגנון supervisor גנרי עכשיו. שלושת השינויים לעיל בלבד.
אל תיגע ב-`scheduler.run()` — הוא כבר נכון.

---

## משימה 3 — [חומרה] רשימות שלא חורגות מהמסך

**חומרה: P1.**

**קבצים בהיקף:** `products/panel/device/rooms_page.py`, `room_page.py`,
`schedules_page.py`, `products/panel/hwtest/hwtest_ui.py`

**הרקע.** `rooms_page.py:72-75` מוסיף כרטיס לכל חדר בלי תקרה; אותו דבר ב-`room_page`
(מכשירים) וב-`schedules_page` (תזמונים). הגלילה מבוטלת מפורשות ב-`widgets.py:30`
(`w_group` עושה `remove_flag(SCROLLABLE)`) וב-`shell.py:63`. פריט שלא נכנס מצויר
מתחת לקצה הזכוכית ואבוד — בלי שגיאה ובלי רמז.

`city_picker.py` ו-`settime.py` נושאים תקציב פיקסלים בדוקסטרינג ומכוסים ב-`hwtest_ui`.
שלושת העמודים עם הרשימות הדינמיות — לא.

**מה לעשות. בסדר הזה:**

1. **קודם הטסט.** הרחב את `hwtest_ui.py` לשלושת העמודים: זרע N פריטים והרץ את
   `_escapes()` הקיים. **הטסט הוא שיקבע את המספר האמיתי — לא אריתמטיקה על הנייר.**
2. **החלטה מוצרית — עצור ושאל את המשתמש.** שלוש אפשרויות: paging (עקבי עם איסור
   הגלילה), הקטנת כרטיס דינמית, או תקרה מוצהרת עם הודעה. **אל תבחר לבד.**
3. מימוש מה שנבחר + תקציב פיקסלים בדוקסטרינג של כל אחד משלושת העמודים.

**אימות:** שלוש הפקודות. ואז [חומרה] `run_hwtest_ui.py` תופס חריגה לפני התיקון
ולא אחריו.

---

## משימה 4 — מסלולי שגיאה בפעולות כתיבה בפאנל

**חומרה: P2.**

**קבצים בהיקף:** `products/panel/device/schedule_add.py`, `dev_common.py`,
`rooms_page.py`, `room_page.py`, `device_page.py`, `schedules_page.py`

**הרקע.** `schedule_add.py:296-306` שולח `schedules.create`/`update` עם `on_ok`
בלבד ואז מנווט ללא תנאי. וזה מגיע: ההיסט נלקח מ-`int(buf or "0")` בלי בדיקת טווח
(`:232-236`) בזמן ש-`domain/schedules.py:96` דוחה מחוץ ל-±2880. אותו קובץ **כן**
בודק טווח לשעה ולדקה (`:192-194`).

**מה לעשות.**

1. בדיקת טווח להיסט ב-`:232-236`, בסגנון של `:192-194`.
2. `on_err` + toast בכל פעולת כתיבה, וניווט **רק** מתוך `on_ok`:
   `schedule_add.py:296-306`, `rooms_page.py:31`, `room_page.py:71`,
   `device_page.py:46`, `schedules_page.py:31,43`. הדוגמה הנכונה:
   `device_page.py:72-74`.
3. `dev_common.py:23-37` דורש יותר: `executor.py:58-63` מחזיר `{"status": "failed"}`
   כדיספאץ' **מוצלח**, אז בדוק את ה-`status` בתוך `on_ok`.

**אימות:** שלוש הפקודות.

---

## משימה 5 — ~~`RECURRENCE_NAMES`~~ · **הממצא לא מתקיים. אל תבצע.**

> **נבדק 2026-08-18 והוכרע שלא לתקן**, משתי סיבות בלתי-תלויות:
>
> 1. `RECURRENCE_NAMES` הוא **מפת תוויות**, לא הכרזה שנייה. כל מפתח שהוא מתייג
>    חייב להיכתב כדי לקבל תווית — ייבוא `RECURRENCE_TYPES` לא מסיר ולו שורה.
> 2. **ה-import הוא בדיוק זה שחסום.**
>    `test_zman_keys_are_in_sync.py:81-84` אוכף `assertNotIn("import", ...)` על
>    כל הקובץ, ו-`CLAUDE.md` מסווג אותו כאילוץ מכשיר מתועד — המקרה שבו טסט
>    הצמדה הוא התשובה הנכונה. (זהירות: זו בדיקת substring, אז גם המילה
>    `important` בהערה תפיל אותה.)
>
> הרשת קיימת ומלאה: `test_panel_labels_cover_exactly_the_domain` בודק **שוויון
> מלא**. ההנמקה נכתבה כהערה בראש `sched_labels.py` (קומיט `886d232`), כי זה היה
> הקורא השני שהסיק שיש כאן כפילות להסיר.

**חומרה: P3** (הורדה מ-P2 — ראה למטה).

**קבצים בהיקף:** `products/panel/device/sched_labels.py`

**מה כבר נעשה.** `tests/test_schedule_vocab_is_in_sync.py` קיים בבסיס שלך, והוא
רחב ממה שביקשתי במקור: הוא מצמיד חזרתיות **ופעולות**, על פני הדומיין, תוויות
הפאנל, תוויות ה-JS של הלקוח, ואשף הפאנל — וגם מקבע ש-`toggle` לא מוצע בתזמון.
**אל תיגע בו ואל תכתוב אותו מחדש.**

לכן החומרה ירדה: הסחף שתיארתי במקור — תזמון של ראש חודש שנקרא כמו כלל יומי —
**כבר לא יכול לקרות בשקט.** הטסט יתפוס אותו.

**מה נשאר.** `sched_labels.py:26-33` עדיין מכריז מחדש את אחת-עשרה המפתחות
ש-`domain/schedules.py:40-45` הוא הבעלים שלהם. לפי `CLAUDE.md` הכלל הוא "מקור אחד
ששניהם מייבאים, ורק כשזה בלתי אפשרי — טסט הצמדה", והפאנל **כן** יכול לייבא
(`city_picker.py:20`, `settime.py:28` עושים זאת). אז זו כפילות שנשארה, עכשיו עם
רשת מתחתיה.

**מה לעשות.** ייבא `RECURRENCE_TYPES` מהדומיין; המילון שנשאר ממפה מפתח → תווית
עברית בלבד. הטסט הקיים חייב להמשיך לעבור בלי שינוי — **זו הראיה שהתיקון נכון.**

**אימות:** שלוש הפקודות, ובמיוחד `test_schedule_vocab_is_in_sync.py`.

---

## משימה 6 — שני תיקוני P3 בפאנל

**קבצים בהיקף:** `products/panel/device/settime.py`, `schedule_add.py`

1. `settime.py:132-140` משכפל את `application/device_time.py:103-110`, כולל
   `_days_in_month` פרטי (`:58-62`). קרא לוולידציה של הליבה במקום לשכפל.
2. `schedule_add.py:225-228` — בחירת "לפני"/"אחרי" מריצה `_render()` →
   `_offset()` → `_numeric()` → `global _buf; _buf = ""` (`:154-155`), ומוחקת מספר
   שכבר הוקלד. שמור את `_buf` על render חוזר.

**אימות:** שלוש הפקודות.

---

# בלוק ב׳ — הליבה (`src/smart_kosher`)

## משימה 7 — רישום ה-Zigbee יקבל עמידות

**חומרה: P0.** כתיבה קטועה אחת מוחקת את כל המכשירים המשויכים, לצמיתות.

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py` (רק `_load_registry`
ו-`_save_registry`), `tests/test_zigbee_gateway.py`

**הרקע.** `zigbee_gateway.py:143-160` הוא הפרסיסטר היחיד בריפו שלא מייבא את
`_atomic_io`:

```python
def _load_registry(self):
    try:
        with open(self._registry_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}          # ← אוסף ריק בשקט

def _save_registry(self):
    with open(self._registry_path, "w") as f:   # ← ישירות על הקובץ החי
        json.dump(self._registry, f)
```

מפר ארבעה חוזים: temp→backup→replace, `.bak` נשמר, שחזור מ-`.tmp`/`.bak`, וכן
*"Corrupt data is reported explicitly and is never silently replaced with an empty
collection"* (README). הרישום נכתב מחדש בכל `device_joined` / `device_endpoints` /
`device_clusters` / שינוי reporting — כלומר במטח, כשבית שלם חוזר מהפסקת חשמל.

**מה לעשות.**

1. ייבא `_atomic_io` והשתמש בו בדיוק כמו `JsonRepository._save_collection`
   (`json_repository.py:162-174`) — זו הדוגמה להעתיק.
2. `_load_registry` ינסה `path`, `.tmp`, `.bak` לפי הסדר.
3. כשכולם נכשלו — **אל תחזיר `{}` בשקט.** דווח מפורשות, בדפוס
   `SettingsStore.load_error` (`settings_store.py:23,76`).
4. טסטים: קובץ פגום לא מוביל לרישום ריק; `.bak` משמש לשחזור; שמירה לא מפילה
   על טעינה חלקית.

**אימות:** שלוש הפקודות.

**אל תעשה:** אל תשנה את מבנה הרישום ואל תיגע בשאר `zigbee_gateway.py`.

---

## משימה 8 — רשומות ה-journal יגיעו לפלאש

**חומרה: P0.** על MicroPython, כל append אחרי הראשון לא מגיע למדיה.

**קבצים בהיקף:** `src/smart_kosher/adapters/json_repository.py` (רק `_append`)

**הרקע.**

```python
def _append(self, record):
    existed = _exists(self._log_path)
    with open(self._log_path, "a") as handle:
        ...
        _flush_file(handle)
    if not existed:
        _sync_filesystem()      # ← רק בפעם הראשונה אי-פעם
```

ו-`_atomic_io.py:48-51` יוצא מוקדם כש-`os.fsync` חסר — בדיוק המצב ב-MicroPython,
כפי שהדוקסטרינג של אותו קובץ אומר בשורות 14-15. `os.sync()` **כן** קיים שם והוא
הפרימיטיב היחיד שעובד. שתי האחיות מסנכרנות ללא תנאי (`_write_compacted:345`,
`_save_collection:170`) — רק המסלול הנפוץ ביותר מדלג.

**התוצאה:** אירוע מבוצע, החשמל נופל, ובאתחול `was_executed()` מחזיר False
וה-catch-up יורה שוב.

**מה לעשות.** הפוך את `_sync_filesystem()` ללא-מותנה ב-`_append`. אם יש חשש
לביצועים — תעד את המדידה, אל תנחש.

**אימות:** שלוש הפקודות.

---

## משימה 9 — `journal.log` ריק לא ייקרא כ"שום דבר לא בוצע"

**חומרה: P1.**

**קבצים בהיקף:** `src/smart_kosher/adapters/json_repository.py` (`_read_log`,
`_load_log`), `tests/test_storage.py`

**הרקע.** `_read_log` על קובץ ריק מחזיר `([], False)` בלי שגיאה. `_load_log:306`
בודק `if not any(_exists(...))` — הקובץ הראשי קיים באורך אפס, אז הוא ממשיך,
מצליח על המועמד הראשון, ומחזיר `True` בשורה 323. **`.tmp` ו-`.bak` לא נפתחים
לעולם** — למרות ש-`.bak` נוצר בכל compaction (`:341-342`).

הדוגמה הנכונה קיימת: `load_all:127` דורש ששלושת הקבצים יהיו חסרים לפני ברירת
מחדל ריקה.

**בנוסף (אותו קובץ, אותו קומיט):** `_load_log:324` תופס
`(OSError, RepositoryCorruptionError)`. `handle.readlines()` (`:281`) זורק
`UnicodeDecodeError` — שהוא `ValueError` ולא נתפס — ומפיל את האתחול לפני
שנוסה `.bak`.

**מה לעשות.**

1. קובץ ראשי ריק כשקיים `.tmp`/`.bak` לא-ריק → נסה אותם.
2. תפוס גם `ValueError` ב-`_load_log:324` והמר ל-`RepositoryCorruptionError`.
3. טסטים לשני המקרים.

**אימות:** שלוש הפקודות.

---

## משימה 10 — `ack_unjournaled` יפסיק להישלח מחדש בכל טיק

**חומרה: P1.**

**קבצים בהיקף:** `src/smart_kosher/application/scheduler.py`,
`tests/test_panel_scheduler.py`

**הרקע.** `scheduler.py:156` — `_JOURNALLED = ("executed", "already_executed")`,
וכל השאר נחשב pending ומחזיר את החלון אחורה (`_advance_to:172-184`).

`Executor` מקיים את החוזה (`executor.py:49-55` — לא מנסה שוב). המתזמן מבטל אותו.
ה-README:145-146 חד: *"the command is not immediately retried."*

ההערה ב-`:154-155` חושפת את הכשל: *"anything else has not actually reached its
device"* — לא נכון ל-`ack_unjournaled`, שמשמעותו "ה-ACK התקבל, המכשיר פעל, רק
היומן נכשל".

**התוצאה:** ב-`TICK_SECONDS=30`, ~240 שליחות כפולות לאורך חלון של 120 דקות.
משתמש שמכבה ידנית מוצא את האור דולק שוב תוך 30 שניות — בניגוד לכלל "המוח מכבד
התערבות ידנית".

**מה לעשות.** `ack_unjournaled` לא יגרום ל-rewind. `failed` כן ימשיך לגרום.
עדכן את ההערה. הוסף טסט.

**אימות:** שלוש הפקודות.

---

## משימה 11 — `_probe_link` לא יינעל

**חומרה: P1.**

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py` (רק `_probe_link`),
`tests/test_zigbee_gateway.py`

**הרקע.** `:631-633`:

```python
self._probe_inflight = True
try:
    asyncio.create_task(probe())
```

הפרה ישירה של אינווריאנט ב-`CLAUDE.md`. אותו קובץ מקיים אותו נכון ב-`_deliver`
(`:717`) — הקובץ שה-`CLAUDE.md` מצטט כדוגמה טובה.

הנזק גרוע מ"הבדיקה לא רצה": הדגל מורם **לפני** ה-`create_task`. משימה שנאספה לא
מריצה `finally` (`:629`), `_probe_inflight` נשאר `True` לתמיד, ו-`:622` חוסם כל
בדיקה עתידית עד ריסטרט.

`tests/test_zigbee_gateway.py:172-185` מכסה את זה — על CPython, שם הלולאה מחזיקה
את המשימה. לכן זה שרד.

**מה לעשות.**

1. שמור הפניה חיה על המופע.
2. **הוסף תפוגה ל-`_probe_inflight`.** משימה שנאספה לא מריצה `finally` בהגדרה,
   אז רק תפוגה הופכת את הנעילה לבלתי אפשרית ולא רק לבלתי סבירה.
3. טסט: הדגל משתחרר גם כשה-probe לא הריץ את ה-`finally` שלו.

**אימות:** שלוש הפקודות.

---

## משימה 12 — `wait_for_report` לא יאושר ע"י הגאנג השני

**חומרה: P1.**

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py` (`_on_state`,
`wait_for_report`), `tests/test_zigbee_gateway.py`

**הרקע.** הקושחה **כן** שולחת `endpoint` בכל `attribute_report`
(`firmware/h2_coordinator/main/zb.c:1033`), אבל `_on_state:477` ממפתח על
`_ieee_for_short(short_addr)` בלבד **וזורק את `payload["endpoint"]`**, ואז
`:484` מעיר את כל הממתינים לאותו ieee.

זה חורג מהפער הידוע ב-README. הפער אומר ששני גאנגים דורסים זה את מצבו של זה.
כאן **פרימיטיב האישור מחזיר חיובי כוזב**: מבקשים אישור שגאנג 1 נדלק, הפקודה
אבדה, המשתמש לוחץ ידנית על גאנג 2 — והמערכת מדווחת `{"confirmed": True}`.
`observed_state` נמצא ב-`EXECUTION_SUCCESS_STATUSES`, אז זה נכנס ליומן כבוצע.

**מה לעשות.** הבחן לפי endpoint במסלול ההמתנה, **בלי לשבור את המצב הקיים**:
כשה-endpoint לא ידוע, ההתנהגות חייבת להישאר כמו היום. הוסף טסט לשני הגאנגים.

**אימות:** שלוש הפקודות.

**הערה.** זה **לא** מתקן את הפער הידוע (`_states` ממופתח לפי ieee). זו עבודה
נפרדת. אל תתחיל אותה כאן.

---

## משימה 13 — `send()` לא יזרוק, ו-`_pending` לא ידלוף

**חומרה: P1.**

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py` (`_command`,
`_deliver`), `tests/test_zigbee_gateway.py`

**הרקע.** `_command:544-545` מכניס ל-`self._pending[rid]` **לפני** `_write_cmd`,
ולא מנקה אם הכתיבה זורקת. `_deliver` מגן על מסלול ריבוי-היעדים (`:704-711`, עם
הערה שמסבירה למה) — ומסלול היעד היחיד (`:690`) חשוף. אז `send()` יכול לזרוק,
בניגוד לדוקסטרינג שלו (`:652-653`): *"Never raises on delivery problems"*.

**מה לעשות.** נקה את `_pending` כשהכתיבה נכשלת; הגן על מסלול היעד היחיד כמו על
מסלול ריבוי-היעדים. טסט: `uart.write` שזורק לא מפיל את `send()` ולא מדליף.

**אימות:** שלוש הפקודות.

---

## משימה 14 — ~~שגיאות ולידציה יחזרו כ-400 ולא כ-500~~ · **בוצעה, דלג**

> **אל תבצע את המשימה הזאת.** היא כבר בבסיס שלך (`60ba7e3`).
> `RepositoryValidationError` יורש עכשיו מ-`ValueError` ולא מ-`RepositoryError`,
> עם דוקסטרינג שמסביר גם למה לא `(RepositoryError, ValueError)` — ריבוי ירושה
> מטיפוס native מוגבל ב-MicroPython, וזה היה הופך אותה למחלקה היחידה כזאת בקוד
> שנצרב ללוח. `RepositoryCorruptionError` נשאר בכוונה מחוץ ל-`ValueError`, כי
> אחסון פגום הוא תקלה פנימית ו-500 היא התשובה הנכונה לו.
> `tests/test_repository_contract.py` מריץ את אותן טענות מול **שתי** המימושים,
> וסוגר בכך את הפער שהסתיר את הבאג: החבילה בדקה `MemoryRepository` בלבד.
>
> **קרא את הסעיף למטה רק כרקע. אל תערוך שום קובץ.**

**חומרה: P2. מופיע רק על החומרה, לא בטסטים.**

**קבצים בהיקף:** `src/smart_kosher/ports/repository.py`,
`src/smart_kosher/adapters/json_repository.py`,
`src/smart_kosher/application/api.py`, `tests/`

**הרקע.** `RepositoryError` יורש מ-`Exception`, לא מ-`ValueError`
(`json_repository.py:22`). `upsert` ממיר `ValueError` מהדומיין ל-
`RepositoryValidationError` (`:194-195`). `api.py:232` תופס
`(DeviceValidationError, ScheduleValidationError, ValueError)` → 400, אז זה נופל
ל-`except Exception` → `internal error`, 500, בלי הודעה.

```
JsonRepository  | hour 25 -> internal    | "internal error"
MemoryRepository| hour 25 -> bad_request | "fixed_time hour must be in 0..23"
```

הטסטים ו-`dev_server.py` משתמשים ב-`MemoryRepository`, לכן זה בלתי נראה בפיתוח.

**מה לעשות.** `api.py` **לא רשאי לייבא מ-`adapters`**. שתי דרכים לגיטימיות: העבר
את טיפוס השגיאה ל-`ports/repository.py`, או ש-`RepositoryError` יירש מ-`ValueError`.
**בחר אחת והסבר למה.** הוסף טסט שרץ מול `JsonRepository` ולא רק מול הזיכרון.

**אימות:** שלוש הפקודות.

---

## משימה 15 — מפסק הזרם לא ינוטרל בזמן פינג

**חומרה: P2.**

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py` (`ping`,
`_command`, `watchdog`), `tests/test_zigbee_gateway.py`

**הרקע.** `ping():816` עושה `was_down, self._down = self._down, False` ומשחזר רק
אחרי ה-await (`:821-822`). בזמן שהקישור למטה ה-watchdog מריץ `ping` (עד 1500ms
עם `_down == False`) ואז ישן 2000ms — כלומר **1500 מכל 3500 מ"ש ההגנה מנוטרלת**.

`_deliver_one:741-744` בודק `not self._down`, אז בחלון הזה כל המכשירים מסומנים
`unreachable`. תזמון קבוצתי ל-50 מנורות מול רכזת מנותקת מסמן 50 מתגים בריאים
כתקולים.

**מה לעשות.** אפשר לפינג לעקוף את ה-fail-fast **בלי** לשנות את `_down` הגלובלי —
דגל מקומי לבקשה, לא מצב משותף.

**אימות:** שלוש הפקודות.

---

## משימה 16 — שני תיקוני P2 בליבה

**קבצים בהיקף:** `src/smart_kosher/application/api.py`,
`src/smart_kosher/application/views.py`

1. `api.py:378` — `_settings_update` מחזיר `self._settings.get()` הגולמי במקום
   ההיטל של `_settings_get` (`:353-358`). מכשיר עם `candle_offset: 40` ישן יציג
   40 אחרי עריכת עיר, בזמן שהמערכת מדליקה ב-18. החזר את אותו היטל.
2. `views.py:223` — משתמש ב-`offset_for_date` (צהריים, `:72-77`) במקום ב-
   `offset_for_local` שה-Planner משתמש בו (`planner.py:131`). בשני ימי מעבר השעון
   התצוגה שגויה בשעה, ובאביב מוצגת שעה שלא קיימת. הוסף טסט לשני התאריכים.

**אימות:** שלוש הפקודות.

---

## משימה 17 — שני תיקוני P3 בליבה

**קבצים בהיקף:** `src/smart_kosher/adapters/zigbee_gateway.py`

1. `:763-766` — `_toggle` עושה `bool(read.get("reply", {}).get("on_off"))`; שדה
   חסר → `False` → תמיד "on". טפל בשדה חסר כמו בקריאה שנכשלה (השורה שמעל).
2. `:240` — `payload.get("status", "ok") == "ok"` קורא שדה חסר כהצלחה. זו בדיוק
   "arrival as success" שההערה ב-`:236-238` אומרת שתוקנה. שדה חסר ≠ הצלחה.

**אימות:** שלוש הפקודות.

---

# בלוק ג׳ — קושחת הרכזת (`firmware/h2_coordinator`)

> **סדר קריטי.** משימה 18 חייבת לקדום את 20, שמוסיפה מילה חדשה לאוצר המילים.

## משימה 18 — טסט הצמדה לאוצר המילים של הפרוטוקול

**קבצים בהיקף:** `tests/test_protocol_vocab_is_in_sync.py` (חדש),
`docs/UART_PROTOCOL.md`

**הרקע.** `CLAUDE.md`: מושג שחוצה גבול בלי import מקבל מקור אחד; כשזה בלתי אפשרי
(שפות שונות) — טסט הצמדה. C ↔ Markdown ↔ פייתון הם המקרה הזה. תקדימים:
`tests/test_zman_keys_are_in_sync.py`, `tests/test_boot_sentinel_is_in_sync.py`.

**מה לעשות.** טסט שעושה פרסינג טקסטואלי של `zb.c` ו-`link.c`, מוציא כל מחרוזת
ב-`send_error(...)` וכל `reason` ב-`report_reporting_outcome`, ומשווה מול
`docs/UART_PROTOCOL.md:92-94` (קודי שגיאה) ו-`:113` (reasons).

**הטסט ייכשל מיד** ויתפוס את `missing_ieee` (`zb.c:772`), שאינו ברשימה. **התיעוד
שגוי, לא הקוד:** `missing_ieee` (שדה חסר) עקבי עם `missing_state` שכבר מתועד,
ונבדל מ-`bad_ieee` (שדה פגום, `zb.c:775`). **אל תמזג אותם.** הוסף אותו לרשימה.

**אימות:** שלוש הפקודות. הטסט החדש נכשל לפני התיקון בתיעוד ועובר אחריו.

---

## משימה 19 — endpoint בהתאמת תגובות בקושחה

**חומרה: P1.** **בצע test-first.**

**קבצים בהיקף:** `firmware/h2_coordinator/main/txn.h`, `txn.c`, `zb.c`,
`firmware/h2_coordinator/host_test/test_main.c`

**הרקע.** `txn_match()` מקבל kind, short_addr, tsn — **אין פרמטר endpoint**
(`txn.h:102`, `txn.c:84`). הגוף מסנן על kind ו-short_addr בלבד; הנפילה היא
ל-`deadline_ms` המוקדם ביותר (`txn.c:99-102`). שני קוראים מעבירים גם
`tsn_valid = false` ולכן נופלים תמיד: `zb.c:540` ו-`zb.c:738`.

**המידע קיים בקובץ:** `on_report_attr` עושה `ep = rpt->in.header->src_ep`
(`zb.c:1018`).

**מה לעשות.**

1. **טסטים נכשלים קודם** ב-`host_test/test_main.c`: שתי `CONFIG_REPORT` פתוחות
   לאותה `short_addr` ב-endpoints 1 ו-2 → כל תגובה מותאמת נכון. אותו דבר
   ל-`READ_REPORT_CFG`. ורגרסיה: בלי endpoint ידוע, ההתאמה כמו היום.
2. חתימה, בדפוס הקיים של `tsn, tsn_valid`:

```c
txn_handle_t txn_match(txn_table_t *table, txn_kind_t kind,
                       uint16_t short_addr, uint8_t tsn, bool tsn_valid,
                       uint8_t endpoint, bool endpoint_valid);
```

3. **כלל ההתאמה — החלק הרגיש.** ה-endpoint **מצמצם רק את מסלול הנפילה ולעולם
   לא גובר על TSN**. סדר: TSN אם יש → אחרת oldest מסונן ב-endpoint → אחרת oldest
   כמו היום. הפיכת ההתאמה לקפדנית מסוכנת בכיוון ההפוך: מכשיר שעונה מ-endpoint
   לא צפוי יאבד התאמה ויקבל פקיעה במקום תשובה.
4. שלושת הקוראים (`zb.c:540,738,984`) קוראים endpoint מהכותרת כמו `:1018`.
5. `on_config_report_rsp` ידווח endpoint **מהתגובה**, לא מהטרנזקציה (`:542,550`).

**אימות:** ארבע הפקודות, כולל `host_test/run.sh`. ואז [חומרה].

---

## משימה 20 — פקיעת `bind` תדווח, ו-verdict לא יומצא

**חומרה: P1. תלויה במשימה 18.**

**קבצים בהיקף:** `firmware/h2_coordinator/main/zb.c`, `docs/UART_PROTOCOL.md`

**הרקע — שני חלקים.**

**(א)** `cmd_enable_reporting` מקצה `TXN_KIND_BIND` עם `rid = NULL` (`zb.c:663`).
`expired_txn_cb` מטפל מפורשות רק ב-`TXN_KIND_CONFIG_REPORT` ויוצא ב-
`if (!txn->has_rid) return;` (`:307`). הקוד מזיין דדליין של 8 שניות ל-bind ואין
לו מטפל. `UART_PROTOCOL.md:80` מבטיח *"outcome follows as an event"*.

**(ב)** `on_config_report_rsp` פולט verdict גם כש-`txn_match` לא מצא כלום —
עם `endpoint = 1` ו-`cluster = OnOff` כניחושים (`:542,546,550`). שתי האחיות
נזהרות: `:746` ו-`:1000-1006`.

**מה לעשות.**

1. ענף ב-`expired_txn_cb` (`:300`):

```c
if (txn->kind == TXN_KIND_BIND) {
    report_reporting_outcome(txn->short_addr, txn->endpoint, txn->cluster,
                             false, "bind_no_response", -1);
    return;
}
```

2. הוסף `bind_no_response` לרשימת ה-reasons ב-`UART_PROTOCOL.md:113`.
   **טסט משימה 18 אוכף.** צד ה-hub בטוח: `_on_reporting_result` שומר את ה-reason
   כמחרוזת אטומית (`zigbee_gateway.py:351-356`) — אין שינוי נדרש בפייתון.
3. `if (txn == NULL) { TXN_UNLOCK(); return; }` ב-`:541`. שים לב: בדיקת
   `txn == NULL` ולא `has_rid` — טרנזקציות `CONFIG_REPORT` מוקצות תמיד בלי rid
   (`:578`).

**אימות:** ארבע הפקודות. ואז [חומרה].

---

## משימה 21 — `remove_device` יבדוק את התוצאה

**חומרה: P2.**

**קבצים בהיקף:** `firmware/h2_coordinator/main/zb.c` (רק `cmd_remove_device`)

**הרקע.** `:781-788` — `ezb_zdo_nwk_mgmt_leave_req(&leave)`, ערך ההחזרה נזרק,
שום callback לא נרשם, לא מוקצית טרנזקציה, ואז `send_ack(..., "ok", ...)` ללא
תנאי. זהו הדפוס שההערה ב-`:421` מתארת כבאג ההיסטורי.

**מה לעשות. קודם בדוק את הכותרת** של `esp-zigbee-lib 2.0.3`: האם ל-
`ezb_zdo_nwk_mgmt_leave_req_t` יש שדה `cb` כמו ל-`ezb_zdo_bind_req_t`, והאם
הפונקציה מחזירה `ezb_err_t`.

- **יש callback:** הקצה טרנזקציה, החזר `accepted` מיד, שדרג ל-`delivered`/`failed`
  מה-callback — כמו `cmd_on_off`.
- **אין:** לפחות בדוק ערך החזרה ושלח `send_failed` בכישלון.

**אם הכותרת לא זמינה — אל תנחש. דווח ועבור הלאה.**

**אימות:** ארבע הפקודות.

---

## משימה 22 — גלישת דור בטבלת הטרנזקציות

**חומרה: P3.**

**קבצים בהיקף:** `firmware/h2_coordinator/main/txn.c`,
`firmware/h2_coordinator/host_test/test_main.c`

**הרקע.** `make_handle` אורז `generation << 8` ל-uint32 (`:21`), אבל `txn_get`
משווה מול הדור המלא (`:74`). מדור `0x01000000` והלאה `txn_get` מחזיר `NULL` תמיד.

**מה לעשות.** טסט: `table.next_generation = 0xFFFFFE`, הקצה שלוש, ודא שכולן
ניתנות לאחזור. תיקון שורה אחת ב-`:49`:

```c
slot->generation = (table->next_generation++) & 0xFFFFFFu;
```

**אימות:** ארבע הפקודות.

---

# בלוק ד׳ — hub, web, tools

## משימה 23 — פריסה ראשונה ל-hub, ופער הטרנספורטים

**קבצים בהיקף:** `products/hub/host/deploy.ps1`,
`src/smart_kosher/web/routes/__init__.py`, `tests/test_route_table.py`,
`tools/dev_server.py`, `tools/zmanim_golden/GenerateGolden.java`

**(א) `deploy.ps1:72` — P1.** אין `mkdir :/lib` לפני ה-`cp -r`. mpremote מעתיק
**אל** היעד רק אם הוא קיים; אחרת הוא משתמש בו כיעד. לוח טרי → `/lib/application/…`
במקום `/lib/smart_kosher/application/…` → `ImportError` בבוט → לולאת ריסט של
5 שניות, **בלי ערוץ USB להתאושש דרכו, כי הערוץ הוא מה שנכשל בייבוא**.

התיקון קיים כבר בריפו: `products/panel/host/deploy.ps1` עושה
`try { Mpr mkdir :/lib } catch {}` לפני ה-`cp -r` הזהה, עם הערה. **העתק אותו.**

**(ב) `deploy.ps1:69,72,82,87,90` — P2.** אף קריאה ל-mpremote לא בודקת
`$LASTEXITCODE`. `$ErrorActionPreference = "Stop"` לא חל על exe-ים ב-PowerShell 5.1,
שזה מה שהכותרת מורה להריץ. אותו קובץ **כן** בודק אחרי mpy-cross (`:54`).
בדוק אחרי כל קריאה.

**(ג) פער הטרנספורטים — P2.** `web/route_table.py` נוצר כדי למנוע "עובד ב-WiFi,
404 ב-USB". הפער קיים, **הפוך**:

```
GET /api/status/          HTTP: 404      USB: status.get
PUT /api/settings (ריק)   HTTP: 400      USB: ok=true, no-op שקט
```

`resolve()` (`route_table.py:177`) סובלני לסלאשים; `routes/__init__.py:36` רושם
את התבנית מילולית ב-Microdot. ו-`route_table.py:92-109` משתמש ב-`body or {}`
בזמן ש-`routes/__init__.py:39-42` אוכף גוף.

**החלט מה ההתנהגות הנכונה, החל אותה על שני הצדדים, ותקן את `test_route_table.py`
שישווה התנהגות ולא רק מחרוזות תבנית.** זו הסיבה שהטסט לא תפס.

**(ד) P3.** `tools/dev_server.py:7-8` אומר "memory only" בזמן ש-`:38` הוא
`STORAGE = "json"`. `:87` מאזין ל-`0.0.0.0` בזמן שהוא מתועד כ-localhost (השווה
ל-`apps/desktop/server.py`, שקושר ל-`127.0.0.1`). `GenerateGolden.java:2` מפנה
ל-`tests/test_zmanim.py` במקום ל-`tests/test_zmanim_reference.py`.

**אימות:** שלוש הפקודות.

**חלק לארבעה קומיטים** — (א), (ב), (ג), (ד).

---

## משימה 24 — `ack_unjournaled` יקבל קריאת אישור בשליטה ידנית

**חומרה: P2.**

**קבצים בהיקף:** `src/smart_kosher/application/control_service.py`,
`tests/test_executor_status_vocabulary.py` (או קובץ טסט חדש)

**הרקע.** נמצא תוך כדי משימה 10 ולא תוקן שם — הוא היה מחוץ להיקפה.

`control_service.py` פותח את שער האישור על `EXECUTED` בלבד:

```python
if (confirm_ms and target_type == "endpoint"
        and action_type in ("on", "off")
        and outcome.get("status") == EXECUTED):
```

שליחה ידנית שמסתיימת ב-`ACK_UNJOURNALED` **לא מקבלת קריאת אישור**, אף
ש-`ack_unjournaled` פירושו שה-ACK חזר והמכשיר פעל — רק הכתיבה ליומן נכשלה.
המשתמש לוחץ על מתג ב-UI, המכשיר באמת נדלק, והתוצאה חוזרת בלי `confirmation`.

**זה אותו באג של משימה 10, שכבה אחת מעל.** שני מקומות התייחסו
ל-`ack_unjournaled` כאילו כלום לא קרה: המתזמן שלח שוב, וכאן לא נבדק כלל. משימה
10 תיקנה את הראשון. אוצר המילים המשותף כבר קיים, אז התיקון הוא תנאי אחד.

**מה לעשות.** הכרע במפורש אם `ACK_UNJOURNALED` נכנס לשער. **שים לב שזו לא
החלטה מקבילה לזו של משימה 10** — שם השאלה הייתה "האם לשלוח שוב" והתשובה נשענה
על כך שהמכשיר פעל; כאן השאלה היא "האם לקרוא את מצב המכשיר", ומכשיר שפעל הוא
בדיוק זה שכדאי לקרוא ממנו. אם ההכרעה חיובית — הוסף טסט שנופל על הקוד הנוכחי.

**אימות:** שלוש הפקודות.

---

## משימה 25 — האישור יבקש את ה-endpoint שפקדנו

**חומרה: P1.** משימה 12 תיקנה את הפרימיטיב; זו מחווטת אותו. **עד שהיא תיסגר,
התסמין של 12 חי בייצור.**

**קבצים בהיקף:** `src/smart_kosher/application/control_service.py`,
`src/smart_kosher/adapters/zigbee_gateway.py` (חשיפת ה-endpoint בלבד),
`tests/test_zigbee_gateway.py`

**הרקע.** `wait_for_report` מקבל `endpoint=None` מאז משימה 12, ואז
`_endpoint_admits` מחזיר `True` תמיד — כלומר בדיוק ההתנהגות הישנה.
`control_service.py:49` קורא `waiter(ieee, action_type == "on", confirm_ms)`,
פוזיציונלי ובלי endpoint, והוא **הקורא היחיד בייצור**.

**האינווריאנט — הוכרע, אל תפתח אותו מחדש:**

> **מאשרים על ה-endpoint שפקדנו, לא על זה שהרישום מכיר.**

ההכרעה כבר קיימת בקוד, בשורה אחת:

```python
zigbee_gateway.py:920
zcl_ep = entity.get("zigbee_endpoint", entry.get("endpoint", 1))
```

הישות מנצחת על מסלול הפקודה — `tests/test_zigbee_gateway.py:147-155` מקבע את
זה: המכשיר הצטרף עם endpoint 1, הישות אומרת 3, והפקודה יוצאת ל-**3**.

ומכאן שהמקרה שנראה מטריד — הפקודה יצאה ל-3 והמכשיר מדווח רק מ-1, ואישור לעולם
לא מגיע — **אינו חיובי-כוזב הפוך אלא שלילי נכון.** אם פקדנו על 3 ואיש לא ענה
מ-3, הפקודה באמת לא הגיעה לשום מקום, ו"לא אושר" היא התשובה הכנה. החלופה — ליפול
בחזרה ל-1 של הרישום — הייתה מאשרת על סמך דיווח מ-endpoint שמעולם לא פקדנו, וזה
בדיוק החיובי-הכוזב שמשימה 12 קיימת כדי להרוג.

**מה לעשות.**

1. שהגייטוויי **יחזיר או יחשוף את ה-endpoint שבו השתמש בפועל**. `ieee_of()`
   (`:923`) הוא הדפוס הקיים לחשיפה כזאת, ו-`_resolve_endpoint` (`:907`) הוא
   המקום שכבר יודע את התשובה.
2. `control_service` יעביר אותו הלאה ל-`wait_for_report`.
3. טסט: הזרימה המלאה דרך `ControlService.send(confirm_ms=...)` — דיווח מגאנג 2
   **לא** מאשר פקודה שיצאה לגאנג 1.

**אזהרה — אל תשכפל את `:920`.** `control_service` מחזיק את ה-`entity` אבל
**לא** את רשומת הרישום, ולכן אינו יכול לשחזר את שורת הרזולוציה בעצמו. כתיבתה
מחדש שם יוצרת עותק שני שיסטה מהמקור — בדיוק המחלקה ש-CLAUDE.md מקדיש לה סעיף
("כשמושג חוצה גבול"). הגייטוויי הוא זה שפתר, והוא זה שיענה.

**אימות:** שלוש הפקודות.

---

# נספח א׳ — מה נבדק ונמצא תקין

**אל תשנה את אלה.** נבדקו בסקירה ועומדים:

- **שכבת המסגור בקושחה** (`protocol.c`, `txn.c`) — עוברת `-Wall -Wextra -Wconversion
  -Wsign-conversion -Wshadow -Wcast-qual` בלי אזהרה, ו-1,234 בדיקות תחת ASan+UBSan.
- **גבולות החלון** — `(start_exclusive, end_inclusive]` מדויק, ללא חפיפה וללא פער.
- **שעון קיץ** — 02:00–02:59 באביב נדחה ומדווח; השעה הכפולה בסתיו → הופעה ראשונה;
  `source_date` שורד היסט חוצה-חצות; 29 בפברואר ב-2028 ולא ב-2027.
- **`event_id` דטרמיניסטי**, אין "נראה לאחרונה", catch-up חסום, boot ו-tick הם
  אותו מסלול, שעון לא מכוון = לא יורים כלום.
- **סולם המסירה** — `accepted_by_h2` לעולם לא ביומן; `_STATUS_RANK` נכון; המקום
  היחיד שכותב ל-`_states` הוא `_on_state`.
- **המתמטיקה** — הזמנים אומתו על 58,440 ימי-עיר מול KosherJava (סטייה < שנייה),
  והלוח העברי אומת על 73,414 ימים מול `pyluach` עם **אפס** אי-התאמות.
- **ניידות MicroPython** — אפס הפרות בכל הריפו.
- **כללי הרינדור** — אפס `gc.collect()`, אפס אנימציית מסך-מלא, `toggle` לא זמין
  בתזמון.
- **`jscpd` על ה-JS** — אפס שכפולים.
- **עמידות `JsonRepository` ו-`SettingsStore`** — temp→backup→replace עם rollback.

# נספח ב׳ — עבודה שלא נכללה כאן

**אל תתחיל אותן.** דורשות החלטה מוצרית:

- **הפער הידוע במולטי-גאנג** — `_states` ממופתח לפי ieee בלבד. משימה 19 **פותחת**
  אותו, אבל התיקון עצמו הוא עבודה נפרדת בצד ה-hub.
- **`reconcile`** — הכלל הוכרע, שום דבר לא מממש, דורש per-command attribution.
- **מוצר ב׳ לא יורה תזמונים** — חסרה משימה אחת בלולאה שלו, וחומרה לאמת עליה.
- **`tset_hakohavim` ו-`tset_hakohavim_shabbat` מחשבים אותו רגע** — מכוון.

# נספח ג׳ — הצעה להמשך

אחרי כל 23: **טסטי ההצמדה החסרים** הם מה שמונע את הישנות כל המחלקה. המועמדים —
`RECURRENCE_TYPES` (משימה 5 עושה אחד), אוצר המילים של הפרוטוקול (משימה 18),
התנהגות טבלת הניתוב (משימה 23ג), ו-`pyluach` כמקור אימות שני ללוח העברי בדפוס
`test_zmanim_reference.py`.

**החוט המשותף בכל 23 הממצאים:** הקוד יודע לעשות נכון, ועושה נכון במקום אחד, ולא
במקום השני. מה שחסר אינו ידע אלא אכיפה — כלל שחי בהערה במקום בטסט, המופע הבא
מפספס אותו.
