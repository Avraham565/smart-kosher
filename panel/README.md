# Panel A — firmware מסך ב-C ‏(ESP-IDF)

‏UI בלבד על ה-ESP32-S3 של ה-CrowPanel Advance 7". הלוגיקה (זמנים, תזמונים, Zigbee)
רצה על hub נפרד (AtomS3 Lite + NanoC6 — קוד מוצר ב' כמו שהוא) ומדברת עם הפאנל
ב-UART באותו פרוטוקול ops של `client/bridge.py`.

## למה C ולא MicroPython על המסך

ראה `docs/` + זיכרון הפרויקט: דרייבר ה-RGB של lvgl_micropython על S3 הוא קוד קהילה
עם חלון יציבות אמפירי צר (דריפט אופקי, קפיצות בגלילה — נצפו על החומרה ב-2026-07-16).
‏Elecrow לא מתעדת MicroPython לפאנל הזה כלל. המסלול כאן בנוי אך ורק מרכיבים רשמיים:

| שכבה | מקור | תיעוד |
|---|---|---|
| esp_lcd RGB + bounce buffers | Espressif (core IDF) | [RGB LCD docs — "screen drift"](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html) |
| esp_lvgl_port ‏(bb_mode+avoid_tearing) | Espressif (component registry) | [esp_lvgl_port](https://components.espressif.com/components/espressif/esp_lvgl_port) |
| esp_lcd_touch_gt911 | Espressif | component registry |
| תזמוני מסך (21MHz, porches 8/4/8, clock edge) | Elecrow factory code | [CrowPanel-Advance-7 repo → LovyanGFX_Driver.h](https://github.com/Elecrow-RD/CrowPanel-Advance-7-HMI-ESP32-S3-AI-Powered-IPS-Touch-Screen-800x480) |

מיפוי קוטביות שאומת מול המקורות: ‏LovyanGFX ‏`pclk_idle_high=1` מתכנת את ביט
‏`lcd_ck_out_edge` ⇒ ‏ב-esp_lcd זה `pclk_active_neg=1` (תואם גם לממצא האמפירי מיוני).

## דרישות build

- ‏ESP-IDF ‏v5.3+ ‏(נבנה עם v5.5.1). כל checkout נקי עובד:
  `git clone -b v5.5.1 --recursive https://github.com/espressif/esp-idf`
  (כרגע בשימוש ה-checkout שב-`~/lvgl_micropython/lib/esp-idf` ב-WSL — תקין וזהה.)
- הקומפוננטות יורדות אוטומטית מה-registry לפי `main/idf_component.yml`
  וננעלות ב-`dependencies.lock`.

## build + צריבה

```bash
# WSL
source <esp-idf>/export.sh
cd panel
idf.py set-target esp32s3   # פעם ראשונה בלבד
idf.py build
```

```powershell
# Windows — צריבה על COM8 (ערכי ה-offsets מודפסים בסוף ה-build):
python -m esptool --chip esp32s3 -p COM8 -b 460800 write-flash `
  0x0 build/bootloader/bootloader.bin `
  0x8000 build/partition_table/partition-table.bin `
  0x10000 build/panel_a.bin
```

## עברית/RTL

- ‏`CONFIG_LV_USE_BIDI=y` + ‏`base_dir=RTL` על ה-screen ⇒ כל ה-widgets מתהפכים.
- קלט טקסט חופשי לא נתמך ב-BiDi (מגבלת LVGL מתועדת) ⇒ קלט מבוסס בחירה בלבד.
- פונט בדיקה: ‏DejaVu עברי מובנה. פונט המוצר: ‏Assistant יומר עם `lv_font_conv`
  ל-C ‏(`--format lvgl`) ויקומפל פנימה — אין כאן מגבלת מקום כמו ב-firmware הפייתון.

## חומרה (אומת על הלוח)

- ‏RGB: ‏B0-B4=21,47,48,45,38; ‏G0-G5=9-14; ‏R0-R4=7,17,18,3,46; ‏HSYNC=40 VSYNC=41 DE=42 PCLK=39
- ‏I2C0 ‏(SDA=15,SCL=16): ‏GT911 ‏@0x5D ‏(בלי RST/INT), תאורה אחורית — expander ‏@0x30, ביט 1
- ‏UART פנוי ל-hub: ‏TX=5, RX=19 (אותם פינים ששימשו ל-H2)
