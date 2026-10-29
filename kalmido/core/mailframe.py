"""2.420.0 B (#3499): the one HTML frame of every Kalmido mail (invitation, findability, appointment booking, portal,
event invitation, security, notification and daily mails). Table layout as mail clients need it, a 560 px card, a dark
head bar with the brand (the logo only where the mail embeds it as cid:logo), petrol buttons, inline CSS only.
The text part of a mail is built by its caller as before; this frame only shapes the HTML part.

Every plain string is escaped; a part that is already safe HTML is passed as Safe(...) (built by the caller with
html.escape on every user value). It sits in core so that every layer may use it at module level
(integrations/mail.py re-exports it)."""
import html

from .config import APP_NAME

MAIL_ACC, MAIL_INK, MAIL_BG, MAIL_CARD, MAIL_MUTED = "#1a7f8e", "#14272b", "#eef5f6", "#ffffff", "#5f6b6e"
MAIL_BAR = "#16141f"
MAIL_FONT = "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"


class Safe(str):
    """A piece of HTML the caller already escaped (mail_html puts it in as it is)."""


def _part(x):
    return str(x) if isinstance(x, Safe) else html.escape(str(x)).replace("\n", "<br>")


def _http(url):
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


def mail_html(subject, lines, button=None, url=None, foot=None, head=None, lang="", brand=None, logo=False, note=None, after=()):
    """The HTML part of a mail: head = the heading (h1), lines = the paragraphs (str escaped, Safe as it is, empty ones
    skipped), button + url = one button (only http(s) links, else none), note = a small line under the button, after =
    blocks after the button, foot = the small print at the bottom. brand = the name in the head bar (APP_NAME),
    logo = the mail embeds the logo as cid:logo."""
    e = html.escape
    paras = "".join(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.55">{_part(x)}</p>' if not isinstance(x, Safe)
                    else f'<div style="margin:0 0 16px">{x}</div>' for x in lines if x)
    h1 = f'<h1 style="margin:0 0 12px;font-size:20px;line-height:1.3">{_part(head)}</h1>' if head else ""
    link = _http(url)
    btn = ""
    if link and button:
        btn = (f'<tr><td style="padding:8px 32px 8px" align="left"><a href="{e(link, quote=True)}" style="display:inline-block;'
               f'background:{MAIL_ACC};color:#ffffff;text-decoration:none;font-weight:600;font-size:16px;padding:13px 26px;'
               f'border-radius:12px">{e(str(button))}</a>'
               + (f'<p style="margin:12px 0 0;font-size:13px;line-height:1.5;color:{MAIL_MUTED}">{_part(note)}</p>' if note else "")
               + "</td></tr>")
    elif note:
        btn = f'<tr><td style="padding:0 32px 8px"><p style="margin:0;font-size:13px;line-height:1.5;color:{MAIL_MUTED}">{_part(note)}</p></td></tr>'
    aft = "".join(f'<tr><td style="padding:16px 32px 8px;font-size:15px;line-height:1.6">{_part(x)}</td></tr>' for x in after if x)
    ft = (f'<tr><td style="border-top:1px solid #e3eaeb;padding:18px 32px;font-size:13px;line-height:1.5;color:{MAIL_MUTED}">'
          f'{_part(foot)}</td></tr>') if foot else ""
    img = ('<td><img src="cid:logo" width="48" height="48" alt="" style="display:block;border-radius:12px"></td>'
           '<td style="padding-left:14px;') if logo else '<td style="'
    lg = f' lang="{e(str(lang), quote=True)}"' if lang else ""
    return f"""<!doctype html><html{lg}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light"><title>{e(str(subject or ""))}</title></head>
<body style="margin:0;padding:0;background:{MAIL_BG};font-family:{MAIL_FONT};color:{MAIL_INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{MAIL_BG};padding:32px 12px"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:{MAIL_CARD};border-radius:18px;overflow:hidden">
<tr><td style="background:{MAIL_BAR};padding:24px 32px" align="left"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
{img}color:#ffffff;font-size:20px;font-weight:700;letter-spacing:.2px">{e(str(brand or APP_NAME))}</td></tr></table></td></tr>
<tr><td style="padding:28px 32px 0">{h1}{paras}</td></tr>
{btn}{aft}{ft}
</table></td></tr></table></body></html>"""
