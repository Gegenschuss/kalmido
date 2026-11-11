"""#5227: a picture of a knowledge page keeps its place while it loads -- the width and height in pixels of a picture
attached to a page (wiki/wikiatt.py wka_store reads them from the header on upload; SVG from its width / height or viewBox).
The web client puts them on the <img> (the browser reserves the box from the ratio before the bytes arrive); NULL = not
known (files from before, a picture whose header tells nothing): the client shows the fixed 4:3 placeholder box instead.
Older versions ignore the columns."""
MIGRATIONS = [
    ("wiki_files", "img_w", "ALTER TABLE wiki_files ADD COLUMN IF NOT EXISTS img_w INTEGER"),
    ("wiki_files", "img_h", "ALTER TABLE wiki_files ADD COLUMN IF NOT EXISTS img_h INTEGER"),
]
