#!/usr/bin/env python3
# kalmido-suite: after=p2296_a_pdfa nodata
"""2.666.0 part B (#4074 point 14): a foreign colour profile reaches littlecms only when it looks like one. On
kalmido/office/pdf.py of the source tree, no server, no container; every picture and profile is made here.
 - a real sRGB profile (588 bytes) is still parsed and converted (the picture keeps its colour)
 - a profile over PDF_ICC_MAX (1 MB), one whose header size does not match its data, one without 'acsp', one of the wrong
   colour space (RGB profile on a CMYK picture), one with an absurd tag count: littlecms is never called, the picture comes
   back as it was and still prints (pdf_image_object)
usage: p2666_b_haertung_pdf_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf_2666b", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

try:
    from PIL import Image, ImageCms
    SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
except Exception:  # noqa: BLE001  (no littlecms in this Pillow)
    SRGB = None

if not SRGB:
    print("SKIP #4074 14 colour profiles: ImageCms not available")
    sys.exit(done("p2666_b_haertung_pdf"))

CALLS = []
_orig = ImageCms.ImageCmsProfile


def _counting(*a, **kw):
    CALLS.append(1)
    return _orig(*a, **kw)


ImageCms.ImageCmsProfile = _counting  # pdf_to_srgb imports ImageCms inside the call: it sees this one


def pic(mode, icc):
    im = Image.new(mode, (4, 4), (47, 93, 138) if mode == "RGB" else (0, 0, 0, 0))
    im.info["icc_profile"] = icc
    return im


def with_size(b):
    return len(b).to_bytes(4, "big") + bytes(b[4:])


def calls(im):
    CALLS.clear()
    out = pdf.pdf_to_srgb(im)
    return len(CALLS), out


n, out = calls(pic("RGB", SRGB))
check(n == 1 and out.mode == "RGB" and max(abs(a - b) for a, b in zip(out.getpixel((0, 0)), (47, 93, 138))) <= 2,
      f"#4074 14: a real sRGB profile is still parsed and converted ({n} calls, {out.getpixel((0, 0))})")

big = with_size(SRGB + b"\0" * (pdf.PDF_ICC_MAX + 1 - len(SRGB)))
cases = {
    "over 1 MB": ("RGB", big),
    "header size does not match": ("RGB", SRGB + b"\0" * 16),
    "no acsp signature": ("RGB", SRGB[:36] + b"xxxx" + SRGB[40:]),
    "RGB profile on a CMYK picture": ("CMYK", SRGB),
    "tag count beyond the data": ("RGB", SRGB[:128] + (10_000).to_bytes(4, "big") + SRGB[132:]),
    "garbage": ("CMYK", b"not a profile"),
}
for what, (mode, icc) in cases.items():
    im = pic(mode, icc)
    n, out = calls(im)
    check(n == 0 and out is im, f"#4074 14: {what}: littlecms not called, the picture as it was ({n} calls)")

b = io.BytesIO()
Image.new("RGB", (60, 20), (47, 93, 138)).save(b, "PNG", icc_profile=big)
CALLS.clear()
obj = pdf.pdf_image_object(b.getvalue())
check(obj and obj[0] == 60 and obj[1] == 20 and not CALLS, f"#4074 14: a logo with a too large profile still prints, unparsed ({len(CALLS)} calls)")

ImageCms.ImageCmsProfile = _orig
sys.exit(done("p2666_b_haertung_pdf"))
