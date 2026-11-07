#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.630.0 D (#4671): tools/pins.py --wheels compares the libraries inside the Pillow wheel (PIL.features.version) with
WHEEL_MIN; the Dockerfile runs it after pip install. Offline: the versions are given, no image. Python standard library only.
 - equal or newer = no problem, older = a problem naming library and minimum, a missing library (None, an unknown feature,
   no number) = a problem; versions with a suffix (1.3.1.zlib-ng) and of different length (2.19 vs 2.19.0) compare right
 - WHEEL_MIN names the libraries of #4671; the Dockerfile runs --wheels after the pip install of the final stage, before pip
   is removed"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pins  # noqa: E402
from kt import check, done  # noqa: E402

MIN = (("libjpeg-turbo", "libjpeg_turbo", "3.2.0"), ("zlib-ng", "zlib_ng", "2.3.3"), ("lcms2", "littlecms2", "2.19"))


def fake(**v):
    def version(feat):
        if feat not in v:
            raise ValueError(f"Unknown feature '{feat}'")
        return v[feat]
    return version


out = pins.wheel_problems(fake(libjpeg_turbo="3.2.0", zlib_ng="2.3.3", littlecms2="2.19.0"), MIN)
check(out == [], f"equal versions are fine (2.19.0 = 2.19): {out}")
out = pins.wheel_problems(fake(libjpeg_turbo="3.10.1", zlib_ng="2.4.0.zlib-ng", littlecms2="2.20"), MIN)
check(out == [], f"newer versions are fine (3.10 > 3.2, a suffix is ignored): {out}")
out = pins.wheel_problems(fake(libjpeg_turbo="3.1.9", zlib_ng="2.3.3", littlecms2="2.18.9"), MIN)
check(len(out) == 2 and "libjpeg-turbo 3.1.9 is older than the minimum 3.2.0" in out[0] and "lcms2 2.18.9" in out[1],
      f"older versions are problems with name and minimum: {out}")
out = pins.wheel_problems(fake(libjpeg_turbo=None, zlib_ng="unknown", littlecms2="2.19"), MIN)
check(len(out) == 2 and all("no version" in p for p in out), f"None / no number = a missing library: {out}")
out = pins.wheel_problems(fake(zlib_ng="2.3.3", littlecms2="2.19"), MIN)
check(len(out) == 1 and out[0].startswith("libjpeg-turbo: no version"), f"an unknown feature is a missing library: {out}")
check(pins._vtuple("4.7.2") == (4, 7, 2) and pins._vtuple("1.3.1.zlib-ng") == (1, 3, 1) and pins._vtuple("") is None,
      "version parsing")

names = {n for n, _, _ in pins.WHEEL_MIN}
check({"libjpeg-turbo", "zlib-ng", "libtiff", "libwebp", "freetype"} <= names, f"WHEEL_MIN has the libraries of #4671: {names}")
check(all(pins._vtuple(m) for _, _, m in pins.WHEEL_MIN), "every minimum is a version")

text = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
final = text.rfind("\nFROM ")
run = text.find("python /tmp/pins.py --wheels")
inst = text.find("pip install", final)
check(run > inst > final and run < text.find("python -m pip uninstall -y pip", final),
      "the Dockerfile runs pins.py --wheels in the final stage after pip install, before pip is removed")
check(re.search(r"COPY tools/pins\.py /tmp/pins\.py\n", text[final:run]) is not None, "the Dockerfile copies pins.py for that step")

sys.exit(done("p2630_d_pins_test"))
