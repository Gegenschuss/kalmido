#!/usr/bin/env python3
"""#5298 (Profi-Bewertung F14): starts the app under coverage inside the TEST container - never in the image, never live.

tests/start.sh runs it instead of `python app.py` when KALMIDO_TEST_COVERAGE names a folder on the host (the full CI run,
.github/workflows/ci.yml): the folder's lib/ (coverage installed with pip --target, plus this file) is mounted read-only at
/cov/lib and on PYTHONPATH, its data/ writable at /cov/data. Every server process writes its own data file
/cov/data/.coverage.<host>.<pid>.<random> (data_suffix); the job "coverage" of ci.yml combines the files of all shards.

The suites end their containers hard (docker rm -f = SIGKILL, no atexit), so the data is written every FLUSH_S seconds while
the server runs (coverage's flush is safe beside tracing threads: it copies the sets first) and once more on SIGTERM
(docker stop): the handler stops measuring, saves and ends the process like the app's own stop handling does (as PID 1 of a
container the default handling would ignore the signal). bgjobs.bgj_on_term() finds this handler as the former one and calls
it after it released its rows. At most the last FLUSH_S seconds of a SIGKILLed container are lost - the figure is a floor.
Measures app.py and kalmido/ only; isolated sub-processes (python -I, e.g. the PDF scan worker) are not measured.
"""
import os
import runpy
import signal
import sys
import threading
import time

import coverage

FLUSH_S = float(os.environ.get("KALMIDO_COV_FLUSH_S", "3"))
APP = os.environ.get("KALMIDO_COV_APP", "/app/app.py")  # the test of this file points both at a temp folder
DATA = os.environ.get("KALMIDO_COV_DATA", "/cov/data")

# sys.monitoring (Python 3.12+): line coverage at a fraction of the classic tracer's cost - the shards keep their times
os.environ.setdefault("COVERAGE_CORE", "sysmon")
cov = coverage.Coverage(data_file=os.path.join(DATA, ".coverage"), data_suffix=True, config_file=False,
                        include=[APP, os.path.join(os.path.dirname(APP), "kalmido", "*")])
_lock = threading.Lock()


def _save():
    with _lock:
        try:
            cov.save()
        except Exception as e:  # noqa: BLE001 -- measuring must never stop the server under test
            print("cov_boot: save failed:", type(e).__name__, e, file=sys.stderr, flush=True)


def _flusher():
    while True:
        time.sleep(FLUSH_S)
        _save()


def _on_term(signum, frame):
    try:
        cov.stop()
    except Exception:  # noqa: BLE001
        pass
    _save()
    os._exit(128 + signum)


if __name__ == "__main__":
    cov.start()
    signal.signal(signal.SIGTERM, _on_term)
    threading.Thread(target=_flusher, name="cov-flush", daemon=True).start()
    sys.argv = [APP] + sys.argv[1:]
    sys.path.insert(0, os.path.dirname(APP))
    try:
        runpy.run_path(APP, run_name="__main__")
    finally:
        cov.stop()
        _save()
