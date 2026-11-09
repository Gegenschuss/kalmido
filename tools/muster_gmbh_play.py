"""2.784.0 (#5387): plays the business year of the invented "Muster GmbH" (tests/fixtures/muster_gmbh_<year>.json) into an office
through the normal HTTP API -- shared by the test suite (tests/muster_gmbh_jahr_test.py) and the demo loader
(tools/muster_gmbh_demo.py), so the demo shows exactly the data the suite checks.

play(s, base, fx, ws, me, log) needs a logged-in requests session s whose current workspace is the organisation (ws =
"org:<id>", the documents space of its receipts) and me = the id of that person (host of the entertainment receipt). It
returns {key of the fixture: id in Kalmido} (invoices, receipts = node ids, bank lines, ...). Every step that fails raises
PlayError with the step and the answer. Python standard library + requests only."""
import time
from xml.sax.saxutils import escape

OFC = "/api/office"


class PlayError(Exception):
    pass


def pdf(lines):
    """A small PDF with a text layer, one line of text per entry (hand-written, no library)."""
    def esc(x):
        return x.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "\n".join(f"({esc(x)}) Tj T*" for x in lines)
    stream = f"BT /F1 10 Tf 12 TL 40 760 Td\n{body}\nET".encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def camt(bank, year):
    """A CAMT.053 statement of the year: every line of bank["zeilen"], purpose "<zweck> <key>", opening and closing balance."""
    def amt(v):
        return f"{abs(float(v)):.2f}"

    def ntry(z):
        cd = "CRDT" if not str(z["betrag"]).startswith("-") else "DBIT"
        who = "Dbtr" if cd == "CRDT" else "Cdtr"
        return (f'<Ntry><Amt Ccy="EUR">{amt(z["betrag"])}</Amt><CdtDbtInd>{cd}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{z["tag"]}</Dt></BookgDt>'
                f'<AcctSvcrRef>MG{z["key"]}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><{who}><Pty><Nm>{escape(z["partner"])}</Nm></Pty></{who}></RltdPties>'
                f'<RmtInf><Ustrd>{escape(z["zweck"])} {z["key"]}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')
    end = sum(round(float(z["betrag"]) * 100) for z in bank["zeilen"]) + round(float(bank["anfang"]) * 100)

    def bal(cd, v, day):
        return (f'<Bal><Tp><CdOrPrtry><Cd>{cd}</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{abs(v) / 100:.2f}</Amt>'
                f'<CdtDbtInd>{"CRDT" if v >= 0 else "DBIT"}</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>')
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
            f'<Id>MG{year}</Id><Acct><Id><IBAN>{bank["iban"]}</IBAN></Id><Ccy>EUR</Ccy></Acct>'
            + bal("OPBD", round(float(bank["anfang"]) * 100), f"{year}-01-01") + bal("CLBD", end, f"{year}-12-31")
            + "".join(ntry(z) for z in bank["zeilen"]) + "</Stmt></BkToCstmrStmt></Document>")


def play(s, base, fx, ws, me, log=print):
    ids = {}
    year = fx["jahr"]

    def go(what, r, codes=(200, 201)):
        if r.status_code not in codes:
            raise PlayError(f"{what}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def get(path):
        return go("GET " + path, s.get(base + path))

    # ---- the office: company, chart, VAT on invoicing, quarterly returns, balance sheet
    f, st = fx["firma"], fx["einstellungen"]
    go("office settings", s.put(base + OFC + "/settings", json={
        "lang": "de", "currency": "EUR", "vat_basis": st["vat_basis"], "datev_extf": {"chart": fx["kontenrahmen"]},
        "company_fields": {k: f[k] for k in ("name", "street", "zip", "city", "country", "tax_number", "register_no", "iban")}}))
    go("tax dates", s.put(base + OFC + "/tax-dates", json={"ustva": st["ustva"]}))
    go("balance sheet chosen", s.put(base + OFC + "/books/ledger/settings", json={"method": st["method"], "size": st["size"]}))
    get(OFC + "/settings/bank-accounts")  # the default bank account from the company's IBAN (first look)
    for e in fx["eroeffnung"]:
        go("opening entry " + e["text"], s.post(base + OFC + "/books/ledger/entries", json={
            "day": f"{year}-01-01", "debit": e["soll"], "credit": e["haben"], "amount": e["betrag"], "text": e["text"], "kind": "open"}))
    log("office and opening entries")

    # ---- receipts (documents space of the organisation), the device
    for b in fx["belege"]:
        r = go("upload " + b["key"], s.post(base + "/api/docs", data={"ws": ws},
                                            files={"files": (b["datei"], pdf([fx["firma"]["name"], b["kategorie"], b["datum"], b["brutto"] + " EUR"]), "application/pdf")}))
        nid = r["ids"][0]
        for _ in range(240):  # the recognition is done (a real state, not a fixed wait)
            if get(f"/api/docs/{nid}").get("state") in ("done", "failed"):
                break
            time.sleep(0.25)
        else:
            raise PlayError(f"recognition of {b['key']} never finished")
        go("amount " + b["key"], s.patch(base + f"/api/docs/{nid}", json={"amount": b["brutto"], "currency": "EUR", "date": b["datum"]}))
        rb = {"category": b["kategorie"], "vat_pct": b["ust"], "keep": True}
        if b.get("rc13b"):
            rb["rc13b"] = b["rc13b"]
        go("receipt " + b["key"], s.put(base + f"/api/docs/{nid}/receipt", json=rb))
        ids[b["key"]] = nid
    for a in fx["anlagen"]:
        ids[a["key"]] = go("device " + a["key"], s.post(base + OFC + "/equipment", json={
            "name": a["name"], "purchase_date": a["kauf"], "purchase_net": a["netto"], "life_months": a["monate"], "afa_method": "linear",
            "receipt_node_id": ids[a["beleg"]]}))["id"]
    log("receipts and the device")

    # ---- the credit card: a typed statement, its receipts matched
    k = fx["karte"]
    K = OFC + "/cards"
    cid = go("card", s.post(base + K, json={"holder_name": k["inhaber"], "last4": k["last4"]}))["id"]
    r = go("card statement", s.post(base + f"{K}/{cid}/statements", files={"file": ("karte.pdf", pdf(["Kreditkartenabrechnung", k["monat"]]), "application/pdf")},
                                     data={"month": k["monat"]}))
    sid = r["statement"]["id"]
    ids["karte"] = sid
    for z in k["zeilen"]:
        lb = {"day": z["tag"], "merchant": z["haendler"], "amount": z["betrag"]}
        if z.get("art"):
            lb["kind"] = z["art"]
        ids[z["key"]] = go("card line " + z["key"], s.post(base + f"{K}/statements/{sid}/lines", json=lb))["line"]["id"]
    go("card total", s.patch(base + f"{K}/statements/{sid}", json={"total": k["summe"]}))
    go("card statement confirmed", s.post(base + f"{K}/statements/{sid}/confirm", json={}))
    for z in k["zeilen"]:
        if z.get("beleg"):
            go("card line matched " + z["key"], s.post(base + f"{K}/lines/{ids[z['key']]}/match", json={"node_id": ids[z["beleg"]]}))
    log("credit card")

    # ---- clients, the cash box, the bank statement (its lines are matched below, in date order)
    cl = {}
    for x in fx["kunden"]:
        cl[x["key"]] = go("client " + x["name"], s.post(base + "/api/clients", json={k_: x[k_] for k_ in ("name", "street", "zip", "city", "country")}))["id"]
    kb = fx["kasse"]
    bid = go("cash box", s.post(base + OFC + "/cashbooks", json={"name": kb["name"], "opening": kb["anfang"], "opening_day": kb["anfang_tag"]}))["id"]
    ids["kasse"] = bid
    go("bank statement", s.post(base + OFC + "/bank/import", json={"text": camt(fx["bank"], year), "filename": f"konto-{year}.xml"}))
    keys = {z["key"] for z in fx["bank"]["zeilen"]}
    for t in get(OFC + "/bank/tx?state=all")["items"]:
        w = (t.get("purpose") or "").split()
        if w and w[-1] in keys:
            ids[w[-1]] = t["id"]
    miss = keys - set(ids)
    if miss:
        raise PlayError(f"bank lines not found after the import: {sorted(miss)}")

    # ---- the year in date order: invoices / credit notes / reminders (the number series wants their order), cash entries and
    # the reconciliation of the bank lines -- a credit note after the payment of its invoice, as it happened
    D = OFC + "/docs"

    def doc(kind, x):
        if kind == "invoice":
            d = go("invoice " + x["key"], s.post(base + D, json={
                "kind": "invoice", "client_id": cl[x["kunde"]], "project_title": x["titel"], "date": x["datum"], "service_from": x["datum"], "service_to": x["datum"],
                "items": [{"title": p["titel"], "qty": p["menge"], "rate": p["preis"], "tax": p["steuer"]} for p in x["positionen"]]}))
        elif kind == "credit":
            d = go("credit note " + x["key"], s.post(base + f"{D}/{ids[x['zu']]}/credit"))
            go("credit note items " + x["key"], s.put(base + f"{D}/{d['id']}/items", json={
                "items": [{"title": p["titel"], "qty": p["menge"], "rate": p["preis"], "tax": p["steuer"]} for p in x["positionen"]]}))
        else:
            d = go("reminder " + x["key"], s.post(base + D + "/reminder", json={"doc_ids": [ids[x["zu"]]], "level": x["stufe"], "fee": float(x["gebuehr"])}))
        did = d["id"]
        if get(f"{D}/{did}").get("date") != x["datum"]:
            go("date of " + x["key"], s.patch(base + f"{D}/{did}", json={"date": x["datum"]}))
        go("finalise " + x["key"], s.post(base + f"{D}/{did}/finalize"))
        ids[x["key"]] = did

    def cash(e):
        eb = {"day": e["tag"], "dir": e["richtung"], "amount": e["betrag"], "text": e["text"]}
        if e.get("kategorie"):
            eb["category"] = e["kategorie"]
        if e.get("ust") is not None:
            eb["vat_pct"] = e["ust"]
        if e.get("beleg"):
            eb["node_id"] = ids[e["beleg"]]
        if e.get("rechnung"):
            eb["invoice_id"] = ids[e["rechnung"]]
        ids[e["key"]] = go("cash entry " + e["key"], s.post(base + OFC + f"/cashbooks/{bid}/entries", json=eb)).get("id")

    def bank(z):
        a = z.get("abgleich")
        if not a:
            return  # stays open: the clearing account (an adjusting entry or the entertainment receipt clears it)
        mb = {"kind": a["art"]}
        if a["art"] == "invoice":
            mb["id"] = ids[a["rechnung"]]
        elif a["art"] == "receipt":
            mb["id"] = ids[a["beleg"]]
        elif a["art"] == "card":
            mb["id"] = ids["karte"]
        go("bank line matched " + z["key"], s.post(base + OFC + f"/bank/tx/{ids[z['key']]}/match", json=mb))

    ev = [(x["datum"], 0, lambda x=x: doc("invoice", x)) for x in fx["rechnungen"]]
    ev += [(x["datum"], 0, lambda x=x: doc("credit", x)) for x in fx["gutschriften"]]
    ev += [(x["datum"], 0, lambda x=x: doc("reminder", x)) for x in fx["mahnungen"]]
    ev += [(e["tag"], 1, lambda e=e: cash(e)) for e in kb["eintraege"]]
    ev += [(z["tag"], 2, lambda z=z: bank(z)) for z in fx["bank"]["zeilen"]]
    for _day, _o, fn in sorted(ev, key=lambda t: (t[0], t[1])):
        fn()
    log("invoices, credit note, reminder, cash box, bank reconciled")

    # ---- the paid reminder fee (on the day the money came)
    for m in fx["mahnungen"]:
        go("reminder fee paid " + m["key"], s.post(base + f"{D}/{ids[m['key']]}/fee", json={"state": "paid", "day": m["bezahlt_am"]}))

    # ---- entertainment receipt, travel expenses
    for m in fx["bewirtung"]:
        r = go("meal " + m["key"], s.post(base + OFC + "/meals", json={
            "date": m["datum"], "place_name": m["ort"], "place_address": m["adresse"], "occasion": m["anlass"], "host": {"id": me},
            "guests": m["gaeste"], "amounts": [{"kind": "food", "rate": m["satz"], "gross": m["brutto"]}]}))
        ids[m["key"]] = r["id"]
        go("meal approved " + m["key"], s.post(base + OFC + f"/meals/{r['id']}/approve"))
        go("meal paid " + m["key"], s.put(base + OFC + f"/meals/{r['id']}/payment", json={"kind": "bank", "id": ids[m["bank"]]}))
    for t in fx["reisen"]:
        ids[t["key"]] = go("trip " + t["key"], s.post(base + OFC + "/trips", json={
            "date_from": t["von"], "date_to": t["bis"], "dest": t["ziel"], "overnight": 1, "country": t["land"], "t_start": t["start"], "t_end": t["ende"],
            "items": [{"date": p["tag"], "category": p["art"], "amount": p["betrag"], "vat_pct": p["ust"]} for p in t["positionen"]]}))["id"]
    log("entertainment and travel")

    # ---- adjusting entries
    for u in fx["umbuchungen"]:
        ids[u["key"]] = go("adjusting entry " + u["key"], s.post(base + OFC + "/books/ledger/entries", json={
            "day": u["tag"], "debit": u["soll"], "credit": u["haben"], "amount": u["betrag"], "text": u["text"], "kind": "manual"}))["id"]
    log("adjusting entries")
    return ids
