# Bookmarks

*Since 2.97.0.* Collect links with a preview, tags and a note, and find them again with the search. Bookmarks are part of
the module **Read later** (*Settings > Modules > Home > Read later*, off by default) and a tab of the area **Home**.

## Saving a link

- Open **Bookmarks** and paste a link (`https://…`; a bare `example.com/page` gets `https://`), then tap **Save**.
- **From another app (phone):** share a link to Kalmido and choose **Save as bookmark** (next to *New task*).
- **From the browser (computer):** menu **…** > *Bookmark button for the browser* gives you a button to drag to your
  bookmarks bar. On any page it opens a small Kalmido window with the page; **Save** keeps it and shows it for tags and a
  note. It uses your normal sign-in and runs no code of ours on the page.
- The same link is not saved twice: saving it again (also with tracking parameters such as `utm_source`) shows the one you
  already have.
- With organisations: a bookmark is saved in the workspace you are looking at (in *All workspaces*: your private space).

## The preview and the reading text

- After saving, your server fetches the page once in the background: title, description, site name and preview picture
  (OpenGraph / Twitter tags, else the page title), and the main text of the page as plain text (*Reading text* in the
  details), so the link stays readable later. *Reload preview* in the details fetches it again; a title you changed stays.
- When the page cannot be fetched, the bookmark stays with its link as the title and the details say why.
- Safety: the server only fetches public addresses (redirects are checked the same way; internal hosts only through the
  server's own setting `KALMIDO_BOOKMARK_ALLOW_HOSTS`, not the calendar allow-list), at most 1 MB of HTML, only web pages.
  Previews are fetched one after the other and per person at a limited rate; beyond it they follow a little later.
  The picture is stored as the app's own copy (PNG, JPEG, WebP or GIF up to 1 MB, never SVG), sealed like attachments;
  your browser never loads anything from the bookmarked site. No scripts or HTML of the page are kept.

## Ordering and finding

- **Cards** (picture, title, site, description) or a **list** (the switch next to the search, remembered per device).
- **Search** looks in the title, description, note, link, tags and the reading text (all words must match).
- **Tags** (in the details, separated by commas): the tags of the shown bookmarks appear above the list; a tap filters.
- States: *Unread*, *Read*, *Archived*. Opening the link marks a bookmark read; the check mark and the archive button on
  a card change it by hand. Archived bookmarks are hidden unless you choose *Archived* or *All*.
- Every change (save, edit, archive, delete, move) is one undo step; a deleted bookmark can be brought back for 7 days.

## Workspaces

- A private bookmark is only yours. A bookmark of an organisation is visible to all its members; changing, deleting or
  moving it is for the person who saved it and the organisation's admins.
- *Move to another workspace…* in the details moves a bookmark between your private space and an organisation (both
  ways, with a check first). A link you already saved in the target stays where it is.
- Bookmarks are for people only: agents and API tokens have no access in 2.97.0.

## Karakeep

With a Karakeep connection (*Home & life* > *Read later* > *Karakeep…*) links you save in Karakeep come in as private
bookmarks (with Karakeep's title, description and picture when it has them); notes and files from Karakeep stay tasks of
your *Read later* list. Archiving a bookmark that came from Karakeep archives it there at the next fetch, like a ticked task.
A bookmark comes in once: deleting it in Kalmido does not bring it back.
