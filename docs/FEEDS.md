# Feeds

*Since 2.85.0.* A simple feed reader, part of the area **Home**: follow blogs and news sites and read their new articles
in one list. Switch it on under *Settings > Modules > Home > Feeds* (off by default).

## Following a feed

- Open **Feeds** (a tab of the area Home) and paste the address of a feed (RSS 2.0, Atom or RSS 1.0), e.g.
  `https://example.com/feed`, then tap **Follow**. The server fetches the feed once right away; if that does not work,
  it says why (no feed at this address, not reachable, too large, a private address).
- Menu **…** > *Import OPML file* takes over the feeds of another reader (at most 100 feeds per person); *Export OPML
  file* downloads yours.
- *Manage feeds* (below the articles) lists your feeds with the last fetch or the last error; the bin unfollows a feed
  (undo brings it back with its articles).

## Reading

- The newest articles come first: title, feed, date and a short summary as plain text. Unread articles have a coloured
  bar. Choose one feed or *Unread only* at the top.
- **Open** opens the article on its website in a new tab and marks it read; **Read** / **Unread** marks it by hand;
  *Mark all read* marks every unread article (of the chosen feed), one undo step brings them back.
- **Read later** saves the article as a task (title + link) in your list *Read later*. A second tap does not add it again.
- *Home & life* shows a card **Feeds** with the number of unread articles.

## How it works

- Your server fetches each feed about once an hour (a feed that fails ten times in a row only once a day) and keeps the
  articles for 30 days; tasks you saved stay.
- Feeds are private: they belong to your account, are never shared and never visible to agents (no REST API, no MCP
  tool in 2.85.0). There are no notifications for new articles.
- Privacy and safety: Kalmido loads no pictures and no scripts of the feeds (no tracking); only the text is kept. The
  server only fetches public addresses (an admin can allow internal hosts under *Settings > Administration > Advanced*,
  like for calendar subscriptions), at most 2 MB per feed, and refuses feeds with a DTD.
