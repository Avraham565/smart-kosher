"""Regenerate the reference zmanim table from KosherJava.

    python tools/zmanim_golden/generate.py

Downloads the reference jar, compiles GenerateGolden.java, runs it over every
packaged city, and writes tests/data/zmanim_golden.csv.gz.

Run this only when the reference version, the city list, or the set of zmanim
changes. The output is committed; the test suite reads the committed file and
needs neither Java nor a network.
"""

import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

KOSHERJAVA_VERSION = "2.5.0"
JAR_URL = (
    "https://repo1.maven.org/maven2/com/kosherjava/zmanim/"
    "{v}/zmanim-{v}.jar".format(v=KOSHERJAVA_VERSION)
)

# One full leap cycle. The sun repeats itself almost exactly every four years,
# so a longer span costs file size and buys close to no coverage -- the budget
# is better spent on locations, which do differ. 2024 is the leap year.
START_YEAR = 2024
END_YEAR = 2027

ROOT = Path(__file__).resolve().parents[2]
CITIES = ROOT / "src" / "smart_kosher" / "data" / "cities.json"
OUTPUT = ROOT / "tests" / "data" / "zmanim_golden.csv.gz"
SOURCE = Path(__file__).with_name("GenerateGolden.java")


def _require(tool):
    path = shutil.which(tool)
    if path is None:
        sys.exit("{} not found on PATH -- a JDK is required to regenerate".format(tool))
    return path


def _fetch_jar(destination):
    print("downloading KosherJava {}".format(KOSHERJAVA_VERSION))
    with urllib.request.urlopen(JAR_URL, timeout=120) as response:
        destination.write_bytes(response.read())


def _write_cities_tsv(destination):
    cities = json.loads(CITIES.read_text(encoding="utf-8"))
    lines = [
        "{}\t{}\t{}\t{}".format(city_id, city["lat"], city["lon"], city["elevation"])
        for city_id, city in cities.items()
    ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    return len(lines)


def main():
    _require("javac")
    _require("java")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        jar = tmp / "kosherjava.jar"
        _fetch_jar(jar)

        subprocess.run(
            ["javac", "-cp", str(jar), "-d", str(tmp), str(SOURCE)], check=True
        )

        count = _write_cities_tsv(tmp / "cities.tsv")
        print("generating {}-{} for {} cities".format(START_YEAR, END_YEAR, count))

        plain = tmp / "golden.csv"
        subprocess.run(
            [
                "java",
                "-cp",
                "{}{}{}".format(jar, ";" if sys.platform == "win32" else ":", tmp),
                "GenerateGolden",
                str(tmp / "cities.tsv"),
                str(START_YEAR),
                str(END_YEAR),
                str(plain),
            ],
            check=True,
        )

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 so regenerating identical data produces an identical file and
        # does not show up as a spurious diff.
        with open(plain, "rb") as raw, gzip.GzipFile(
            OUTPUT, "wb", compresslevel=9, mtime=0
        ) as packed:
            shutil.copyfileobj(raw, packed)

    print("wrote {} ({:,} bytes)".format(OUTPUT.relative_to(ROOT), OUTPUT.stat().st_size))


if __name__ == "__main__":
    main()
