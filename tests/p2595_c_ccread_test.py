#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.595.0 (#4903): the credit card reader (kalmido/office/ccread.py) on the conversion fee, pure Python, no server.
Every statement, shop and figure is invented.
 - "2,5% für Währungsumrechnung 0,11 -" under a USD position is its own position of kind fee (it fell away before, the sum
   was short by it); the euro amount, the foreign amount and the rate stay apart; the sum fits the printed total
 - the other names of the conversion fee (Umrechnungsentgelt / -gebühr / -aufschlag, Fremdwährungszuschlag, Auslandszuschlag)
   are fees too; the line of the rate ("Umrechnungskurs 1,12") is no position
 - a line under a position with an amount of its own that is neither foreign amount nor rate is never dropped: it is a
   position of its own (kind by its sign, so it asks for a receipt); only when the printed total fits without it, it is no
   position (a footer amount); a lone "EUR 4,47" repeating the amount is no position either
usage: python3 tests/p2595_c_ccread_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys
import types
from decimal import Decimal

from kt import FAILS, OKS, check

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OFF = os.path.join(SRC, "kalmido", "office")
# ccread.py imports .calc: a small package of its own around the two files (calc.py runs alone, see tests/office_calc_test.py)
pkg = types.ModuleType("p2595c")
pkg.__path__ = [OFF]
sys.modules["p2595c"] = pkg
for name in ("calc", "ccread"):
    sp = importlib.util.spec_from_file_location("p2595c." + name, os.path.join(OFF, name + ".py"))
    mod = importlib.util.module_from_spec(sp)
    sys.modules["p2595c." + name] = mod
    sp.loader.exec_module(mod)
ccr = sys.modules["p2595c.ccread"].ccr_mastercard

HEAD = ["Kreditkartenabrechnung vom 20.10.2026", "Beispielbank Mastercard", "Karte 5232 12XX XXXX 4711"]


def read(rows):
    return ccr("\n".join(HEAD + rows))


def pos(r):
    return [(x["merchant"], str(x["amount"]), x["kind"]) for x in r["lines"]]


# ---- the line of the statement in the task (rollback: without the fix the fee line falls away, one position only)
r = read(["18.10.26 19.10.26 ELEVENLABS.IO, NEW YORK USD 5,00 1,119801 4,47 -", "2,5% für Währungsumrechnung 0,11 -",
          "Neuer Saldo 4,58 -"])
L = r["lines"]
check(len(L) == 2, f"two positions: the purchase and the conversion fee {pos(r)}")
check(L and L[0]["amount"] == Decimal("4.47") and L[0]["kind"] == "purchase" and L[0]["orig_amount"] == Decimal("5.00")
      and L[0]["orig_currency"] == "USD" and L[0]["day"] == "2026-10-18" and L[0]["booked"] == "2026-10-19", f"the purchase {L[:1]}")
check(L and L[0]["merchant"] == "ELEVENLABS.IO, NEW YORK", f"the rate is no part of the merchant {L[:1]}")
check(len(L) > 1 and L[1]["amount"] == Decimal("0.11") and L[1]["kind"] == "fee" and L[1]["merchant"] == "2,5% für Währungsumrechnung"
      and L[1]["day"] == "2026-10-18", f"the conversion fee is a fee position {L[1:]}")
check(r["total"] == Decimal("4.58") and sum(x["amount"] for x in L) == r["total"], f"the sum fits the printed total {r['total']}")
# the same without a printed total: still two positions
r = read(["18.10.26 19.10.26 ELEVENLABS.IO, NEW YORK USD 5,00 1,119801 4,47 -", "2,5% für Währungsumrechnung 0,11 -"])
check(pos(r) == [("ELEVENLABS.IO, NEW YORK", "4.47", "purchase"), ("2,5% für Währungsumrechnung", "0.11", "fee")], f"no total: the same {pos(r)}")

# ---- the other names of the conversion fee; the rate line is no position
for fee in ("Umrechnungsentgelt 1,75% 0,35-", "Umrechnungsgebühr 0,35-", "Umrechnungsaufschlag 0,35-", "Fremdwährungszuschlag 0,35-",
            "Fremdwaehrungszuschlag 0,35-", "Auslandszuschlag 0,35-", "Waehrungsumrechnung 1,75 % 0,35-"):
    r = read(["03.10. 04.10. Cloud Beispiel Inc USD 20,00 18,40-", "Umrechnungskurs 1,12", fee, "Neuer Saldo 18,75-"])
    check(pos(r) == [("Cloud Beispiel Inc", "18.40", "purchase"), (fee.rsplit(" ", 1)[0], "0.35", "fee")], f"{fee!r}: a fee position {pos(r)}")

# ---- an unknown line with an amount of its own is never dropped (rollback: dropped before)
r = read(["05.10. 05.10. Hotel Beispiel Lissabon 120,00-", "Kurtaxe Beispiel 4,00-", "Neuer Saldo 124,00-"])
check(pos(r) == [("Hotel Beispiel Lissabon", "120.00", "purchase"), ("Kurtaxe Beispiel", "4.00", "purchase")],
      f"an unknown line with its own amount is a position (asks for a receipt) {pos(r)}")
r = read(["05.10. 05.10. Hotel Beispiel Lissabon 120,00-", "Kurtaxe Beispiel 4,00-"])
check(len(r["lines"]) == 2, f"without a total too {pos(r)}")
# the printed total fits without it: a footer amount, no position
r = read(["05.10. 05.10. Hotel Beispiel Lissabon 120,00-", "Bonuspunkte Beispielprogramm 36,00", "Neuer Saldo 120,00-"])
check(pos(r) == [("Hotel Beispiel Lissabon", "120.00", "purchase")], f"the total fits without the line: no position {pos(r)}")
# a minimum payment and the amount once more in euro are no positions
r = read(["05.10. 05.10. Shop Beispiel USD 10,00 9,20-", "EUR 9,20", "Mindestzahlung 50,00"])
check(pos(r) == [("Shop Beispiel", "9.20", "purchase")], f"'EUR 9,20' and the minimum payment are no positions {pos(r)}")

# ---- what stayed as it was: the Auslandseinsatzentgelt, the foreign amount on a line of its own
r = read(["03.01. 04.01. Cloud Beispiel Inc 18,40-", "USD 20,00", "Auslandseinsatzentgelt 1,75% 0,32-", "Neuer Saldo 18,72-"])
L = r["lines"]
check(pos(r) == [("Cloud Beispiel Inc", "18.40", "purchase"), ("Auslandseinsatzentgelt 1,75%", "0.32", "fee")]
      and L[0]["orig_amount"] == Decimal("20.00") and L[0]["orig_currency"] == "USD", f"the foreign amount below, the old fee {pos(r)}")

print(f"p2595_c_ccread: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
