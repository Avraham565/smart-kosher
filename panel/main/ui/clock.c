#include "clock.h"

/* Mock time base — matches the approved header mockup. */
static int s_hh = 11;
static int s_mm = 57;

#define MAX_TIME_LABELS 12   /* home + one corner clock per sub-page */
static lv_obj_t *s_labels[MAX_TIME_LABELS];
static int s_label_count;

static void time_str(char *buf, size_t n)
{
    lv_snprintf(buf, n, "%02d:%02d", s_hh, s_mm);
}

static void apply_to_labels(void)
{
    char buf[8];
    time_str(buf, sizeof(buf));
    for (int i = 0; i < s_label_count; i++) {
        if (s_labels[i]) {
            lv_label_set_text(s_labels[i], buf);
        }
    }
}

static void tick_cb(lv_timer_t *t)
{
    LV_UNUSED(t);
    if (++s_mm >= 60) {
        s_mm = 0;
        if (++s_hh >= 24) {
            s_hh = 0;
        }
    }
    apply_to_labels();
}

void clock_bind_time(lv_obj_t *label)
{
    if (s_label_count < MAX_TIME_LABELS) {
        s_labels[s_label_count++] = label;
    }
    /* A clock is LTR numerals — force it so an RTL parent paragraph doesn't
     * reorder "11:57" into "57:11". */
    lv_obj_set_style_base_dir(label, LV_BASE_DIR_LTR, LV_PART_MAIN);
    char buf[8];
    time_str(buf, sizeof(buf));
    lv_label_set_text(label, buf);
}

void clock_start(void)
{
    /* 60000 ms — one mock minute per real minute. */
    lv_timer_create(tick_cb, 60000, NULL);
}

const char *clock_date_hebrew_dow(void) { return "יום ה׳"; }
const char *clock_date_hebrew(void)     { return "ט׳ באב תשפ״ו"; }
const char *clock_date_gregorian(void)  { return "23/07/2026"; }
