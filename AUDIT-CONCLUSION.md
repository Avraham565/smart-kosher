# ביקורת ארכיטקטונית — מסקנות

תאריך: 2026-08-12 · ענף: `feat/scheduler-engine-and-h2-delivery-proof` · HEAD: `900173a`
היקף: 187 קבצים מנוהלים + 2 לא-מנוהלים, ~25,900 שורות, 6 שפות.
שיטה: פנקס כיסוי מכני → תצפית → אינדקס לפי מושג → שיפוט.

> **סטטוס: כל הממצאים תוקנו** (2026-08-12, אחרי האודיט). ראו
> [סעיף הביצוע](#מה-בוצע-בפועל) בסוף. הגוף שלמטה נשאר כפי שנכתב באודיט —
> הוא הנימוק לתיקונים, לא תיאור המצב הנוכחי.

---

## ציון בריאות: **8 / 10**

**זה לא ריפו מוזנח. זה ריפו שהתחזק היטב סביב ציר אחד ולא הכליל את השיטה.**

מה שמצדיק את הציון הגבוה — כל אחד מהם נמדד, לא הוערך:

| מדד | תוצאה |
|---|---|
| תלויות מעגליות | **אפס** (גרף הייבוא של `src/smart_kosher` נבנה ידנית במלואו) |
| הפרות שכבה | **אפס** — אין `domain→adapters`, אין `domain→application`, אין `adapters→application`; `ports/` עלים מוחלטים |
| lint | `ruff check .` → All checks passed |
| טסטים | 355 טסטים + 1,369 subtests, כולם עוברים ב-4.19 שניות |
| קוד מוער | אפס (ERA001 החזיר תוצאה חיובית-שגויה אחת) |
| השערות התנהגות שנבדקו | 8 מתוך 8 אומתו נכונות; אחת דרשה חידוד ניסוח |

ומה שגורע: **תשעה מושגים חוצי-יחידות, ולאחד בלבד יש הצמדה.**

`tests/test_zman_keys_are_in_sync.py` הוא ההוכחה שהשיטה מוכרת כאן — הוא מפנקס
18 מפתחות זמנים על פני חמישה משטחים, כולל פרסינג טקסטואלי של JavaScript ושל
קובץ MicroPython, ובודק גם שמפתחות שהוצאו משימוש נעלמו מכולם. הוא נכתב כי
"retiring `tset_hakohavim_tsom` meant editing seven files".

אותה בעיה בדיוק קיימת בשמונה צירים נוספים — רשימת הישויות, טבלת הניתוב
REST↔op, אוצר הפעולות, סוגי היעד, מיפוי השגיאות, סף "השעון לא נקבע", חוזה
הכתיבה העמידה, וכלי הפיתוח — ולאף אחד מהם אין את הטסט המקביל.

**הסיבה המבנית:** אין `CLAUDE.md` בריפו. הכללים קיימים — בהערות-נימוק מצוינות
בקוד, ב-`docs/`, ובזיכרון הסוכן — אבל אף אחד מהמקומות האלה אינו רשימת כללים
שאפשר לקרוא לפני שכותבים. לכן כל סשן מגלה מחדש. הקובץ נוצר עכשיו (ראו למטה).

---

## ממצאים לפי עדיפות

### P0 — לפני הקומיט הבא

#### F-01 · `panel_mp/uart_tap.py` אינו מנוהל ב-git, ושני קבצים מנוהלים תלויים בו
`git status` מראה `?? panel_mp/uart_tap.py` לצד ` M panel_mp/main.py` ו-` M panel_mp/deploy.ps1`.
- [main.py:31](panel_mp/main.py#L31) — `import uart_tap`, **ללא תנאי**, בראש המודול
- [main.py:199](panel_mp/main.py#L199) — `uart_tap.maybe_install(gateway, …)`
- [deploy.ps1:44-46](panel_mp/deploy.ps1#L44-L46) — מוסיף אותו לרשימת המודולים, עם הערה
  שכתובה שם במפורש: *"uart_tap.py is imported unconditionally by main.py … so
  leaving it out of this list bricks the boot."*

HEAD תקין, עץ העבודה תקין תפקודית. הסיכון הוא הקומיט: שני קבצים מנוהלים ייכנסו,
הקובץ שהם צריכים לא — ושיבוט נקי לא יעלה. הקובץ עצמו (70 שורות, מתועד היטב) בסדר גמור.

**תיקון:** `git add panel_mp/uart_tap.py`. עלות: אפס.

---

### P1 — סחף פעיל עם מסלול כשל שקט

#### F-02 · טבלת הניתוב REST↔op משוכפלת בין שני תהליכים, בלי הצמדה
[web/routes/__init__.py:45-142](src/smart_kosher/web/routes/__init__.py#L45-L142) מול
[client/bridge.py:60-165](client/bridge.py#L60-L165).
ה-docstring מודה בכך ([bridge.py:63-65](client/bridge.py#L63-L65)): *"Mirrors the hub's
own HTTP adapter (web/routes/__init__.py)"*.

```
$ grep -rn "rest_to_op\|_KIND_TO_STATUS\|_HTTP_STATUS" tests/
(אין תוצאות)
```

**מסלול הכשל:** נתיב חדש שנוסף ל-`routes/` יעבוד ב-WiFi ויחזיר 404 ב-USB
([bridge.py:193-194](client/bridge.py#L193-L194)) — בלי שגיאה בשום צד, בערוץ אחד בלבד.
בנוסף `_KIND_TO_STATUS` ([bridge.py:29-36](client/bridge.py#L29-L36)) משכפל את
`_HTTP_STATUS` ([routes/__init__.py:18-24](src/smart_kosher/web/routes/__init__.py#L18-L24)) —
אותם חמישה זוגות.

**תיקון מוצע:** טסט הצמדה בדיוק בנוסח `test_zman_keys_are_in_sync.py` — לאסוף את
נתיבי ה-routes ואת מה ש-`rest_to_op` יודע לתרגם, ולדרוש כיסוי הדדי.

#### F-05 · שכבת עצמי-הערך בדומיין — **אושר למחיקה**
| מחלקה | צרכני ייצור | צרכני טסט |
|---|---|---|
| `Event` | ✅ [planner.py:146](src/smart_kosher/application/planner.py#L146) | ✅ |
| `Schedule` `Zone` `Endpoint` `Group` | **אפס** | `test_domain.py:43-45,63` בלבד |
| `Action` | **אפס** | **אפס** |

נבדק מול השאלה "האם זה שמור ל-HTTP?" — לא. שכבת ה-HTTP כבר בנויה ומכוסה
(1,041 שורות ב-`test_routes.py`), והמסלול שלה כולו dict-based:
`routes → api.dispatch → crud_service.create (dict(data)) → repo.upsert →
validate_entity → validate_zone()`. הוולידציה קורית דרך הפונקציות; המחלקות אינן
נוגעות במסלול.

**החלטה: למחוק** את `Action`, `Schedule`, `Zone`, `Endpoint`, `Group` ואת `_DeviceModel`;
להשאיר את `Event`. לעדכן `domain/__init__.py` ו-`tests/test_domain.py`.

#### F-03 + F-08 · רשימת הישויות בחמישה מקומות, אחד מהם מת
`("zones","endpoints","groups","schedules")` מופיע ב:
[entities.py:8](src/smart_kosher/domain/entities.py#L8) · [crud_service.py:6](src/smart_kosher/application/crud_service.py#L6) · [api.py:22](src/smart_kosher/application/api.py#L22) · [routes/__init__.py:73](src/smart_kosher/web/routes/__init__.py#L73) (ליטרל בלי שם) · [client/bridge.py:37](client/bridge.py#L37)

ארבעה מהם באותו תהליך. `crud_service.ENTITY_TYPES` הוא **קוד מת מאומת** — grep על
כל הריפו מחזיר מופע יחיד, ההגדרה עצמה.

**תיקון:** `domain/entities.py:8 CONFIG_ENTITY_TYPES` הוא הבעלים (הוא כבר בונה את
`ALL_ENTITY_TYPES`). למחוק את `crud_service.ENTITY_TYPES`, ולייבא ב-`api.py`
וב-`routes/__init__.py`. `client/bridge.py:37` נשאר — תהליך אחר, בלי גישה לחבילה.

**קוד מת נוסף (אפס צרכנים, מאומת ב-grep):**
[web/responses.py:12-13](src/smart_kosher/web/responses.py#L12-L13) `not_found()`
(ההתאמות ב-`tests/` הן שמות מתודות, לא קריאות).

---

### P2 — כפילות מדודה, בלי מסלול כשל מיידי

#### F-04 · 38 שורות זהות-בבתים בין שני מתאמי אחסון
```
$ diff <(sed -n '30,67p' src/smart_kosher/adapters/json_repository.py) \
       <(sed -n '17,54p' src/smart_kosher/adapters/settings_store.py)
(אפס הבדלים)
```
`_exists`, `_replace`, `_flush_file`, `_sync_filesystem`.
[settings_store.py:3-6](src/smart_kosher/adapters/settings_store.py#L3-L6) **מצהיר**
שזה "the same durability contract as the JSON repository" — החוזה משותף ומודע,
המימוש הועתק. גם לוגיקת ה-tmp/bak חוזרת.
**סיכון:** תיקון עמידות באחד (טיפול ב-`ENOSPC`, למשל) לא יגיע לשני.
**תיקון מוצע:** `adapters/_atomic_io.py` פרטי, שני המתאמים מייבאים.

#### F-06 · המספר `2013` בשש נקודות, בשתי משמעויות שאינן קשורות
**משמעות א׳ — חוק שעון הקיץ (נכון ומתועד):** [israel_time.py:20-21](src/smart_kosher/zmanim/israel_time.py#L20-L21), [views.py:61-65](src/smart_kosher/application/views.py#L61-L65)
**משמעות ב׳ — סנטינל "ה-RTC מעולם לא נקבע":** [scheduler.py:56](src/smart_kosher/application/scheduler.py#L56) (`MIN_VALID_YEAR` — היחיד שיש לו שם) · [api.py:399](src/smart_kosher/application/api.py#L399) · [device_time.py:13](src/smart_kosher/application/device_time.py#L13) · [pcf8563.py:83](src/smart_kosher/adapters/pcf8563.py#L83) · [panel_mp/main.py:97](panel_mp/main.py#L97) · [panel_mp/settime.py:36](panel_mp/settime.py#L36)

[scheduler.py:54-55](src/smart_kosher/application/scheduler.py#L54-L55) מודע ומתעד
את השכפול, אך `MIN_VALID_YEAR` אינו נצרך באף אחד מהחמישה.
**הסיכון הייחודי:** שני מושגים חולקים ערך במקרה — עריכה טקסטואלית של האחד תזלוג לשני.

#### F-07 · `_VALID_ACTIONS` משכפל את `ACTION_TYPES`
[control_service.py:15](src/smart_kosher/application/control_service.py#L15) מול
[actions.py:5](src/smart_kosher/domain/actions.py#L5). באותו קובץ,
`_TARGET_TO_COLLECTION` ([control_service.py:10-13](src/smart_kosher/application/control_service.py#L10-L13))
מגדיר עצמאית גם את `TARGET_TYPES`. שירות שכותב מחדש אוצר-מילים של הדומיין במקום לצרוך אותו.

---

### P3 — ניקיון

- **F-09 · יישור סגנון (אושר):** [uart_codec.py](src/smart_kosher/adapters/uart_codec.py)
  הוא הקובץ היחיד ב-`src/` (מתוך ~4,900 שורות) עם f-strings (`:23,36,40`) ועם type
  annotations (`:9,26`). להמיר ל-`.format()` ולהסיר את ה-annotations.
- **F-10 · שאריות תיעוד:** [test_uart_codec.py:1](tests/test_uart_codec.py#L1) מזכיר
  `UartProtocolCodec` — סמל שאינו קיים בשום מקום בריפו.
  [device_gateway.py:3-5](src/smart_kosher/ports/device_gateway.py#L3-L5) מתאר את
  מיפוי ה-ACK כמשימה עתידית, בעוד `_ack_status` כבר מממש אותו והקושחה כבר לא
  מחזירה `"ok"` (לפי `UART_PROTOCOL.md`, `ok` הוא legacy מקושחה < 0.8.0).
- **F-11 · כפילות בכלי הפיתוח:** `find_panel()` זהה-בבתים ב-`run_hwtest.py:28-33`,
  `run_hwtest_ui.py:27-32`, `run_hwtest_zmanim.py:34-39`; `mpremote()` ו-`CH340_VID_PID`
  דומים. `panel_mp/dev_common.py` כבר קיים כמודול המשותף של התיקייה.
- **S-03 · `pyrightconfig.json`** מצהיר `"pythonVersion": "3.14"` בעוד
  `pyproject.toml:11` קובע `>=3.8` ו-`:32` קובע `target-version = "py38"`, והליבה
  חייבת לרוץ על MicroPython. pyright גם אינו מותקן, כך שהקובץ אינו נאכף היום.
  **לא אושר לשינוי — נשאר כהמלצה פתוחה.**

---

### S-02 · מעטפות תגובה שונות בשני ערוצים (לא סווג כפגם)
HTTP מחזיר `{"ok":false,"error":…}` וזורק את `kind` (הוא מקודד בקוד הסטטוס);
serial מחזיר `{"ok":false,"kind":…,"error":…}`. `client/bridge.py:29-36` ממיר בחזרה.
**זה מגן על עצמו** — בלקוח HTTP קוד הסטטוס *הוא* הסיווג — אבל זו הסיבה
ש-`_KIND_TO_STATUS` קיים, כלומר חצי מ-F-02. מתועד כהחלטה, לא כממצא.

---

## תוכנית תיקון

| # | פעולה | קבצים | עלות |
|---|---|---|---|
| 1 | `git add panel_mp/uart_tap.py` | 1 | דקה |
| 2 | מחיקת `Action`/`Schedule`/`Zone`/`Endpoint`/`Group`/`_DeviceModel` | `domain/actions.py`, `domain/devices.py`, `domain/schedules.py`, `domain/__init__.py`, `tests/test_domain.py` | ~שעה |
| 3 | איחוד רשימת הישויות ל-`CONFIG_ENTITY_TYPES` + מחיקת `ENTITY_TYPES` ו-`not_found()` | `crud_service.py`, `api.py`, `routes/__init__.py`, `responses.py` | ~שעה |
| 4 | טסט הצמדה ל-`rest_to_op` ↔ `register_all` | `tests/test_client_bridge_sync.py` (חדש) | ~שעתיים |
| 5 | חילוץ `adapters/_atomic_io.py` | 3 קבצים | ~שעה |
| 6 | `MIN_VALID_YEAR` כמקור יחיד לסנטינל השעון | 5 קבצים | ~שעה |
| 7 | `control_service` מייבא `ACTION_TYPES` ו-`TARGET_TYPES` מהדומיין | 1 | 15 דק׳ |
| 8 | יישור `uart_codec.py` ל-`.format()`, תיקון שתי שאריות התיעוד | 3 | 30 דק׳ |
| 9 | חילוץ `find_panel`/`mpremote` ל-`dev_common.py` | 4 | 30 דק׳ |

**כלים שכדאי להתקין** (אף אחד מהם לא היה זמין; הכול נעשה ידנית + ruff בכללים מורחבים):
`pip install vulture` היה תופס את פריט 3 לבדו; `npx jscpd` היה תופס את פריט 5 לבדו.
חסרים גם `pyright`/`mypy`, `pydeps`, `cppcheck`, ו**`gcc`** — שבלעדיו
`experiments/zigbee_probe/h2_coordinator_firmware/host_test/run.sh` לא ניתן להרצה כאן.

---

## חוקים שהוצע לשנות או להסיר — וההכרעה

### R-A · `extend-exclude = ["experiments"]` — **ההצעה נמשכה, היא הייתה שגויה**

הצגתי במקור טענה ש-"~1,900 שורות C מוחרגות מ-lint בגלל מיקומן". בדיקה הפריכה אותה:

- **ruff הוא לינטר Python בלבד** — קוד ה-C מעולם לא היה בתחולת ההחרגה.
- ה-Python שתחת `experiments/` היה 1,568 שורות, **וכולו באמת סקריפטי חקירה/ארכיון**.
  (אחרי מחיקת `_archive/crowpanel_ui/` ב-2026-08-12: 1,299 שורות, כולן `zigbee_probe/tools/`.)
- ביטול ההחרגה היה מניב **6 בעיות**: 5 מיון-imports + `E731` אחד.

`extend-exclude = ["experiments"]` **מכוון נכון ונשאר כפי שהוא.**

### R-B · הסתירה בתיאור `experiments/zigbee_probe/` — **הוכרע: לתקן את התיאור**

מה שכן נשאר מהממצא, בלי השלכת האכיפה:
- [README.md:3](experiments/zigbee_probe/README.md#L3) — "**Disposable** hardware proof-of-life code"
- [README.md:10-11](experiments/zigbee_probe/README.md#L10-L11) — "It is the **current source of truth** for hardware behavior"
- [hardware_audit.md:5-7](docs/hardware_audit.md#L5-L7) — קוד חומרה בדוק "should be promoted from `experiments/`"; התנאי התקיים (Gate 2+3), הקידום לא בוצע.

הסיכון הוא **גילוי**, לא איכות: מי שקורא את הריפו עלול לא להבין שזו הקושחה החיה
של מוצר נמכר, ושכל שינוי בפרוטוקול חייב לגעת בה.

**הוכרע:** לתקן את התיאור, לא להזיז קוד. לשנות את `README.md:3` כך שלא יקרא
"disposable", ולעדכן את `hardware_audit.md:5-7` כך ש-`zigbee_probe/` מוצהר כמיקום
הקבע של הקושחה ו-`_archive/` כארכיון. אפס שינויי נתיבים.

### R-C · האינווריאנט על `gc.collect()` — **נוסח מחדש כתלוי-חומרה**

הזיכרון ניסח זאת כאיסור גורף. הקוד מדויק יותר —
[brain.py:15-20](panel_mp/brain.py#L15-L20): *"The AtomS3 has no PSRAM and no RGB
scanout, so there that strategy is **correct**; here it is forbidden."*
ו-[web/server.py:37-45](src/smart_kosher/web/server.py#L37-L45) אכן מפעיל
`gc.collect()` — בכוונה, למוצר ב׳.

איסור גורף ב-`CLAUDE.md` היה מונע תיקון נכון על מוצר ב׳. **נכתב עם התנאי.**

### R-D · `pyrightconfig.json` 3.14 מול יעד 3.8 — **לא הוכרע, נשאר פתוח**
לא אושר לשינוי. מופיע כהמלצה ב-P3.

### R-E · אין `CLAUDE.md` — **הוכרע: ליצור, בהיקף מינימלי**
שלב 6ב במשימה הניח קובץ קיים; בפועל זו הייתה יצירה. נוצר `CLAUDE.md` בשורש,
מכיל **רק** אינווריאנטים שאומתו מול הקוד ואושרו — כל שורה בו מגובה בראיה מהאודיט.

---

## דו"ח פערים — מה לא נבדק לעומק, ולמה

הפנקס מנה **34 יחידות**, מתוכן 2 סווגו `n-a` מראש (פונטים בינאריים, דאטה-שיטים
של יצרנים). כל 32 הנותרות קיבלו סטטוס; אפס נשארו `unreviewed`.
מתוכן **19 נקראו לעומק** ו-**13 נסקרו חלקית**. הנה הפערים, בכנות:

| יחידה | מה נבדק | מה **לא** נבדק | למה |
|---|---|---|---|
| **E1–E3 · קושחת H2 (C, ~1,900 שורות)** | הכותרות, סולם ה-ACK, גרסאות, התאמה ל-`UART_PROTOCOL.md` | הלוגיקה הפנימית של `zb.c` (1,239 שורות), `txn.c`, `link.c`; טסטי `host_test` **לא הורצו** | **אין `gcc` בסביבה** ואין `cppcheck`. זה הפער המשמעותי ביותר. |
| **A5 · `zmanim/`** | מבנה, תלויות, קונבנציות, `CANDLE_OFFSET_MINUTES`, מורכבות | נכונות מתמטית של `hebrew_cal.py` (516 שורות) ו-`astronomy.py` | מכוסה מבחוץ: `test_zmanim_reference.py` מול טבלת אמת מ-KosherJava. אודיט ארכיטקטוני אינו הכלי לאמת חישוב אסטרונומי. |
| **B2–B4 · UI של הפאנל (~2,900 שורות)** | תבניות (`open`/`_build`/`_rebuild`), הגשר, שורש ההרכבה, `store`/`reactive` | הלוגיקה של כל עמוד בנפרד | LVGL, לא ניתן להרצה מחוץ ללוח. מכוסה ע"י `hwtest_ui.py` (26/26 על חומרה) שאינו חלק מ-pytest. |
| **C2–C4 · JS של הלקוח (~1,600 שורות)** | `labels.js` (בגלל ציר הזמנים), מבנה המודולים, `index.html` | לוגיקת התצוגה ב-`views/*.js`, `style.css` (657 שורות) | אין כלי JS מותקן (`jscpd`/`madge`), אין package.json, ואין שום כיסוי טסטים. |
| **E4 · כלי probe (~1,420 שורות)** | תפקיד, החרגת lint | התוכן | מוצהרים כסקריפטי חקירה — וזה אומת כנכון. |
| **F · טסטים** | מיפוי לכל יעד, הורצו במלואם | לא נבדקה **איכות** הטענות בכל טסט | 355 עוברים; ביקורת טסט-אחר-טסט היא משימה נפרדת. |
| **D1, G1** | ההרכבה, ה-imports, `SETTINGS_DEFAULTS` | `connect_wifi()`, `GenerateGolden.java` | היקף. |

**מה שהפערים האלה עלולים להסתיר:** באג לוגי בתוך `zb.c`, שגיאת חישוב זמנים שטבלת
האמת לא כיסתה, וכפילות בתוך `views/*.js`. שום ממצא שנרשם כאן אינו תלוי בהם —
כל ממצא מגובה בפלט כלי או ב-`file:line` שנקרא בפועל.

---

## מה שנבדק ונמצא תקין (ראוי לציון)

- **`SETTINGS_DEFAULTS`** — הסחף ההיסטורי ב-`candle_offset` (18 מול 20, שתי שעות
  כניסת שבת לאותו לוח זמנים) תוקן, **ומוחזק** בכל ארבעת שורשי ההרכבה.
- **סולם ה-ACK** — עקבי שורה-בשורה בין `ports/device_gateway.py`, `_ack_status`,
  `_STATUS_RANK`, ה-`Executor`, ו-`docs/UART_PROTOCOL.md`. המושג המתוחזק ביותר בריפו.
- **הפרדת `_states` מ-`_expected`** ב-`zigbee_gateway.py:107-115` — הבסיס לכלל
  "המוח מכבד התערבות ידנית", אכוף במבנה ולא רק בכוונה.
- **צפיפות התיעוד ב-`application/`** — הערות שמסבירות *למה*, כולל תיאור הבאג
  ההיסטורי שהכלל מונע. זה מה שאיפשר את רוב האודיט הזה.

---

## מה בוצע בפועל

בוצע ב-2026-08-12, אחרי אישור הממצאים. ההנחיה המנחה הייתה **מקור אחד ששני
הצדדים משתמשים בו**, ולא טסט שמצמיד שני עותקים — כלומר לתקן את המבנה, לא לשמור
על הכפילות ולהתריע כשהיא סוטה.

| # | ממצא | מה נעשה |
|---|---|---|
| F-01 | `uart_tap.py` לא מנוהל | `git add panel_mp/uart_tap.py` |
| F-02 | טבלת ניתוב משוכפלת | **`web/route_table.py` חדש** — 27 routes כנתונים. `web/routes/register_all` רושם ממנו; `client/bridge.rest_to_op` פותר מולו. `HTTP_STATUS` עבר לשם גם הוא, כך ש-`_KIND_TO_STATUS` בלקוח נעלם |
| F-03 | קוד מת | נמחקו `crud_service.ENTITY_TYPES` ו-`web/responses.not_found()` |
| F-04 | 38 שורות זהות | **`adapters/_atomic_io.py` חדש** — `exists`/`replace`/`flush_file`/`sync_filesystem`; שני המתאמים מייבאים |
| F-05 | מחלקות דומיין מתות | נמחקו `Action`, `Schedule`, `Zone`, `Endpoint`, `Group`, `_DeviceModel`. `Event` נשאר (נצרך ב-`planner.py:146`) |
| F-06 | 2013 בשש נקודות | **`ports/clock.py:MIN_VALID_YEAR`/`MAX_VALID_YEAR`** — נצרך ב-scheduler, api, device_time, pcf8563, panel_mp/main, panel_mp/settime. ה-2013 של חוק שעון הקיץ נשאר בנפרד, בכוונה |
| F-07 | `_VALID_ACTIONS` משוכפל | `control_service` מייבא `ACTION_TYPES` ו-`TARGET_COLLECTIONS` מהדומיין |
| F-08 | רשימת ישויות ×5 | `domain/entities.CONFIG_ENTITY_TYPES` הוא הבעלים; `api.py` ו-`route_table.py` מייבאים. הליטרל ב-routes ובלקוח נעלם |
| F-09 | סגנון `uart_codec` | הומר ל-`.format()`, ה-annotations הוסרו |
| F-10 | שאריות תיעוד | `UartProtocolCodec` תוקן; ההערה ב-`ports/device_gateway.py` מתארת את המצב בפועל |
| F-11 | `find_panel` ×3 | **`panel_mp/run_common.py` חדש** (host-side, לא נפרס). שלושת ה-runners מייבאים |
| S-03 | pyright 3.14 | **לא שונה** — לא אושר. נשאר פתוח |
| R-B | סתירת `experiments/` | `_archive/README.md` נכתב מחדש כרשומת שושלת; `experiments/_archive/crowpanel_ui/` נמחק |

**מפלי כפילות שנסגרו:** רשימת הישויות 5→1, טבלת הניתוב 2→1, מיפוי `kind`→סטטוס
2→1, עוזרי הכתיבה האטומית 2→1, סנטינל השעון 6→1, אוצר הפעולות 2→1,
`find_panel` 3→1.

**כיסוי חדש:** `tests/test_route_table.py` (15 טסטים, 81 subtests) מאמת את
התכונה עצמה — שכל route בטבלה נרשם ע"י הרכזת **וגם** נפתר ע"י הלקוח. זו בדיקה
חזקה יותר מהשוואת שני מימושים זה לזה, שהיא מה שטסט לפני הריפקטור היה נאלץ לעשות.
`client/` קיבל בכך כיסוי טסטים ראשון.

**אימות:** `ruff check .` נקי · **371 טסטים + 1,455 subtests עוברים**
(לפני: 355 + 1,369).

**שינוי אריזה שדורש תשומת לב:** הלקוח מייבא עכשיו את `smart_kosher`, ולכן
`client/build.ps1` קיבל `--paths src` ו-`client/app.py` מוסיף את `src` לנתיב
כשהוא לא frozen. **ה-exe לא נבנה מחדש ולא נבדק כאן** — זה הפער היחיד שנשאר.
