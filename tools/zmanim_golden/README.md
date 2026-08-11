# Zmanim reference table

`src/smart_kosher/zmanim` is a port of [KosherJava](https://github.com/KosherJava/zmanim).
This directory regenerates the table the port is checked against.

```
python tools/zmanim_golden/generate.py
```

Downloads KosherJava 2.5.0 from Maven Central, compiles `GenerateGolden.java`,
runs it over every city in `src/smart_kosher/data/cities.json` for 2024–2027,
and writes `tests/data/zmanim_golden.csv.gz` (~58,000 rows).

Four years, not more: the sun repeats itself almost exactly every leap cycle,
so extra years cost file size and buy nothing. The budget goes to locations,
which genuinely differ — 40 cities from Eilat to Nahariya, sea level to 850 m.

Needs a JDK on `PATH`. Nothing else in the project does — the output is
committed, and `tests/test_zmanim_reference.py` reads the committed file.

## When to run it

- the reference version changes (`KOSHERJAVA_VERSION`)
- a city is added, removed, or its coordinates or elevation move
- a zman is added or its definition changes

The test fails loudly if a city is missing from the table, so an out-of-date
file cannot pass unnoticed.

After regenerating, run the exhaustive sweep once — the normal test run only
samples the table, so a regression outside the sample would otherwise wait:

```
ZMANIM_FULL_REFERENCE=1 python -m pytest tests/test_zmanim_reference.py
```

## Why the values look the way they do

Each value is **seconds from UTC midnight** of the row's date, to one tenth of
a second. Both sides of the comparison speak that unit, so no time zone or DST
rule enters the test. Values may fall outside `[0, 86400)` — solar midnight
lands after it, which is correct, not a bug.

The calendar is configured to match the product:

| setting | value | why |
|---|---|---|
| `useElevation` | `false` | the library default: derived zmanim come off sea level, only sunrise/sunset carry the elevation correction |
| `candleLightingOffset` | `18` | the library default |

`sunrise_sea` and `sunset_sea` are emitted but map to no zman. They are there
so a failure can be read: if the elevation split regresses, they show which
side of it moved.

## Elevations

`cities.json` elevations are the SRTM 30 m model sampled at each city's own
coordinate, cross-checked against ASTER 30 m (the two agree within 10 m
everywhere). Sampling the exact coordinate is the only self-consistent choice —
a published "elevation of city X" has no single answer, as Jerusalem spans
roughly 650–830 m.

Below sea level is stored as `0`: KosherJava's `GeoLocation` rejects a negative
elevation outright, so that is what it would compute for Tiberias anyway.
