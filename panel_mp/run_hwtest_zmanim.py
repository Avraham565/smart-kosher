"""Diff what the panel computes against the committed reference table.

Runs hwtest_zmanim.py on the device, then compares every value it printed with
tests/data/zmanim_golden.csv.gz -- KosherJava's own output. This closes the last
gap in the chain: the host suite proves the algorithm, and this proves the
device running it agrees, on a single-precision float build where it might not.

    python panel_mp/run_hwtest_zmanim.py
"""

import csv
import gzip
import os
import subprocess
import sys

from run_common import find_panel, mpremote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLDEN = os.path.join(ROOT, "tests", "data", "zmanim_golden.csv.gz")

# Our key -> reference column, same mapping the host suite uses.
COLUMNS = ("alos_16_1", "misheyakir_11_5", "sunrise_elev",
           "sof_zman_shma_gra", "sof_zman_shma_mga",
           "sof_zman_tfila_gra", "sof_zman_tfila_mga",
           "chatzos", "mincha_gedola", "mincha_gedola_30",
           "mincha_ketana", "plag_hamincha", "sunset_elev",
           "tzais_8_5", "tzais_8_5", "tzais_72", "solar_midnight", "candle_18")

TOLERANCE_SECONDS = 2.0


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

    print("== uploading ==")
    if mpremote(port, "cp", os.path.join(HERE, "hwtest_zmanim.py"),
                ":hwtest_zmanim.py") != 0:
        return 1

    print("== running on device ==")
    result = mpremote(port, "exec", "import hwtest_zmanim; hwtest_zmanim.run()",
                      capture=True)
    output = result.stdout or ""

    # main.py goes back before anything else can fail -- a black screen is not
    # an acceptable outcome of a read-only check.
    print("== restoring main.py ==")
    if mpremote(port, "cp", os.path.join(HERE, "main.py"), ":main.py") != 0:
        print("!! could not restore main.py; run:")
        print("   python -m mpremote connect {} cp panel_mp/main.py :main.py"
              .format(port))
        return 1
    mpremote(port, "reset")

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
