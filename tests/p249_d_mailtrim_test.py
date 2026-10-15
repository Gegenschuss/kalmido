"""2.49.0 (#971): md_trim_forward -- forwarded mails of the common clients shrink to one header line; no server needed."""
import importlib.util
import os
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido", "integrations", "mailtrim.py")
sp = importlib.util.spec_from_file_location("mailtrim", p)
mt = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mt)
trim = mt.md_trim_forward
fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


GMAIL = """Please book this, thanks.

---------- Forwarded message ---------
From: Jane Doe <jane@example.com>
Date: Mon, Oct 5, 2026 at 9:12 AM
Subject: Dentist on Friday
To: <me@example.com>

Hi,

your appointment is on Friday at 10:00.

> older quoted text
> more

On Fri, Oct 2, 2026 at 8:00 AM Bob <bob@example.com> wrote:
> Is Friday fine?

Best regards
Jane Doe
Example Dental
"""
t = trim(GMAIL)
check(t.startswith("Please book this, thanks.\n\nFrom Jane Doe, Mon, Oct 5, 2026 at 9:12 AM\n\nHi,"), "gmail: own text, one line, body: " + repr(t[:120]))
check("your appointment is on Friday at 10:00." in t and "older quoted" not in t and "wrote:" not in t and "Example Dental" not in t and "Forwarded" not in t, "gmail: quotes and signature cut")
check("To:" not in t and "Subject" not in t, "gmail: header lines gone")

OUTLOOK_EN = """FYI

________________________________
From: Doe, Jane <jane@example.com>
Sent: Monday, October 5, 2026 9:12 AM
To: Me <me@example.com>
Cc: Bob <bob@example.com>
Subject: RE: Budget

Numbers attached.

Kind regards
Jane

CONFIDENTIAL: This e-mail may contain privileged information. If you are not the intended recipient, delete it.

________________________________
From: Bob <bob@example.com>
Sent: Friday, October 2, 2026 8:00 AM
To: Doe, Jane <jane@example.com>
Subject: Budget

Older mail.
"""
t = trim(OUTLOOK_EN)
check(t == "FYI\n\nFrom Doe, Jane, Monday, October 5, 2026 9:12 AM\n\nNumbers attached.", "outlook en: " + repr(t))

OUTLOOK_DE = """Von: Erika Muster [mailto:erika@example.com]
Gesendet: Montag, 5. Oktober 2026 09:12
An: Ich <ich@example.com>
Betreff: WG: Angebot

Anbei das Angebot.

Mit freundlichen Grüßen
Erika Muster
Musterfirma GmbH
Diese E-Mail enthält vertrauliche Informationen.
"""
t = trim(OUTLOOK_DE)
check(t == "Von Erika Muster, Montag, 5. Oktober 2026 09:12\n\nAnbei das Angebot.", "outlook de, no own text: " + repr(t))

APPLE = """Bitte ansehen.

Anfang der weitergeleiteten Nachricht:

Von: Max Beispiel <max@example.com>
Betreff: Termin
Datum: 5. Oktober 2026 um 09:12:00 MESZ
An: ich@example.com

Passt Donnerstag?

Am 2. Oktober 2026 um 08:00 schrieb Ich <ich@example.com>:

> Wann hast du Zeit?

Von meinem iPhone gesendet
"""
t = trim(APPLE)
check(t == "Bitte ansehen.\n\nVon Max Beispiel, 5. Oktober 2026 um 09:12:00 MESZ\n\nPasst Donnerstag?", "apple de: " + repr(t))

APPLE_EN = """Begin forwarded message:

From: Max Example <max@example.com>
Subject: Meeting
Date: October 5, 2026 at 9:12:00 AM GMT+2
To: me@example.com

Does Thursday work?

On Oct 2, 2026, at 8:00 AM, Me <me@example.com> wrote:

> When are you free?
-- 
Max
"""
t = trim(APPLE_EN)
check(t == "From Max Example, October 5, 2026 at 9:12:00 AM GMT+2\n\nDoes Thursday work?", "apple en: " + repr(t))

TB = """-------- Weitergeleitete Nachricht --------
Betreff: 	Rechnung
Datum: 	Mon, 5 Oct 2026 09:12:00 +0200
Von: 	Rita Test <rita@example.com>
An: 	ich@example.com

Hallo,
die Rechnung steht bereit.

Viele Grüße
Rita
"""
t = trim(TB)
check(t == "Von Rita Test, Mon, 5 Oct 2026 09:12:00 +0200\n\nHallo,\ndie Rechnung steht bereit.", "thunderbird de (subject first): " + repr(t))

check(trim("Just a plain mail.\n\nBest regards\nMe") == "Just a plain mail.\n\nBest regards\nMe", "no forward header: unchanged")
check(trim("") == "" and trim(None) is None, "empty input")
LONG = "From: A <a@example.com>\nnot a header block\nbody"
check(trim(LONG) == LONG, "a lone From: line is no forward header")

# wrapped header value and a quoted-only header
WRAP = """---------- Forwarded message ----------
From: Very Long Name
 <vl@example.com>
Date: Tue, Oct 6, 2026
Subject: x

Body here.
"""
t = trim(WRAP)
check(t == "From Very Long Name, Tue, Oct 6, 2026\n\nBody here.", "wrapped header value: " + repr(t))

print("FAILED: %d" % len(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
