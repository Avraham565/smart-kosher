# מוצר א׳ — הפאנל

**זהו המוצר**, לא ניסוי. ה-CrowPanel Advance 7" מריץ כאן את ה-UI **ואת המוח**
בתהליך MicroPython אחד, על **לולאת asyncio אחת**, עם ה-H2 מחובר ב-UART1.

> הקובץ הזה תיאר פעם ניסוי רינדור טהור ("אין מוח, אין UART, אין שעון אמיתי").
> זה נכון עד 2026-07-29 בלבד. הניסוי הצליח, והתיקייה גדלה למוצר.

## המבנה

| תיקייה | הכלל |
|---|---|
| `device/` | **כל מה שכאן נצרב ללוח, ושום דבר אחר.** `deploy.ps1` דוחף את התיקייה, לא רשימה |
| `hwtest/` | רץ על הלוח, מועלה רק לצורך הרצת בדיקה |
| `host/` | רץ על ה-PC; נוגע במערכת הקבצים של הלוח רק דרך mpremote |

## מה רץ כאן

| רכיב | קובץ | תפקיד |
|---|---|---|
| bring-up חומרה | `display.py` | RGB 800×480, GT911 touch, I2C משותף (מפרסם `display.i2c` ל-RTC) |
| pump של LVGL | `lvgl_loop.py` | `lv.tick_inc` + `lv.timer_handler` **על הלולאה** — לא `task_handler.TaskHandler` |
| קומפוזיציה | `brain.py` | בונה את `Api` של `smart_kosher` in-process |
| גשר UI→מוח | `bridge.py` | callback סינכרוני של LVGL → `await api.dispatch` |
| מנוע תזמון | `smart_kosher/application/scheduler.py` | מה שהופך תזמון שמור לפקודה שנשלחת (+catch-up בבוט). **במוח, לא כאן** — `main.py` רק מפעיל אותו כמשימה |
| שכבה ריאקטיבית | `reactive.py`, `store.py` | signals; מסך קורא מ-store דרך `bind`, לא polling |
| נקודת כניסה | `main.py` | סדר בוט + כל המשימות על לולאה אחת |
| בדיקות חומרה — רדיו | `hwtest.py`, `run_hwtest.py` | 26 קביעות מול H2 ומפסקים אמיתיים |
| בדיקות חומרה — מסך | `hwtest_ui.py`, `run_hwtest_ui.py` | 34 קביעות: מסכים נבנים, נכנסים ל-800×480, לא דולפים |
| בדיקות חומרה — זמנים | `hwtest_zmanim.py`, `run_hwtest_zmanim.py` | 540 ערכים מהמכשיר מול טבלת הייחוס (float חד-דיוק!) |

שאר הקבצים הם מסכים (`ui_home`, `rooms_page`, `room_page`, `device_page`,
`zmanim_page`, `schedules_page`, `schedule_add`, `settime`) ורכיבים
(`theme`, `widgets`, `shell`, `keyboard`, `toast`, `text_input`,
`zone_picker`, `city_picker`).

## שלושה כללים שאסור לשבור

1. **בלי `gc.collect()` / `gc.threshold()` אחרי שהרינדור התחיל.** משחרר partial
   buffer שה-copy task על core 0 עדיין מצביע אליו → `LoadProhibited` bootloop.
   (זו בדיוק האסטרטגיה ה*נכונה* למוצר ב׳, שאין לו PSRAM. כאן היא אסורה.)
2. **בלי scroll ובלי אנימציית מסך-מלא.** לפאנל אין GRAM; ה-DMA סורק את ה-FB
   מחדש בכל פריים. המסקנה שקל לפספס: מה שלא נכנס ל-800×480 **מצויר מחוץ לדף
   ונעלם בשקט** — אין סרגל גלילה שיגיע אליו ואין שגיאה. לכן לכל מסך עם פריסה
   קבועה יש הערת תקציב גבהים בקוד, ו-`hwtest_ui.py` מודד את העץ הבנוי
   בקואורדינטות מוחלטות. חישוב על הנייר כבר פספס פעם 8 פיקסלים.
3. **כל `create_task` מ-callback של UI חייב keepalive.** ב-MicroPython task
   שאף אחד לא מחזיק אליו הפניה נאסף לפני שהוא רץ — `bridge.py` מצמיד אותם
   ב-`_pending`. בלי זה הפעולה פשוט לא קורית, בשקט.

## למה MicroPython, אחרי שנטשנו לטובת C

הדריפט **לא** נבע מהשפה. דרייבר ה-RGB של lvgl_micropython לא הגדיר
`bounce_buffer_size_px`, אז ה-DMA סרק ישירות מ-PSRAM וכל latency spike הרעיב
אותו. הפתרון כאן: **בלי** `frame_buffer1/2` ל-`RGBDisplay` ⇒ הדרייבר מקצה
partial buffers ב-SRAM פנימי (`RENDER_MODE.PARTIAL`), שזה שקול-תפקודית
ל-bounce buffers של `esp_lcd` בקושחת ה-C. `PCLK_HZ = 18MHz`.

דורש firmware של lvgl_micropython עם `LV_USE_BIDI=1`, פונט עברי, ו-sdkconfig
עם `DATA_CACHE_LINE_64B` + `SPIRAM_XIP_FROM_PSRAM`.

## צריבה

```powershell
.\products\panel\host\deploy.ps1 -Port COM8
```

`deploy.ps1` קורא קודם ל-`clean_board.py`: לוח שכבר מרנדר ממשיך להריץ DMA ברקע
גם ב-REPL, וכל העברת קובץ מתנגשת בו ומשחיתה את ה-VFS. `clean_board` עושה
hardware-reset ומציף Ctrl-C בחלון הבוט כדי לעצור את `main.py` **לפני**
`display.init()`. אף פעם לא `mpremote cp` נקודתי ללוח שמרנדר.

### קושחה — `flash.py`, ולא esptool ביד

```powershell
python products\panel\host\flash.py --bin <firmware.bin>
```

`deploy.ps1` פורס **קבצים**. הוא לא צורב **קושחה**, ולצריבה יש `--erase-all`
שמוחק את ה-VFS כולו — **ובתוכו `/data`**: מכשירים, אזורים, תזמונים והגדרות.

`flash.py` עושה את הרצף שלם: מגבה את `/data` ו**מאמת לפי גודל** מול הרשימה של
הלוח, מארכב את הבינרי שנצרב (כדי שאפשר יהיה לחזור), צורב, מריץ `deploy.ps1`,
ומחזיר את `/data` — שוב עם אימות גדלים. **גיבוי שלא תואם = סירוב לצרוב.**

לפי גודל ולא לפי קוד יציאה: mpremote מדווח הצלחה מצד המארח, והמארח אינו המקום
שאליו הקובץ נחת (משימה 46 — `main.py` חזר פעמיים באפס בתים).

`flash.py` **אינו בונה**. בנייה דורסת את `build/*.bin` במקום, וזה העותק היחיד
של מה שעל הלוח — לגבות לפני. ראה `products/panel/firmware/lvgl_micropython/`.

## מה עוד לא

קבוצות ו-recurrences מבוססות-תאריך (אין UI); מסך הגדרות/עיר; reconcile
(עקיפה ידנית); ריבוי גנגים (ראה "Known gaps" ב-README הראשי).
