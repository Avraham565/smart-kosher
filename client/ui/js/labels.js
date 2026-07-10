// Hebrew labels for domain values — shared by all views.

export const ZMAN_LABELS = {
  alot_hashachar:             'עלות השחר',
  talit_and_tefillin:         'טלית ותפילין',
  netz_hachama:               'נץ החמה',
  sof_zman_shema_gra:         'סוף זמן שמע (גר"א)',
  sof_zman_shema_mga:         'סוף זמן שמע (מג"א)',
  sof_zman_tfilla_gra:        'סוף זמן תפילה (גר"א)',
  sof_zman_tfilla_mga:        'סוף זמן תפילה (מג"א)',
  chatzot_hayom:              'חצות היום',
  mincha_gedola:              'מנחה גדולה',
  mincha_gedola_30min:        'מנחה גדולה (30 דק׳)',
  mincha_ketana:              'מנחה קטנה',
  plag_hamincha:              'פלג המנחה',
  shkia:                      'שקיעה',
  tset_hakohavim:             'צאת הכוכבים',
  tset_hakohavim_shabbat:     'צאת הכוכבים (שבת)',
  tset_hakohavim_tsom:        'צאת הכוכבים (תענית)',
  tset_hakohavim_rabeinu_tam: 'צאת הכוכבים (ר"ת)',
  chatzot_halayla:            'חצות הלילה',
  candle_lighting:            'הדלקת נרות',
};

export const RECURRENCE_LABELS = {
  daily:                  'יומי',
  days_of_week:           'ימים בשבוע',
  assur_bemelacha:        'שבת ויו"ט',
  erev_assur_bemelacha:   'ערב שבת/יו"ט',
  motzei_assur_bemelacha: 'מוצאי שבת/יו"ט',
  chol_hamoed:            'חול המועד',
  rosh_chodesh:           'ראש חודש',
  hebrew_day_of_month:    'יום בחודש עברי',
  hebrew_date:            'תאריך עברי',
  gregorian_date:         'תאריך לועזי',
  one_time:               'פעם אחת',
};

export const ACTION_LABELS = { on: 'הדלק', off: 'כבה' };

// day index 0=Mon…6=Sun, displayed in Hebrew week order
export const WEEK_DAYS = [
  { idx: 6, label: 'א׳' },
  { idx: 0, label: 'ב׳' },
  { idx: 1, label: 'ג׳' },
  { idx: 2, label: 'ד׳' },
  { idx: 3, label: 'ה׳' },
  { idx: 4, label: 'ו׳' },
  { idx: 5, label: 'ש׳' },
];

export const HEBREW_MONTHS = [
  'ניסן','אייר','סיון','תמוז','אב','אלול',
  'תשרי','חשון','כסלו','טבת','שבט','אדר','אדר ב׳',
];
