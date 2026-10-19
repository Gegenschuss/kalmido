#!/usr/bin/env python3
"""The type check's guard for new client files (2.102.0, #1995; see docs/ARCHITECTURE.md "Type check").

jsconfig.json makes every static/js/*.js part of one program for tsc (CI: "Type check"), but tsc only checks files whose
FIRST line is `// @ts-check`. The files that existed when the check came stand in BASE below; every other (new) file must
start with `// @ts-check`, so new code is typed from its first day. A BASE file may switch it on any time (then remove its
name here: the list only shrinks); a BASE name without its file fails too.

usage: python3 tools/check_tscheck.py     exit code 1 on a new file without // @ts-check or a stale BASE entry
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the client files without // @ts-check on 2.96.2 (+ 2.102.0); remove a name once its file starts with // @ts-check
BASE = {
    "ablage.js", "absence.js", "account.js", "acctset.js", "agentchat.js", "agentplan.js", "agents.js", "agentsetup.js",
    "agentview.js", "apptbook.js", "areas.js", "assistant.js", "attachments.js", "backclose.js", "basket.js",
    "budget.js", "caldrag.js", "calendar.js", "calevents.js", "calview.js", "cfnew.js", "chat.js", "chatbase.js",
    "chatplus.js", "chatwin.js", "chatwins.js", "choicecard.js", "cleanup.js", "clientpage.js", "clients.js",
    "collab.js", "contacts.js", "contractprop.js", "core.js", "countries.js", "cryptscope.js", "ctlinks.js",
    "custview.js", "dashboard.js", "davwrite.js", "dayplan.js", "depchain.js", "detail.js", "dialogs.js", "discover.js",
    "dispo.js", "dlgmove.js", "dnd.js", "docpreview.js", "docs.js", "dragmulti.js", "dupprop.js", "e2e.js", "envs.js",
    "events.js", "family.js", "favorites.js", "favtiles.js", "feeds.js", "filetext.js", "formguard.js", "formula.js",
    "git.js", "habits.js", "hubmail.js", "icons.js", "importprop.js", "integrations.js", "jobchat.js", "life.js",
    "listadmin.js", "listcolor.js", "liste2e.js", "liste2echan.js", "liste2efile.js", "liste2eui.js", "listedit.js",
    "listhead.js", "liveparts.js", "lyopts.js", "lyprop.js", "lysets.js", "main.js", "mdtitle.js", "meetprop.js",
    "mindmap.js", "mineorder.js", "miniwin.js", "move.js", "msvview.js", "multiedit.js", "multilist.js", "multisel.js",
    "newsletter.js", "notelock.js", "notesall.js", "office.js", "office_agreements.js", "office_assets.js",
    "office_bank.js", "office_books.js", "office_cashflow.js", "office_datev.js", "office_docs.js", "office_doctpl.js",
    "office_import.js", "office_kpi.js", "office_leads.js", "office_logbook.js", "office_packs.js", "office_parts.js",
    "office_pipeline.js", "office_recurring.js", "office_sheet.js", "office_subs.js", "office_taxdates.js",
    "office_travel.js", "officeagents.js", "orgcrypt.js", "orgexport.js", "orgvis.js", "palette.js", "paperless.js",
    "pdfview.js", "photometa.js", "pinboard.js", "playbook.js", "points.js", "popovers.js", "portal.js", "projects.js",
    "projtime.js", "propkinds2.js", "pubvideo.js", "purposemods.js", "quickadd.js", "receipts.js", "refs.js",
    "related.js", "reloadguard.js", "render.js", "review.js", "richcopy.js", "roadmap.js", "rowsym.js", "rules.js",
    "sbnav.js", "secdrag.js", "servers.js", "setcore.js", "settings.js", "sharedlg.js", "sharews.js", "sheetdrag.js",
    "sheetgrid.js", "sheetmotion.js", "sheets.js", "sheets2.js", "sheetsio.js", "sidebar.js", "signoff.js",
    "spacemove.js", "sprints.js", "stats.js", "supporter.js", "tablecells.js", "tagsview.js", "tapdone.js",
    "taskbell.js", "templates.js", "time.js", "timeline.js", "undo.js", "videorev.js", "views.js", "vlist.js",
    "widgets.js", "wiki.js", "wikie2e.js", "wip.js", "workspace.js", "wscolor.js",
}


def main():
    err, checked = [], []
    files = sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js")))
    names = {os.path.basename(p) for p in files}
    for p in files:
        n = os.path.basename(p)
        with open(p, encoding="utf-8") as f:
            on = f.readline().strip() == "// @ts-check"
        if on:
            checked.append(n)
            if n in BASE:
                err.append(f"tools/check_tscheck.py BASE: {n} starts with // @ts-check now, remove it from BASE")
        elif n not in BASE:
            err.append(f"static/js/{n}: a new client file starts with // @ts-check (first line; the type check covers it then)")
    for n in sorted(BASE - names):
        err.append(f"tools/check_tscheck.py BASE: {n} does not exist any more, remove it")
    print(f"check_tscheck: {len(files)} client files, {len(checked)} with // @ts-check ({', '.join(checked)}), {len(err)} error(s)")
    for e in err:
        print("check_tscheck:", e)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
