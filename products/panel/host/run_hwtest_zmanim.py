"""Diff what the panel computes against the committed reference table.

Runs hwtest_zmanim.py on the device, then compares every value it printed with
tests/data/zmanim_golden.csv.gz -- KosherJava's own output. This closes the last
gap in the chain: the host suite proves the algorithm, and this proves the
device running it agrees, on a single-precision float build where it might not.

    python products/panel/host/run_hwtest_zmanim.py
"""

import csv
import gzip
import os
import subprocess
import sys

from run_common import find_panel, mpremote, restore_main, run_on_device

HERE = os.path.dirname(os.path.abspath(__file__))
# host/ -> panel/ -> products/ -> repo root.
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
DEVICE = os.path.join(HERE, os.pardir, "device")
HWTEST = os.path.join(HERE, os.pardir, "hwtest")
GOLDEN = os.path.join(ROOT, "tests", "data", "zmanim_golden.csv.gz")

# Our key -> reference column, same mapping the host suite uses.
COLUMNS = ("alos_16_1", "misheyakir_11_5", "sunrise_elev",
           "sof_zman_shma_gra", "sof_zman_shma_mga",
           "sof_zman_tfila_gra", "sof_zman_tfila_mga",
           "chatzos", "mincha_gedola", "mincha_gedola_30",
           "mincha_ketana", "plag_hamincha", "sunset_elev",
           "tzais_8_5", "tzais_8_5", "tzais_72", "solar_midnight", "candle_18")

TOLERANCE_SECONDS = 2.0

# 540 zman sets computed on the device, single-precision, one print per row.
# Minutes, not seconds -- but not ten minutes, and an unbounded run would hang
# here forever with main.py still deleted.
RUN_TIMEOUT_S = 600


def _read_device(port):
    """Upload the suite, run it, and return what it printed (None on failure)."""
    print("== uploading ==")
    if mpremote(port, "cp", os.path.join(HWTEST, "hwtest_zmanim.py"),
                ":hwtest_zmanim.py") != 0:
        return None

    print("== running on device ==")
    result = run_on_device(port, "import hwtest_zmanim; hwtest_zmanim.run()",
                           RUN_TIMEOUT_S, capture=True,
                           hint="It prints one row per city-day; the last row "
                                "above is where it stopped.")
    return None if result is None else result


def main():
    port = (sys.argv[1] if len(sys.argv) > 1 else None) or find_panel()
    if port is None:
        print("No panel found (CH340 1A86:7522). Is its USB connected?")
        return 1
    print("panel on {}".format(port))

    print("== stopping main.py ==")
    if subprocess.call([sys.executable, os.path.join(HERE, "clean_board.py"),
                        port]) != 0:
        print("could not reach a clean REPL")
        return 1

    # main.py goes back before anything else can fail -- a black screen is not
    # an acceptable outcome of a read-only check. The device work is a function
    # and the restore a finally, so that holds for the paths that *do* fail too:
    # the upload returning non-zero, and the run timing out, both used to return
    # from here with main.py still deleted.
    try:
        result = _read_device(port)
    finally:
        restored = restore_main(port, DEVICE)
    if not restored:
        return 1
    if result is None:
        return 1
    output = result.stdout or ""

    if "BEGIN" not in output or "END" not in output:
        print("device produced no usable output:")
        print(output[:1000])
        print(result.stderr[:1000] if result.stderr else "")
        return 1

    reference = {}
    with gzip.open(GOLDEN, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            reference[(row["city"], row["date"])] = row

    print()
    worst, worst_where, compared, missing = 0.0, "", 0, []
    for line in output.splitlines():
        if "|" not in line:
            continue
        city, date, values = line.strip().split("|")
        row = reference.get((city, date))
        if row is None:
            missing.append((city, date))
            continue
        for value, column in zip(values.split(","), COLUMNS):
            delta = abs(float(value) - float(row[column]))
            compared += 1
            if delta > worst:
                worst, worst_where = delta, "{} {} {}".format(city, date, column)

    print("compared      : {} values on the device".format(compared))
    print("worst delta   : {:.3f} sec  ({})".format(worst, worst_where))
    print("tolerance     : {} sec".format(TOLERANCE_SECONDS))
    if missing:
        print("NOT IN TABLE  : {}".format(missing))
    ok = compared > 0 and worst <= TOLERANCE_SECONDS and not missing
    print()
    print("DEVICE MATCHES THE REFERENCE" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
