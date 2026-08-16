# תוכנית תיקון — קושחת הרכזת (`firmware/h2_coordinator`)

מקור: סקירה לעומק, 2026-08-15. HEAD: `eda4233`.
היקף: 1,976 שורות C. שיטה: קריאה מלאה + בנייה תחת `-Wconversion -Wsign-conversion
-Wshadow -Wcast-qual` + `host_test` תחת ASan/UBSan + אימות יריב לכל ממצא.

> **סטטוס: אף ממצא לא תוקן.** המסמך הוא תוכנית עבודה, לא תיאור מצב.

---

## רקע: למה כל הממצאים ב-`zb.c`

`host_test/run.sh` מקמפל את `test_main.c`, `protocol.c` ו-`txn.c` — **ולא את `zb.c`**.
`protocol.c` ו-`txn.c` עוברים `-Wconversion` בלי אזהרה אחת ו-1,234 בדיקות תחת
סניטייזרים בלי פגם. `zb.c` הוא הקובץ היחיד בלי רשת ביטחון, ושם יושבים כל ששת
הממצאים. זו סיבה ותוצאה, לא צירוף מקרים.

רוב הממצאים הם **חוסר עקביות ולא בורות**: הקוד יודע לעשות נכון ועושה נכון
במקומות אחרים באותו קובץ.

---

## הממצאים

| # | ממצא | חומרה | file:line |
|---|---|---|---|
| F-1 | פקיעת `TXN_KIND_BIND` לא מייצרת שום פלט | P1 | `zb.c:300-307`, `zb.c:663` |
| F-2 | התאמת תגובות מתעלמת מה-endpoint | P1 | `txn.h:102`, `zb.c:540,738` |
| F-3 | `on_config_report_rsp` ממציא endpoint כשאין התאמה | P2 | `zb.c:541-550` |
| F-4 | `remove_device` מאשר `ok` בלי לבדוק כלום | P2 | `zb.c:781-788` |
| F-5 | `missing_ieee` לא ברשימת קודי השגיאה | P3 | `zb.c:772` מול `UART_PROTOCOL.md:92-94` |
| F-6 | גלישת דור בטבלת הטרנזקציות (סמוי) | P3 | `txn.c:21,49,74` |

### F-1 · פקיעת `bind` שקטה

`cmd_enable_reporting` מקצה `TXN_KIND_BIND` עם `rid = NULL` (`zb.c:663`), ולכן
`has_rid` שקר. `expired_txn_cb` מטפל מפורשות רק ב-`TXN_KIND_CONFIG_REPORT` ויוצא
ב-`if (!txn->has_rid) return;` (`zb.c:307`).

הקוד מזיין דדליין של 8 שניות ל-bind — ואין לו מטפל כשהוא מצלצל. אם
`bind_result_cb` לא נורה בזמן, לא נשלח כלום: לא ack, לא event.

סותר את `UART_PROTOCOL.md:80` ("outcome follows as an event"). ברשימת ה-reasons
(`:113`) אין סיבה שמתארת פקיעת bind.

**השפעה מוגבלת:** ל-`zigbee_gateway.py` יש טיימר retry עם backoff שממשיך לרוץ, אז
זו לא תקיעה — אלא עיוורון אבחוני. `reporting_error` נשאר ריק וה-hub מנסה שוב בלי
לדעת למה.

### F-2 · endpoint לא משתתף בהתאמה

`txn_match()` מקבל kind, short_addr, tsn — **אין פרמטר endpoint** (`txn.h:102`,
`txn.c:84`). הגוף מסנן על `kind` ו-`short_addr` בלבד; `slot->endpoint` לא נקרא
לעולם, והנפילה היא ל-`deadline_ms` המוקדם ביותר (`txn.c:99-102`).

שני קוראים מעבירים גם `tsn_valid = false`, כלומר נופלים תמיד: `zb.c:540`
(`on_config_report_rsp`) ו-`zb.c:738` (`on_read_report_cfg_rsp`).

**מה שהופך את זה לממצא:** אותו קובץ קורא את ה-endpoint מהכותרת במקום אחר —
`on_report_attr` עושה `ep = rpt->in.header->src_ep` (`zb.c:1018`). המידע קיים,
זמין, ובשימוש.

תוצאה על מתג דו-גאנגי (שתי טרנזקציות פתוחות לאותה `short_addr`):
- `on_config_report_rsp` — ה-endpoint שמדווח ל-hub מועתק מהטרנזקציה (`zb.c:542`)
  ולא מהמכשיר שענה, ולכן יכול להתהפך.
- `on_read_report_cfg_rsp` — לא שולח endpoint בכלל; הוא עונה תחת ה-`request_id`
  הלא נכון (`zb.c:742,764`).

**עדיין לא פעיל:** ה-hub שולח בקשה אחת לכל ieee. אבל "Multi-gang switches share
one state" הוא פער ידוע ב-README, ו-`device_clusters` קיים במפורש כדי שהגאנג השני
ייוודע. התיקון של הפער הזה מפעיל את הבאג.

**פער בטסטים:** `test_match_ignores_other_devices` מכסה מכשירים שונים. אין טסט
ל"אותו מכשיר, endpoint אחר".

### F-3 · verdict מומצא

אם `txn_match` לא מצא כלום, `on_config_report_rsp` בכל זאת פולט verdict עם
`endpoint = 1` ו-`cluster = OnOff` כניחושים (`zb.c:542,546,550`). אין
`if (txn == NULL) return`.

שתי האחיות נזהרות: `on_read_report_cfg_rsp` יוצא ב-`if (!awaited) return`
(`zb.c:746`), ו-`on_read_attr_rsp` מוריד לאירוע `attribute_report` במקום להמציא
request_id (`zb.c:1000-1006`). התבנית הנכונה כתובה בקובץ פעמיים.

### F-4 · `remove_device` ללא בדיקה

`zb.c:781-788`: `ezb_zdo_nwk_mgmt_leave_req(&leave)` — ערך ההחזרה נזרק, שום
callback לא נרשם, לא מוקצית טרנזקציה, ואז `send_ack(..., "ok", ...)` רץ ללא תנאי.

זהו הדפוס שההערה ב-`zb.c:421` מתארת כבאג ההיסטורי: *"The old firmware discarded
this and acked ok regardless."*

**הסתייגות:** כותרות `ezbee` לא ברפו (רכיב חיצוני מוצמד ל-`espressif/esp-zigbee-lib
==2.0.3`), אז לא ניתן להוכיח מכאן שיש שדה `cb` או ערך החזרה. מה שכן ניתן להוכיח:
כלום לא נבדק.

### F-5 · `missing_ieee`

`zb.c:772` שולח `missing_ieee`. הרשימה ב-`UART_PROTOCOL.md:92-94` לא מכילה אותו
(`bad_ieee` הוא קוד אחר לענף אחר, `zb.c:775`). חיפוש בכל `src/` מחזיר אפס תוצאות.

### F-6 · גלישת דור

`make_handle` אורז `generation << 8` לתוך `uint32_t` (`txn.c:21`), אבל `txn_get`
משווה מול הדור המלא (`txn.c:74`). מדור `0x01000000` והלאה `txn_get` מחזיר `NULL`
תמיד.

**לא סמוי** — הפקיעה עובדת על מצביע ולא על handle (`txn.c:114`), אז כל פקודה
תיכשל ברעש ולא תיעלם. דורש ~16.7M הקצאות. הערה בסוגריים — אבל ההערה בראש `txn.c`
מתארת בדיוק באג כזה שכבר קרה כשהשדה היה nibble.

---

## סדר הפעולות

הסדר לפי **תלות**, לא לפי חומרה: F-1 ו-F-5 מוסיפים או חושפים מילים באוצר המילים
של הפרוטוקול, ומילה שחוצה C ↔ תיעוד ↔ פייתון היא בדיוק מה שיצר את הסחף. בונים את
הרשת לפני שקופצים.

### שלב 0 · טסט הצמדה לאוצר המילים

`CLAUDE.md` קובע: מושג שחוצה גבול בלי import מקבל מקור אחד, וכשזה בלתי אפשרי
(שפות שונות) — טסט הצמדה. C, Markdown ופייתון הם המקרה הזה. תקדימים:
`tests/test_zman_keys_are_in_sync.py`, `tests/test_boot_sentinel_is_in_sync.py`.

צרו `tests/test_protocol_vocab_is_in_sync.py`:
- פרסינג טקסטואלי של `zb.c` ו-`link.c`
- הוצאת כל מחרוזת ב-`send_error(...)` וכל `reason` ב-`report_reporting_outcome`
- השוואה מול `docs/UART_PROTOCOL.md:92-94` (קודי שגיאה) ו-`:113` (reasons)

הטסט **ייכשל מיד** ויתפוס את F-5. זה מוכיח אותו לפני שסומכים עליו.

### שלב 1 · F-5

הוסיפו `missing_ieee` לרשימה ב-`UART_PROTOCOL.md:92-94`.

**התיעוד שגוי, לא הקוד:** `missing_ieee` (שדה חסר) עקבי עם `missing_state` שכבר
מתועד, ונבדל מ-`bad_ieee` (שדה קיים אך פגום). אל תמזגו.

טסט שלב 0 עובר. → קומיט.

### שלב 2 · F-2 (test-first)

היחיד שהלוגיקה שלו בקוד שניתן לבדוק על ה-host.

**2.1 — טסטים נכשלים** ב-`host_test/test_main.c`:
- שתי `CONFIG_REPORT` פתוחות לאותה `short_addr`, endpoints 1 ו-2 → כל תגובה
  מותאמת ל-endpoint הנכון
- אותו דבר ל-`READ_REPORT_CFG`
- רגרסיה: תגובה בלי endpoint ידוע מותאמת כמו היום

**2.2 — חתימה** (`txn.h:102`, `txn.c:84`):

```c
txn_handle_t txn_match(txn_table_t *table, txn_kind_t kind,
                       uint16_t short_addr, uint8_t tsn, bool tsn_valid,
                       uint8_t endpoint, bool endpoint_valid);
```

צמד `endpoint, endpoint_valid` בדיוק כמו `tsn, tsn_valid` הקיים.

**2.3 — כלל ההתאמה (החלק הרגיש):** ה-endpoint **מצמצם רק את מסלול הנפילה ולעולם
לא גובר על TSN**. סדר: TSN אם יש → אחרת oldest מסונן ב-endpoint → אחרת oldest
כמו היום.

הפיכת ההתאמה לקפדנית מסוכנת בכיוון ההפוך: מכשיר שעונה מ-endpoint לא צפוי יאבד
התאמה ויקבל פקיעה במקום תשובה. `endpoint_valid = false` שומר על ההתנהגות הקיימת
בדיוק.

**2.4 — שלושת הקוראים** קוראים endpoint מהכותרת כמו `zb.c:1018`:
`zb.c:540`, `zb.c:738`, `zb.c:984` (באחרון TSN כבר עובד — חגורה מעל כתפיות).

**2.5 — `on_config_report_rsp` מדווח endpoint מהתגובה**, לא מהטרנזקציה
(`zb.c:542,550`). המכשיר שענה הוא מקור האמת.

→ קומיט.

### שלב 3 · F-1 ו-F-3

**3.1 —** ענף ב-`expired_txn_cb` (`zb.c:300`):

```c
if (txn->kind == TXN_KIND_BIND) {
    report_reporting_outcome(txn->short_addr, txn->endpoint, txn->cluster,
                             false, "bind_no_response", -1);
    return;
}
```

מילה חדשה → רשימת ה-reasons ב-`UART_PROTOCOL.md:113`. טסט שלב 0 אוכף.
צד ה-hub בטוח: `_on_reporting_result` שומר את ה-reason כמחרוזת אטומית
ב-`reporting_error` (`zigbee_gateway.py:351-356`), אז אין שינוי נדרש בפייתון.

**3.2 —** שמירת NULL ב-`on_config_report_rsp` (`zb.c:541`):
`if (txn == NULL) { TXN_UNLOCK(); return; }`

בדיקת `txn == NULL` ולא `has_rid` — טרנזקציות `CONFIG_REPORT` מוקצות תמיד בלי rid
(`zb.c:578`), אז הגרסה של האחיות לא ישימה כאן.

→ קומיט.

### שלב 4 · F-4

**קודם בדקו את הכותרת** של `esp-zigbee-lib 2.0.3`: האם ל-
`ezb_zdo_nwk_mgmt_leave_req_t` יש שדה `cb` כמו ל-`ezb_zdo_bind_req_t`, והאם
הפונקציה מחזירה `ezb_err_t`.

- **יש callback:** הקצו טרנזקציה, החזירו `accepted` מיד, שדרגו ל-`delivered`/
  `failed` מה-callback — כמו `on_off`.
- **אין:** לפחות בדקו ערך החזרה ושלחו `send_failed` בכישלון.

ה-`ok` הנוכחי כבר מתועד כ"הסטאק לקח את זה" ולא כהוכחה (`UART_PROTOCOL.md:59`), אז
המחדל אינו ה-`ok` — הוא שכלום לא נבדק.

→ קומיט.

### שלב 5 · F-6

טסט ב-`host_test`: `table.next_generation = 0xFFFFFE`, הקצו שלוש, ודאו שכולן
ניתנות לאחזור.

תיקון שורה אחת (`txn.c:49`):

```c
slot->generation = (table->next_generation++) & 0xFFFFFFu;
```

כדי ששני צדי ההשוואה ידברו על אותו ערך.

→ קומיט.

### שלב 6 · אימות

```bash
bash firmware/h2_coordinator/host_test/run.sh      # אמור לגדול מ-1234 בדיקות
```

תחת סניטייזרים (תופס מה ש-`-Werror` לא):

```bash
cd firmware/h2_coordinator
gcc -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
    -fno-sanitize-recover=all -I main -o /tmp/h2_san \
    host_test/test_main.c main/protocol.c main/txn.c && /tmp/h2_san
```

צד הפייתון:

```powershell
$env:PYTHONPATH = "src"; python -m pytest -q
ruff check .
```

**ואז החומרה — ואין לזה תחליף.** `firmware/tools/build_h2_coordinator.ps1`
לבנייה וצריבה, ואז `products/panel/host/run_hwtest.py` מול ה-H2 והממסרים
האמיתיים. `main/idf_component.yml` קובע את זה במפורש: שינוי בקושחה אינו מאומת
בלעדיו.

---

## מחוץ להיקף

שלב 2 **פותח** את התיקון של הפער הידוע ב-README — `_states` שממופתח לפי ieee בלבד
ולכן שני גאנגים דורסים זה את מצבו של זה. זו עבודה נפרדת בצד ה-hub, והיא תלויה
בשלב 2: אין טעם לפצל מצב לפי endpoint כשהרכזת עדיין מייחסת תשובות ל-endpoint
הלא נכון.

## מה לא נבדק

- **האינטראקציה עם `esp-zigbee-lib` עצמה.** הכותרות לא ברפו (רכיב חיצוני), אז
  חוזי ה-API אינם ניתנים לאימות מקריאת הריפו. זה מה שמשאיר את F-4 פתוח.
- **`zb.c` תחת ריצה.** אין לו כיסוי טסטים ולא ניתן להריץ אותו מחוץ ללוח. כל ששת
  הממצאים נובעים מקריאה ומהצלבה מול החוזה, לא מהרצה.
