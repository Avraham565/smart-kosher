# panel_mp — the panel UI in MicroPython (rendering-stability test)

זהו **פורט 1:1 של ה-UI שב-`panel/`** (C/ESP-IDF) ל-MicroPython + lvgl_micropython,
נבנה למטרה אחת: **לבדוק אם ה-UI הרזה מרנדר יציב על החומרה ב-MicroPython**, אחרי
שסאגת הדריפט הביאה למעבר ל-C. אותה ארכיטקטורה, אותה שיטת ניהול מסכים, אותו עיצוב —
המשתנה היחיד הוא השפה/דרייבר.

## מה זהה ל-C (בכוונה)

| C (`panel/main/ui/`) | כאן | תפקיד |
|---|---|---|
| `theme.h` | `theme.py` | טוקנים (צבעי style.css), `card()`/`screen()`, טעינת פונטים |
| `widgets.c` | `widgets.py` | `w_label`/`w_group`/`w_stripe`/`w_header`/`w_card_button` |
| `shell.c` | `shell.py` | `page_create` (chrome: header דק + חזרה + שעון-פינה) + `placeholder` |
| `page.c` | `pages.py` | registry ניטרלי-לפריסה (5 עמודים, hex accents) |
| `clock.c` | `clock.py` | שעון mock (11:57, tick דקה, LTR enforced) |
| `ui_home.c` | `ui_home.py` | ראש עשיר + hero+4 — הפריסה חיה רק פה |
| `main.c` | `display.py` + `main.py` | bring-up חומרה + wiring |

הפונטים (`fonts/assistant_*.bin`) נטענים ב-runtime עם `lv.binfont_create` (כמו
ב-hebrew_probe), לא מקומפלים פנימה.

## מה **שונה** מ-C — וזה הלב של הבדיקה

ל-C יש **bounce buffers** של `esp_lcd` (Track B) שפתרו את הדריפט. דרייבר ה-RGB של
lvgl_micropython חושף רק את מסלול **שני ה-framebuffers המלאים ב-SPIRAM**
(`RENDER_MODE.FULL`, swap בלי copy) — לא bounce. לכן הכפתור המרכזי לבדיקה הוא
`display.PCLK_HZ` (ברירת מחדל 14MHz — "max safe" מיוני; 21MHz גלש).

## צריבה

דורש firmware של **lvgl_micropython עם `LV_USE_BIDI=1` + פונט DejaVu-Hebrew**
(ראה `deploy/lvgl_micropy_S3_bidi_hebrew.bin` אם קיים, או ה-build מהזיכרון
[[lvgl-crowpanel]]). ואז:

```powershell
.\panel_mp\deploy.ps1 -Port COM8
```

ה-script מנקה קודם את הלוח (מוחק main.py + reset) כי ה-DMA של LVGL רץ ברקע ומפיל
`mpremote cp` באמצע — זו הדרך הבטוחה המתועדת.

## פרוטוקול הבדיקה (מה שמכריע היתכנות)

1. לצרוב, ולהשאיר את מסך הבית **ב-idle 15-20 דקות**. בדיקה קצרה מטעה — "היציבות
   מיוני הייתה אשליה" כי הבדיקות היו קצרות.
2. לחפש: **סחיפה אופקית** מתמשכת, **גלגול** אנכי, קרעים, או **טשטוש קצה-שמאל**.
3. ללחוץ על הכרטיסים (ניווט = החלפת מסך מיידית, בלי אנימציה) ולחזור — לוודא שאין
   shear/flicker בהחלפה.
4. אם נקי אחרי 20 דקות → הפורט בר-קיימא, וממשיכים לחבר את המוח (async על אותו
   loop). אם גולש → לרדת ב-`PCLK_HZ` (12MHz) ולחזור; אם עדיין → הבעיה מתחת ל-LVGL
   (bandwidth/timing), ו-MicroPython בלי bounce buffers כנראה לא יספיק.

## מה זה עדיין **לא**

טהור-UI. אין מוח, אין UART ל-H2, אין שעון אמיתי — בדיוק כמו שלב ה-C המקביל. אלה
נכנסים רק **אחרי** שהרינדור מוכרע. תלוי בהצלחת הבדיקה הזו.
