"""Profile pictures and list icons (presets or own images, re-encoded, served with login)."""
import contextlib
import io
import os
import re

from ..core.config import ATT_DIR
from ..core.i18n import tr


# ---- 1.9.0: profile pictures. A preset (funny animal pictures, static SVGs) or an own photo: the client crops it square, the
# server decodes it (Pillow, pixel limit), turns it upright, resizes it to AVATAR_PX and stores a fresh JPEG (no EXIF /
# GPS or other metadata survives) below ATT_DIR/avatars (so backups include it). Served with login to the user
# themselves, admins and the people who share a list with them; the file name carries a random token (new picture =
# new URL, cached for good). Without a picture everybody sees the initials, as before.
AVATAR_PRESETS = ("coffee", "headphones", "camera", "sleepy", "laptop", "plant", "robot", "shades", "party", "glasses")
AVATAR_PX = 256
AVATAR_MAX_MB = 8
AVATAR_DIR = os.path.join(ATT_DIR, "avatars")


def avatar_url(u):
    try:
        a = u["avatar"] or ""
    except (IndexError, KeyError):
        return ""
    if a.startswith("p:") and a[2:] in AVATAR_PRESETS:
        return f"/static/avatars/{a[2:]}.svg"
    if a.startswith("u:") and re.fullmatch(r"[A-Za-z0-9_-]{8,40}", a[2:]):
        return f"/api/avatar/{u['id']}/{a[2:]}.jpg"
    return ""


def avatar_path(uid, tok):
    return os.path.join(AVATAR_DIR, f"u{int(uid)}-{tok}.jpg")


def avatar_drop_file(uid, a):
    if a and a.startswith("u:") and re.fullmatch(r"[A-Za-z0-9_-]{8,40}", a[2:]):
        with contextlib.suppress(OSError):
            os.remove(avatar_path(uid, a[2:]))


def avatar_map(c, uid):
    """{user id: picture URL} of me and everybody sharing a list with me (only users that have a picture)."""
    from ..core.access import vis_sql
    rows = c.execute(f"""SELECT id, avatar FROM users WHERE avatar IS NOT NULL AND avatar!='' AND (id=? OR id IN
                         (SELECT owner_id FROM lists WHERE id IN {vis_sql()}) OR id IN
                         (SELECT user_id FROM list_members WHERE list_id IN {vis_sql()}))""", (uid, uid, uid, uid, uid)).fetchall()
    return {str(r["id"]): avatar_url(r) for r in rows if avatar_url(r)}


def avatar_process(raw):
    """Upload bytes -> square JPEG bytes (AVATAR_PX, no metadata). BadInput for anything that is not a picture."""
    from ..personal.timetrack import BadInput
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise BadInput(tr("Photos are not available on this server"))
    Image.MAX_IMAGE_PIXELS = 30_000_000
    try:
        im = Image.open(io.BytesIO(raw))  # reads the header only
        if im.format not in ("JPEG", "PNG", "WEBP", "GIF", "BMP"):
            raise BadInput(tr("Please choose a JPEG, PNG or WebP picture"))
        if im.width * im.height > 60_000_000:  # the browser sends 512 px; this only stops huge direct uploads (memory)
            raise BadInput(tr("This picture cannot be read"))
        if im.format == "JPEG":
            im.draft("RGB", (AVATAR_PX * 2, AVATAR_PX * 2))  # decode big photos at a reduced scale (fast, little memory)
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
        im = ImageOps.fit(im, (AVATAR_PX, AVATAR_PX), method=Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=86, optimize=True)  # a new file: no EXIF, GPS or ICC data carried over
        return out.getvalue()
    except BadInput:
        raise
    except Exception:  # noqa: BLE001  (decompression bomb, truncated, unknown format ...)
        raise BadInput(tr("This picture cannot be read"))


# ---- 2.0.2: own list icons (same technique as the profile pictures): a preset (the profile pictures or the app icon) or an
# own picture, cropped square in the browser, re-encoded here (PNG, LIST_ICON_PX, transparency kept, no metadata) below
# ATT_DIR/listicons (in backups). Served to everybody who sees the list; new picture = new token = new URL.
LIST_ICON_PRESETS = ("kalmido",) + AVATAR_PRESETS
LIST_ICON_PX = 128
LIST_ICON_DIR = os.path.join(ATT_DIR, "listicons")


def list_icon_url(r):
    try:
        a = r["icon"] or ""
    except (IndexError, KeyError):
        return ""
    if a == "p:kalmido":
        return "/static/icon.svg"
    if a.startswith("p:") and a[2:] in AVATAR_PRESETS:
        return f"/static/avatars/{a[2:]}.svg"
    if a.startswith("u:") and re.fullmatch(r"[A-Za-z0-9_-]{8,40}", a[2:]):
        return f"/api/list-icon/{r['id']}/{a[2:]}.png"
    return ""


def list_icon_path(lid, tok):
    return os.path.join(LIST_ICON_DIR, f"l{int(lid)}-{tok}.png")


def list_icon_drop_file(lid, a):
    if a and a.startswith("u:") and re.fullmatch(r"[A-Za-z0-9_-]{8,40}", a[2:]):
        with contextlib.suppress(OSError):
            os.remove(list_icon_path(lid, a[2:]))


def list_icon_process(raw):
    """Upload bytes -> square PNG bytes (LIST_ICON_PX, alpha kept, no metadata). BadInput for anything that is not a picture."""
    from ..personal.timetrack import BadInput
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise BadInput(tr("Photos are not available on this server"))
    Image.MAX_IMAGE_PIXELS = 30_000_000
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("JPEG", "PNG", "WEBP", "GIF", "BMP"):
            raise BadInput(tr("Please choose a JPEG, PNG or WebP picture"))
        if im.width * im.height > 60_000_000:
            raise BadInput(tr("This picture cannot be read"))
        if im.format == "JPEG":
            im.draft("RGB", (LIST_ICON_PX * 2, LIST_ICON_PX * 2))
        im.load()
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA")
        im = ImageOps.fit(im, (LIST_ICON_PX, LIST_ICON_PX), method=Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)  # a new file: no EXIF, GPS, text chunks or ICC data carried over
        return out.getvalue()
    except BadInput:
        raise
    except Exception:  # noqa: BLE001
        raise BadInput(tr("This picture cannot be read"))
