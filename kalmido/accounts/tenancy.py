"""2.30.0 (#1036): the boundary between workspaces beyond lists -- calendars and address books get their workspace once
(ws_migrate_objs), and a nightly boundary check counts every membership that crosses it (boundary_check): people in an
organisation's list / calendar / address book who are not its members (directly or through a group), agents in an object of
another workspace, owners outside the organisation of their object, agents of an organisation their owner left. A finding
is an admin alert (kind security, ids and counts only, once per new set of findings); the count is in GET /api/admin/orgs.
2.36.2 (#1142): memberships in an organisation's object of people outside it are removed by the nightly run (boundary_repair)."""
import hashlib
import json
import os

from ..core.i18n import N_
from ..core.db import gset, gsetting, iso, local_now, now_utc
from ..accounts.orgs import PRIVATE_FOLDER_RE, has_workspaces

# when the check runs: once a day at this local hour or later; KALMIDO_TENANT_CHECK=always = at every watchdog tick (tests)
TENANT_CHECK_HOUR = int(os.environ.get("KALMIDO_TENANT_CHECK_HOUR", "3") or 3)
TENANT_CHECK_ENV = os.environ.get("KALMIDO_TENANT_CHECK", "").strip().lower()
TENANT_SAMPLE = 20

# kind -> (what it counts, SQL returning (object id, user id)). Every row is one membership across the boundary.
# Persons: an organisation's object (org_id set) for somebody who is not in org_members of that organisation. Agents: the
# agent's workspace (agents.org_id, NULL = private) differs from the object's. Rows that only come from a group share
# (list_members.grole set, no own role) are counted as "group".
_PERSON = "u.kind!='agent' AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id={o}.org_id AND om.user_id={m}.user_id)"
CHECKS = {
    "list_person": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN users u ON u.id=m.user_id "
                    "WHERE l.org_id IS NOT NULL AND NOT (m.grole IS NOT NULL AND m.own_role IS NULL) AND " + _PERSON.format(o="l", m="m")),
    "group": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN users u ON u.id=m.user_id "
              "WHERE l.org_id IS NOT NULL AND m.grole IS NOT NULL AND m.own_role IS NULL AND " + _PERSON.format(o="l", m="m")
              + " AND EXISTS (SELECT 1 FROM group_members gm WHERE gm.user_id=m.user_id)"),
    "list_agent": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN agents a ON a.user_id=m.user_id "
                   "WHERE COALESCE(a.org_id,0)!=COALESCE(l.org_id,0) AND NOT (a.org_id IS NULL AND l.org_id IS NOT NULL)"),
    # 2.37.0 (#1150, K2-3): a private agent (no workspace) in an organisation's list -- row-level security hides the list
    # from it; reported on its own (assign the agent to a workspace), never changed
    "list_agent_private": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN agents a "
                           "ON a.user_id=m.user_id WHERE a.org_id IS NULL AND l.org_id IS NOT NULL"),
    "list_owner": ("SELECT l.id, l.owner_id FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.org_id IS NOT NULL AND u.kind!='agent' "
                   "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=l.owner_id)"),
    "cal_person": ("SELECT m.cal_id, m.user_id FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id JOIN users u ON u.id=m.user_id "
                   "WHERE k.org_id IS NOT NULL AND " + _PERSON.format(o="k", m="m")),
    "cal_agent": ("SELECT m.cal_id, m.user_id FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id JOIN agents a ON a.user_id=m.user_id "
                  "WHERE COALESCE(a.org_id,0)!=COALESCE(k.org_id,0)"),
    "cal_owner": ("SELECT k.id, k.owner_id FROM ev_cals k JOIN users u ON u.id=k.owner_id WHERE k.org_id IS NOT NULL AND u.kind!='agent' "
                  "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=k.org_id AND om.user_id=k.owner_id)"),
    # 2.87.0 (#1983): a person invited to an event of an organisation's calendar who is not (any more) its member (the read
    # layer ignores the invitation: events/model.py ev_att_ok; boundary_repair takes it out), an agent of another workspace
    # invited there (counted only, like cal_agent)
    "att_person": ("SELECT a.event_id, a.user_id FROM event_attendees a JOIN events e ON e.id=a.event_id JOIN ev_cals k ON k.id=e.cal_id "
                   "JOIN users u ON u.id=a.user_id WHERE k.org_id IS NOT NULL AND e.deleted_at IS NULL AND " + _PERSON.format(o="k", m="a")),
    "att_agent": ("SELECT a.event_id, a.user_id FROM event_attendees a JOIN events e ON e.id=a.event_id JOIN ev_cals k ON k.id=e.cal_id "
                  "JOIN agents g ON g.user_id=a.user_id WHERE k.org_id IS NOT NULL AND e.deleted_at IS NULL AND g.org_id IS DISTINCT FROM k.org_id"),
    "book_person": ("SELECT m.book_id, m.user_id FROM book_members m JOIN books b ON b.id=m.book_id JOIN users u ON u.id=m.user_id "
                    "WHERE b.org_id IS NOT NULL AND " + _PERSON.format(o="b", m="m")),
    "book_agent": ("SELECT m.book_id, m.user_id FROM book_members m JOIN books b ON b.id=m.book_id JOIN agents a ON a.user_id=m.user_id "
                   "WHERE COALESCE(a.org_id,0)!=COALESCE(b.org_id,0)"),
    "book_owner": ("SELECT b.id, b.owner_id FROM books b JOIN users u ON u.id=b.owner_id WHERE b.org_id IS NOT NULL AND u.kind!='agent' "
                   "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=b.org_id AND om.user_id=b.owner_id)"),
    # 2.52.0 C (#1438): an address book an organisation owns outside that organisation's workspace
    "book_org": "SELECT b.id, b.owner_id FROM books b WHERE b.owner_org_id IS NOT NULL AND b.org_id IS DISTINCT FROM b.owner_org_id",
    # 2.55.0 (#1455): a newsletter segment / member / run in another workspace than its connection
    "nl_segment": ("SELECT s.id, s.conn_id FROM nl_segments s JOIN nl_conns n ON n.id=s.conn_id WHERE s.org_id IS DISTINCT FROM n.org_id"),
    "nl_member": ("SELECT m.seg_id, s.conn_id FROM nl_members m JOIN nl_segments s ON s.id=m.seg_id WHERE m.org_id IS DISTINCT FROM s.org_id"),
    "nl_run": ("SELECT r.id, r.conn_id FROM nl_runs r JOIN nl_conns n ON n.id=r.conn_id WHERE r.org_id IS DISTINCT FROM n.org_id"),
    # 2.59.0 B (#1375): a task's text vector in another workspace / list than the task (the embedding worker drops such rows,
    # tasks/related.py emb_cleanup; reported when the worker is off)
    "task_vector": ("SELECT v.task_id, v.org_id FROM task_vectors v JOIN tasks t ON t.id=v.task_id JOIN lists l ON l.id=t.list_id "
                    "WHERE v.org_id IS DISTINCT FROM l.org_id OR v.list_id IS DISTINCT FROM t.list_id"),
    # 2.63.0 B (#1513): a customer report in another workspace than its list, or bound to a client of another workspace
    "portal_ticket": ("SELECT p.id, p.list_id FROM portal_tickets p JOIN lists l ON l.id=p.list_id WHERE p.org_id IS DISTINCT FROM l.org_id "
                      "OR (p.org_id IS NULL AND p.owner_id IS DISTINCT FROM l.owner_id)"),
    # 2.81.0 (#1856): a file's recognised text kept for another workspace than its file's (task / project file: the list's,
    # Ablage file: the node's); the queue's workspace sweep (files/textscan.py) moves it within minutes
    "file_text": ("SELECT f.id, f.ref_id FROM file_text f LEFT JOIN attachments a ON f.kind='att' AND a.id=f.att_id "
                  "LEFT JOIN tasks t ON t.id=a.task_id LEFT JOIN list_files lf ON f.kind='list' AND lf.id=f.list_file_id "
                  "LEFT JOIN lists l ON l.id=COALESCE(t.list_id, lf.list_id) LEFT JOIN fs_nodes n ON f.kind='fs' AND n.id=f.node_id "
                  "WHERE (l.id IS NOT NULL AND f.org_id IS DISTINCT FROM l.org_id) OR (n.id IS NOT NULL AND f.org_id IS DISTINCT FROM n.org_id)"),
    "portal_client": ("SELECT p.id, p.client_id FROM portal_tickets p JOIN clients k ON k.id=p.client_id WHERE k.org_id IS DISTINCT FROM p.org_id"),
    # 2.49.0 (#1106): a connection (accepted request) of an agent or a kid account -- requests are for people only
    "conn_agent": ("SELECT l.a_id, l.b_id FROM conn_links l JOIN users u ON u.id IN (l.a_id, l.b_id) "
                   "WHERE l.deleted_at IS NULL AND (u.kind!='user' OR u.kid!=0)"),
    # 2.50.0 B (#1196): a deal of the sales pipeline bound to a client or project of another workspace (a personal office's
    # deals bind the owner's private clients / lists, org_id NULL)
    "deal_ref": ("SELECT d.id, d.created_by FROM office_deals d JOIN orgs o ON o.id=d.org_id LEFT JOIN clients cl ON cl.id=d.client_id "
                 "LEFT JOIN lists l ON l.id=d.list_id WHERE d.deleted_at IS NULL AND ("
                 "(cl.id IS NOT NULL AND cl.org_id IS DISTINCT FROM d.org_id AND NOT (cl.org_id IS NULL AND o.personal_of=cl.created_by)) OR "
                 "(l.id IS NOT NULL AND l.org_id IS DISTINCT FROM d.org_id AND NOT (l.org_id IS NULL AND o.personal_of=l.owner_id)))"),
    # 2.50.0 A (#1195): an absence in an organisation of a person who is not (any more) its member
    "absence": ("SELECT a.id, a.user_id FROM hub_absences a JOIN orgs o ON o.id=a.org_id WHERE a.deleted_at IS NULL AND o.personal_of IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=a.org_id AND om.user_id=a.user_id)"),
    # 2.125.0 A (#2117): a vacation account in an organisation of a person who is not (any more) its member
    "leave_quota": ("SELECT q.id, q.user_id FROM hub_leave_quota q JOIN orgs o ON o.id=q.org_id WHERE o.personal_of IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=q.org_id AND om.user_id=q.user_id)"),
    # 2.50.0 A (#1194): a booking of a person in an organisation they are not (any more) a member of
    "booking": ("SELECT b.id, b.resource_id FROM hub_bookings b JOIN orgs o ON o.id=b.org_id WHERE b.deleted_at IS NULL AND b.resource_kind='user' "
                "AND o.personal_of IS NULL AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=b.org_id AND om.user_id=b.resource_id)"),
    # 2.50.0 (#1200): an approval link whose organisation differs from its quotation's / list's
    "signoff_org": ("SELECT s.id, s.created_by FROM office_signoffs s LEFT JOIN office_docs d ON d.id=s.doc_id LEFT JOIN lists l ON l.id=s.list_id "
                    "WHERE (s.doc_id IS NOT NULL AND d.org_id IS DISTINCT FROM s.org_id) OR (s.list_id IS NOT NULL AND l.org_id IS DISTINCT FROM s.org_id)"),
    # 2.51.0 A (#1348): a quotation / invoice bound to a project list of another workspace (a personal office's documents
    # bind the owner's private lists, org_id NULL), a payment suggestion on a document of another area
    "doc_list": ("SELECT d.id, d.created_by FROM office_docs d JOIN orgs o ON o.id=d.org_id JOIN lists l ON l.id=d.list_id "
                 "WHERE l.org_id IS DISTINCT FROM d.org_id AND NOT (l.org_id IS NULL AND o.personal_of=l.owner_id)"),
    # 2.90.0 B (#1921): a bank booking whose import, matched invoice or booked payment lies in another office area
    "bank_tx": ("SELECT t.id, t.import_id FROM office_bank_tx t LEFT JOIN office_bank_imports i ON i.id=t.import_id "
                "LEFT JOIN office_docs d ON t.match_kind='invoice' AND d.id=t.match_id LEFT JOIN office_payments p ON p.id=t.payment_id "
                "WHERE t.deleted_at IS NULL AND ((i.id IS NOT NULL AND i.org_id IS DISTINCT FROM t.org_id) OR "
                "(d.id IS NOT NULL AND d.org_id IS DISTINCT FROM t.org_id) OR (p.id IS NOT NULL AND p.org_id IS DISTINCT FROM t.org_id))"),
    # 2.124.0 D (#2342): a statement balance whose import lies in another office area
    "bank_balance": ("SELECT b.id, b.import_id FROM office_bank_balances b JOIN office_bank_imports i ON i.id=b.import_id "
                     "WHERE i.org_id IS DISTINCT FROM b.org_id"),
    # 2.93.0 A (#1927): a document made from a template bound to a client / project list / quotation / template of another
    # office area (a personal office's documents bind the owner's private clients and lists), or a signature link of it
    # in another area than the document
    "gen_doc_ref": ("SELECT d.id, d.created_by FROM office_gen_docs d JOIN orgs o ON o.id=d.org_id LEFT JOIN clients cl ON cl.id=d.client_id "
                    "LEFT JOIN lists l ON l.id=d.list_id LEFT JOIN office_docs od ON od.id=d.doc_id LEFT JOIN office_doc_templates t ON t.id=d.template_id "
                    "WHERE (cl.id IS NOT NULL AND cl.org_id IS DISTINCT FROM d.org_id AND NOT (cl.org_id IS NULL AND o.personal_of=cl.created_by)) OR "
                    "(l.id IS NOT NULL AND l.org_id IS DISTINCT FROM d.org_id AND NOT (l.org_id IS NULL AND o.personal_of=l.owner_id)) OR "
                    "(od.id IS NOT NULL AND od.org_id IS DISTINCT FROM d.org_id) OR (t.id IS NOT NULL AND t.org_id IS DISTINCT FROM d.org_id)"),
    # 2.99.1 A (#1959): a video sign-off bound to a task / list / client of another workspace, a version / comment / approval
    # link of it in another workspace than the sign-off
    "video_ref": ("SELECT v.id, v.created_by FROM video_reviews v LEFT JOIN tasks t ON t.id=v.task_id LEFT JOIN lists tl ON tl.id=t.list_id "
                  "LEFT JOIN lists l ON l.id=v.list_id LEFT JOIN clients cl ON cl.id=v.client_id WHERE v.deleted_at IS NULL AND ("
                  "(tl.id IS NOT NULL AND tl.org_id IS DISTINCT FROM v.org_id) OR (l.id IS NOT NULL AND l.org_id IS DISTINCT FROM v.org_id) OR "
                  "(cl.id IS NOT NULL AND cl.org_id IS DISTINCT FROM v.org_id) OR EXISTS (SELECT 1 FROM video_versions x WHERE x.review_id=v.id "
                  "AND x.org_id IS DISTINCT FROM v.org_id) OR EXISTS (SELECT 1 FROM video_comments x WHERE x.review_id=v.id AND x.org_id IS DISTINCT "
                  "FROM v.org_id) OR EXISTS (SELECT 1 FROM office_signoffs s WHERE s.video_id=v.id AND s.org_id IS DISTINCT FROM v.org_id "
                  "AND s.state='open' AND s.revoked_at IS NULL))"),  # 2.122.4 A (#2215 L3): a moved review keeps its old (closed) records
    "gen_doc_signoff": ("SELECT s.id, s.created_by FROM office_signoffs s JOIN office_gen_docs d ON d.id=s.gen_doc_id WHERE d.org_id IS DISTINCT FROM s.org_id"),
    "pay_prop": ("SELECT p.id, p.agent_id FROM office_pay_props p JOIN office_docs d ON d.id=p.doc_id WHERE d.org_id IS DISTINCT FROM p.org_id"),
    # 2.113.1 B (#2059): a member of an organisation's team chat channel who is not (any more) in it, an agent of another
    # workspace in a channel or a personal agent whose owner is not in it (the read layer ignores them: collab/teamchan.py
    # tcx_members; boundary_repair takes the person out)
    "tchat_person": ("SELECT m.room_id, m.user_id FROM tchat_members m JOIN tchat_rooms r ON r.id=m.room_id JOIN users u ON u.id=m.user_id "
                     "WHERE r.org_id IS NOT NULL AND " + _PERSON.format(o="r", m="m")),
    "tchat_agent": ("SELECT m.room_id, m.user_id FROM tchat_members m JOIN tchat_rooms r ON r.id=m.room_id JOIN agents a ON a.user_id=m.user_id "
                    "WHERE COALESCE(a.org_id,0)!=COALESCE(r.org_id,0) OR (a.owner_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tchat_members x "
                    "WHERE x.room_id=m.room_id AND x.user_id=a.owner_id))"),  # 2.113.1 (#2059): + a personal agent whose owner is not in it
    # an agent of an organisation that is gone, or a personal agent working in an organisation its owner is not in
    "agent": ("SELECT a.user_id, a.owner_id FROM agents a WHERE a.org_id IS NOT NULL AND (NOT EXISTS (SELECT 1 FROM orgs o WHERE o.id=a.org_id) "
              "OR (a.owner_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=a.org_id AND om.user_id=a.owner_id)))"),
    # 2.48.0 (#1207): a file store share of an organisation's folder / file with a person outside it, or with an agent of
    # another workspace (the read layer ignores both: files/store.py fs_role)
    "file_person": ("SELECT s.node_id, s.user_id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id JOIN users u ON u.id=s.user_id "
                    "WHERE n.org_id IS NOT NULL AND " + _PERSON.format(o="n", m="s")),
    "file_agent": ("SELECT s.node_id, s.agent_id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id JOIN agents a ON a.user_id=s.agent_id "
                   "WHERE COALESCE(a.org_id,0)!=COALESCE(n.org_id,0)"),
    # 2.48.0 (#1111): an organisation's forwarding address for documents held by a person who left it (the mail input
    # refuses it anyway: docs/ingest.py docs_mail_import)
    "doc_mail_person": ("SELECT m.org_id, m.user_id FROM doc_mail m JOIN users u ON u.id=m.user_id WHERE m.org_id IS NOT NULL AND "
                        + _PERSON.format(o="m", m="m")),
    # 2.53.0 C (#1424): a task bell of an organisation's task held by a person outside it, or by an agent (only people get
    # bells; the read layer ignores rows of another workspace: notify/taskbell.py tbl_rows)
    "task_bell_person": ("SELECT b.task_id, b.user_id FROM task_bell b JOIN users u ON u.id=b.user_id WHERE b.org_id IS NOT NULL AND "
                         "(u.kind='agent' OR " + _PERSON.format(o="b", m="b") + ")"),
    # 2.59.0 A (#1735): a client's contact person linked to a contact outside the client's address books (an organisation's
    # client: a book the organisation owns; a client without one: its creator's own private books). (client, its creator);
    # boundary_repair drops such a link (the contact person stays)
    "client_contact": ("SELECT DISTINCT cl.id, cl.created_by FROM office_client_contacts k JOIN clients cl ON cl.id=k.client_id "
                       "JOIN contacts ct ON ct.id=k.contact_id JOIN books b ON b.id=ct.book_id WHERE CASE WHEN cl.org_id IS NOT NULL "
                       "THEN b.owner_org_id IS DISTINCT FROM cl.org_id OR b.org_id IS DISTINCT FROM cl.org_id "
                       "ELSE b.owner_org_id IS NOT NULL OR b.org_id IS NOT NULL OR b.owner_id IS DISTINCT FROM cl.created_by END"),
    # 2.60.0 C (#1512): the reviewer of an organisation's task who is neither its list's owner nor a member of the list
    "task_reviewer": ("SELECT t.id, t.reviewer_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.reviewer_id IS NOT NULL "
                      "AND l.org_id IS NOT NULL AND t.reviewer_id<>l.owner_id AND NOT EXISTS (SELECT 1 FROM list_members m "
                      "WHERE m.list_id=t.list_id AND m.user_id=t.reviewer_id)"),
    # 2.64.3 A (#1817): a wrapped key of an organisation's knowledge space with the lock held by an agent or by a person outside
    # the organisation, or a key of a private space held by another person (the trigger wiki_e2e_members removes it when someone leaves; counted only)
    "wiki_key": ("SELECT k.space_id, k.user_id FROM wiki_keys k JOIN wiki_spaces s ON s.id=k.space_id JOIN users u ON u.id=k.user_id "
                 "WHERE (s.org_id IS NULL AND k.user_id<>s.owner_id) OR (s.org_id IS NOT NULL AND (u.kind='agent' OR "
                 + _PERSON.format(o="s", m="k") + "))"),
    # 2.99.0 A (#2182): a file of a knowledge page that lies in another space than its page (org / owner) -- (file, who stored it)
    "wiki_file": ("SELECT f.id, f.created_by FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id WHERE "
                  "COALESCE(f.org_id,0)<>COALESCE(p.org_id,0) OR (p.org_id IS NULL AND f.owner_id IS DISTINCT FROM p.owner_id)"),
    # 2.123.0 B (#2104): a live person share of a knowledge page / folder that crosses a boundary: in an organisation's space
    # (people get shares in private spaces only), with an agent, or with the space's owner itself -- (share, person)
    "wiki_share": ("SELECT s.id, s.user_id FROM wiki_shares s JOIN users u ON u.id=s.user_id WHERE s.kind='person' AND s.revoked_at IS NULL "
                   "AND (s.org_id IS NOT NULL OR u.kind='agent' OR s.user_id=s.owner_id)"),
    # 2.122.0 A (#2097): a file request in another workspace than its folder, or of an organisation's folder made by a person
    # outside that organisation (the link stops anyway: files/filereq.py frq_alive) -- (request, its creator); counted only
    "file_request": ("SELECT q.id, q.created_by FROM fs_upload_requests q JOIN fs_nodes n ON n.id=q.node_id WHERE q.deleted_at IS NULL "
                     "AND (COALESCE(q.org_id,0)<>COALESCE(n.org_id,0) OR (n.org_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM org_members om "
                     "WHERE om.org_id=n.org_id AND om.user_id=q.created_by)))"),
    # 2.71.0 B (#1459): a task shown in a list of another workspace (the trigger kalmido_ml_prune drops such links on every
    # move; the read layer ignores them: tasks/multilist.py ml_fill) -- (further list, who linked it)
    "list_task_link": ("SELECT k.list_id, k.added_by FROM task_links k JOIN tasks t ON t.id=k.task_id JOIN lists o ON o.id=t.list_id "
                       "JOIN lists x ON x.id=k.list_id WHERE o.org_id IS DISTINCT FROM x.org_id OR k.org_id IS DISTINCT FROM x.org_id"),
    # 2.71.0 A (#1457): a rule in another workspace than its list, or whose move goes into a list of another workspace (it
    # pauses itself when it runs: lists/rules.py rul_target_ok)
    # 2.115.0 A (#2061): an organisation's webhook (switched on) whose owner is no admin of it any more (it turns itself off at the
    # next event: integrations/webhooks.py who_admin_ok; counted only) -- (webhook, its owner)
    "org_webhook": ("SELECT w.id, w.user_id FROM webhooks w WHERE w.org_id IS NOT NULL AND w.enabled=1 AND NOT EXISTS "
                    "(SELECT 1 FROM org_members om WHERE om.org_id=w.org_id AND om.user_id=w.user_id AND om.role='admin')"),
    "list_rule": ("SELECT r.id, r.created_by FROM list_rules r JOIN lists l ON l.id=r.list_id LEFT JOIN lists t ON t.id=r.target_list_id "
                  "WHERE r.deleted_at IS NULL AND (r.org_id IS DISTINCT FROM l.org_id OR (t.id IS NOT NULL AND t.org_id IS DISTINCT FROM l.org_id))"),
    # 2.75.0 A (#1411): a list of an organisation shared with the built-in assistant by a person outside it, or by an agent
    # (the assistant reads only lists the person sees right now: assistant/web.py asst_lists; the row is taken out)
    "assistant_person": ("SELECT a.list_id, a.user_id FROM assistant_access a JOIN lists l ON l.id=a.list_id JOIN users u ON u.id=a.user_id "
                         "WHERE l.org_id IS NOT NULL AND (u.kind='agent' OR " + _PERSON.format(o="l", m="a") + ")"),
    # 2.84.0 A (#1198): a filed mail bound to a client / project of another workspace (the read layer shows it nowhere:
    # hub/hubmail.py hbm_can; boundary_repair takes the binding off, the mail goes back to its recipient's "Not assigned"),
    # and an organisation's hub address held by a person who left it (the mail input refuses it anyway; taken out)
    "hub_mail_ref": ("SELECT m.id, m.owner_id FROM hub_mails m LEFT JOIN clients cl ON cl.id=m.client_id LEFT JOIN lists l ON l.id=m.list_id "
                     "WHERE m.deleted_at IS NULL AND ((cl.id IS NOT NULL AND cl.org_id IS DISTINCT FROM m.org_id) OR "
                     "(l.id IS NOT NULL AND l.org_id IS DISTINCT FROM m.org_id))"),
    # 2.89.0 (#1916): a table attached to a list of another workspace (the read layer ignores the attachment: sheets/core.py
    # sh_list_ok) -- (sheet, who created it; counted only)
    "sheet_list": ("SELECT s.id, s.created_by FROM sheets s JOIN lists l ON l.id=s.list_id WHERE s.deleted_at IS NULL "
                   "AND l.org_id IS DISTINCT FROM s.org_id"),
    # 2.124.0 B (#2110): a file of a table cell that lies in another space than its table (sheets/shkinds.py shk_move_files
    # moves them along) -- (file, who stored it; counted only)
    "sheet_file": ("SELECT f.id, f.created_by FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE "
                   "COALESCE(f.org_id,0)<>COALESCE(s.org_id,0) OR (s.org_id IS NULL AND f.owner_id IS DISTINCT FROM s.owner_id)"),
    # 2.124.0 E (#2116): a further sheet of a table whose space / list differs from its first sheet's (the rights follow the first
    # sheet: sheets/shbook.py; a move / list change copies them over) -- (sheet, who created it; counted only)
    "sheet_book": ("SELECT s.id, s.created_by FROM sheets s JOIN sheets b ON b.id=s.book_id WHERE COALESCE(s.org_id,0)<>COALESCE(b.org_id,0) "
                   "OR (s.org_id IS NULL AND s.owner_id IS DISTINCT FROM b.owner_id) OR s.list_id IS DISTINCT FROM b.list_id"),
    # 2.89.0 (#1916, D): a row carried over into a task / taken from a task of another workspace than the table's (the buttons
    # refuse it; the formulas show "No access" then) -- (sheet, who pressed the button; counted only)
    "sheet_link": ("SELECT s.id, k.created_by FROM sheet_links k JOIN sheets s ON s.id=k.sheet_id JOIN tasks t ON t.id=k.target_id "
                   "JOIN lists l ON l.id=t.list_id WHERE k.kind IN ('task', 'row') AND k.undone_at IS NULL AND l.org_id IS DISTINCT FROM s.org_id"),
    # 2.98.0 A (#1953): a scheduling poll of an organisation held by an agent or a person outside it, or bound to a task / client /
    # list of another workspace (the read layer needs the membership and drops a foreign reference: calendars/polls.py
    # tpo_ref_ok; counted only) -- (poll, owner)
    "sched_poll": ("SELECT p.id, p.user_id FROM sched_polls p JOIN users u ON u.id=p.user_id LEFT JOIN tasks t ON t.id=p.task_id "
                   "LEFT JOIN lists tl ON tl.id=t.list_id LEFT JOIN clients cl ON cl.id=p.client_id LEFT JOIN lists l ON l.id=p.list_id "
                   "WHERE p.deleted_at IS NULL AND ((p.org_id IS NOT NULL AND (u.kind='agent' OR " + _PERSON.format(o="p", m="p") + ")) "
                   "OR (tl.id IS NOT NULL AND tl.org_id IS DISTINCT FROM p.org_id) OR (cl.id IS NOT NULL AND cl.org_id IS DISTINCT FROM p.org_id) "
                   "OR (l.id IS NOT NULL AND l.org_id IS DISTINCT FROM p.org_id))"),
    "hub_token_person": ("SELECT m.org_id, m.user_id FROM hub_tokens m JOIN users u ON u.id=m.user_id WHERE m.org_id IS NOT NULL AND "
                         + _PERSON.format(o="m", m="m")),
    # 2.124.0 C (#2113): a live share of an organisation's table with a person outside it (repaired), of a table with an agent of
    # another workspace, or a share whose org_id differs from its table's (the read layer refuses all: sheets/shshare.py shs_fits)
    "sheet_share_person": ("SELECT s.sheet_id, s.user_id FROM sheet_shares s JOIN sheets t ON t.id=s.sheet_id JOIN users u ON u.id=s.user_id "
                           "WHERE s.revoked_at IS NULL AND t.org_id IS NOT NULL AND " + _PERSON.format(o="t", m="s")),
    "sheet_share_agent": ("SELECT s.sheet_id, s.user_id FROM sheet_shares s JOIN sheets t ON t.id=s.sheet_id JOIN agents a ON a.user_id=s.user_id "
                          "WHERE s.revoked_at IS NULL AND (COALESCE(a.org_id,0)!=COALESCE(t.org_id,0) OR s.org_id IS DISTINCT FROM t.org_id)"),
    # 2.97.0 A (#1950): a bookmark of an organisation held by an agent or by a person outside it (the read layer needs the
    # membership: life/bookmarks.py bm_get; counted only) -- (bookmark, owner)
    "bookmark_owner": ("SELECT b.id, b.user_id FROM bookmarks b JOIN users u ON u.id=b.user_id WHERE b.org_id IS NOT NULL AND "
                       "b.deleted_at IS NULL AND (u.kind='agent' OR " + _PERSON.format(o="b", m="b") + ")"),
    # 2.112.1 B (#2058): an external share link whose workspace is not its node's (the page refuses it: files/extlinks.py
    # xl_find; counted only) -- (link, creator)
    "file_ext_link": ("SELECT x.id, x.created_by FROM fs_ext_links x JOIN fs_nodes n ON n.id=x.node_id WHERE x.org_id IS DISTINCT FROM n.org_id"),
}
TENANT_ALERT = N_("Workspace boundary check: {0} memberships cross the boundary between organisations / private ({1}). Settings > Administration > Organisations")


def boundary_check(c):
    """{n, kinds: {kind: count}, sample: {kind: [[object id, user id], ...]}} over the whole server (0 without workspaces)."""
    out = {"n": 0, "kinds": {}, "sample": {}}
    if not has_workspaces(c):
        return out
    for k, sql in CHECKS.items():
        rows = c.execute(sql + " ORDER BY 1, 2").fetchall()
        if rows:
            out["kinds"][k] = len(rows)
            out["sample"][k] = [[r[0], r[1]] for r in rows[:TENANT_SAMPLE]]
            out["n"] += len(rows)
    return out


# 2.36.2 (#1142): memberships of PEOPLE in an organisation's object who are not members of that organisation are taken out
# (like org_leave) instead of only counted -- the same rule the read layer applies (core/access.py acx_org_ok).
# kind -> (member table, object column). Agents of another workspace stay counted only: the read layer already hides the
# object from them, and moving the agent to the right workspace brings its access back. Owners outside their organisation
# and agents whose owner left stay counted as before.
REPAIR = {"list_person": ("list_members", "list_id"), "group": ("list_members", "list_id"),
          "cal_person": ("ev_cal_members", "cal_id"), "book_person": ("book_members", "book_id"),
          "att_person": ("event_attendees", "event_id"),  # 2.87.0 (#1983)
          "file_person": ("fs_shares", "node_id"),  # 2.48.0 (#1207)
          "doc_mail_person": ("doc_mail", "org_id"),  # 2.48.0 (#1111)
          "task_bell_person": ("task_bell", "task_id"),  # 2.53.0 C (#1424)
          "assistant_person": ("assistant_access", "list_id"),  # 2.75.0 A (#1411)
          "hub_token_person": ("hub_tokens", "org_id"),  # 2.84.0 A (#1198)
          "sheet_share_person": ("sheet_shares", "sheet_id"),  # 2.124.0 C (#2113)
          "tchat_person": ("tchat_members", "room_id")}  # 2.113.1 B (#2059)
TENANT_REPAIRED = N_("Workspace boundary check: {0} memberships across the boundary between organisations were removed ({1}). Settings > Administration > Organisations")


def boundary_repair(c):
    """Takes out every membership in an organisation's list / calendar / address book of a person who is not a member of
    that organisation. {kind: [[object id, user id], ...]} of what was removed; the
    caller commits."""
    out = {}
    ckl = c.execute(CHECKS["client_contact"] + " ORDER BY 1, 2").fetchall()  # 2.59.0 A (#1735): also without workspaces (freelancers)
    for cid, _ in ckl:
        c.execute("UPDATE office_client_contacts k SET contact_id=NULL FROM contacts ct, books b, clients cl WHERE k.client_id=? "
                  "AND cl.id=k.client_id AND ct.id=k.contact_id AND b.id=ct.book_id AND " + CHECKS["client_contact"].split(" WHERE ", 1)[1], (cid,))
    if ckl:
        out["client_contact"] = [[r[0], r[1]] for r in ckl]
    hbm = c.execute(CHECKS["hub_mail_ref"] + " ORDER BY 1, 2").fetchall()  # 2.84.0 A (#1198): also without workspaces (private <-> org)
    for mid, _ in hbm:
        c.execute("UPDATE hub_mails SET client_id=NULL, list_id=NULL WHERE id=?", (mid,))
    if hbm:
        out["hub_mail_ref"] = [[r[0], r[1]] for r in hbm]
    if not has_workspaces(c):
        return out
    for k, (table, col) in REPAIR.items():
        rows = c.execute(CHECKS[k] + " ORDER BY 1, 2").fetchall()
        done = []
        for oid_, uid in rows:
            c.execute(f"DELETE FROM {table} WHERE {col}=? AND user_id=?", (oid_, uid))
            if table == "list_members":
                c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (oid_, uid))
                c.execute("DELETE FROM task_people WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, oid_))
            done.append([oid_, uid])
        if done:
            out[k] = done
    return out


def boundary_last(c):
    try:
        d = json.loads(gsetting(c, "tenant_check") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def boundary_tick(c):
    """Watchdog: the boundary check once a night (KALMIDO_TENANT_CHECK_HOUR, default 3:00 local time; =always: every tick).
    Stores the result (setting tenant_check) and raises an admin alert when there are findings that were not reported
    before (the same findings are not repeated every night; the count stays visible in the administration)."""
    from ..notify.alerts import aa_now
    now = local_now()
    last = boundary_last(c)
    if TENANT_CHECK_ENV != "always":
        if TENANT_CHECK_ENV in ("0", "off", "no") or now.hour < TENANT_CHECK_HOUR or last.get("day") == now.date().isoformat():
            return
    fixed = boundary_repair(c)  # 2.36.2 (#1142): repaired, not only counted
    if fixed:
        n = sum(len(v) for v in fixed.values())
        aa_now("security", "tenantfix|" + hashlib.sha256(json.dumps(fixed, sort_keys=True).encode()).hexdigest()[:16], TENANT_REPAIRED,
               [n, ", ".join(f"{k} {len(v)}" for k, v in sorted(fixed.items()))])
        print(f"boundary check (#1142): {n} memberships across the workspace boundary removed "
              f"{json.dumps({k: v[:TENANT_SAMPLE] for k, v in fixed.items()})}", flush=True)
        c.commit()
    res = boundary_check(c)
    sig = hashlib.sha256(json.dumps(res["sample"], sort_keys=True).encode()).hexdigest()[:16] if res["n"] else ""
    rec = {"day": now.date().isoformat(), "at": iso(now_utc()), "n": res["n"], "kinds": res["kinds"], "sig": sig,
           "alerted": last.get("alerted", "")}
    if res["n"] and sig != last.get("alerted"):
        aa_now("security", "tenant|" + sig, TENANT_ALERT, [res["n"], ", ".join(f"{k} {v}" for k, v in sorted(res["kinds"].items()))])
        rec["alerted"] = sig
        print(f"boundary check (#1036): {res['n']} memberships across the workspace boundary {json.dumps(res['kinds'])}", flush=True)
        if res["kinds"].get("list_agent_private"):
            print("boundary check (K2-3): private agents in lists of an organisation no longer see these lists; assign each "
                  f"agent to a workspace (Settings > Agents): {json.dumps(res['sample']['list_agent_private'])}", flush=True)
    elif not res["n"]:
        rec["alerted"] = ""
    gset(c, "tenant_check", json.dumps(rec, separators=(",", ":")))
    c.commit()


# 2.46.0 (#1563): what each finding is, for the administration (kind prefix -> (type, table of the object))
OA_OBJ = {"list": ("list", "lists"), "group": ("list", "lists"), "cal": ("calendar", "ev_cals"), "book": ("book", "books"),
          "client": ("client", "clients"),  # 2.59.0 A (#1735)
          "att": ("event", "events")}  # 2.87.0 (#1983): an invitation to an organisation's event
OA_DETAIL_MAX = 100


def rg4_oa_seen(c, viewer_uid):
    """2.122.4 A (#1724): what the instance admin viewer_uid may see by name in the boundary findings: (own organisations,
    function(person id) -> True when it is the viewer, shares an organisation with them or belongs to none)."""
    if not viewer_uid:
        return set(), lambda pid: False
    mine = {r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=?", (viewer_uid,)).fetchall()}
    def person(pid):
        if pid == viewer_uid:
            return True
        theirs = {r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=?", (pid,)).fetchall()}
        if not theirs:
            ag = c.execute("SELECT org_id FROM agents WHERE user_id=?", (pid,)).fetchone()
            return not ag or not ag[0] or ag[0] in mine
        return bool(theirs & mine)
    return mine, person


def oa_details(c, limit=OA_DETAIL_MAX, viewer_uid=None):
    """[{kind, type (list | calendar | book | agent), id, name, user_id, user, agent, fixable}] for the findings (at most
    limit). Same rows as boundary_check; fixable = a person's membership that boundary_repair takes out. Admin only (the caller).
    2.122.4 A (#1724): with viewer_uid, objects of organisations the viewer is not a member of and people outside the viewer's
    organisations come with ids only (name / user empty; the client shows "#id"): an organisation's object is named only for
    its members, a private one / an agent when the viewer sees its owner (a shared organisation or none at all)."""
    out = []
    mine, person = rg4_oa_seen(c, viewer_uid) if viewer_uid else (None, None)
    for k, sql in CHECKS.items():
        if len(out) >= limit:
            break
        ot, table = OA_OBJ.get(k.split("_")[0], ("agent", None))
        for r in c.execute(sql + " ORDER BY 1, 2").fetchall()[:limit - len(out)]:
            oid_, uid = r[0], r[1]
            if table:
                row = c.execute(f"SELECT {'title' if table == 'events' else 'name'} FROM {table} WHERE id=?", (oid_,)).fetchone()
                name, who, ag = (row[0] if row else ""), uid, "agent" in k
            else:  # an agent of an organisation that is gone / whose owner left: (agent, owner)
                row = c.execute("SELECT display_name FROM users WHERE id=?", (oid_,)).fetchone()
                name, who, ag = (row[0] if row else ""), oid_, True
            u = c.execute("SELECT display_name FROM users WHERE id=?", (who,)).fetchone()
            if person:  # 2.122.4 A (#1724): ids only outside the viewer's organisations
                ws = rg4_oa_obj_ws(c, table, oid_, mine)
                if ws is False or (ws is None and not person(oid_ if not table else rg4_oa_owner(c, table, oid_))):
                    name, u = "", None
                elif ws is None and not person(who):
                    u = None
            out.append({"kind": k, "type": ot, "id": oid_, "name": name, "user_id": who, "user": u[0] if u else "", "agent": ag,
                        "fixable": k in REPAIR or k in ("client_contact", "hub_mail_ref")})
    return out


def rg4_oa_obj_ws(c, table, oid_, mine):
    """2.122.4 A (#1724): the workspace of a finding's object: True = one of the viewer's organisations, False = another
    organisation, None = private (or an agent finding without a table: decided by the person)."""
    if not table:
        return None
    if table == "events":
        r = c.execute("SELECT k.org_id FROM events e JOIN ev_cals k ON k.id=e.cal_id WHERE e.id=?", (oid_,)).fetchone()
    elif table == "books":  # a book_org finding: org_id may be empty while owner_org_id names the organisation (review 2.122.4)
        r = c.execute("SELECT COALESCE(org_id, owner_org_id) FROM books WHERE id=?", (oid_,)).fetchone()
    else:
        r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (oid_,)).fetchone()
    return (r[0] in mine) if r and r[0] else None


def rg4_oa_owner(c, table, oid_):
    """2.122.4 A (#1724): the owner of a private object of a finding (None when unknown)."""
    if table == "events":
        r = c.execute("SELECT k.owner_id FROM events e JOIN ev_cals k ON k.id=e.cal_id WHERE e.id=?", (oid_,)).fetchone()
    else:
        col = "created_by" if table == "clients" else "owner_id"
        r = c.execute(f"SELECT {col} FROM {table} WHERE id=?", (oid_,)).fetchone()
    return r[0] if r else None


def boundary_summary(c, viewer_uid=None):
    """For GET /api/admin/orgs: the live count + when the nightly check ran last. 2.122.4 A (#1724): viewer_uid = the
    instance admin asking (names only inside their organisations, see oa_details)."""
    from ..core.pg import system_ctx
    with system_ctx(c):  # 2.37.0 (#1150): counts and ids over every organisation, no content
        res = boundary_check(c)
        details = oa_details(c, viewer_uid=viewer_uid) if res["n"] else []  # 2.46.0 (#1563): names of the objects and people, for the admin
    last = boundary_last(c)
    return {"violations": res["n"], "kinds": res["kinds"], "sample": res["sample"], "checked_at": last.get("at") or None,
            "details": details}


# ---------------------------------------------------------------- the workspace of calendars and address books, once
def _obj_ws(c, members_sql, obj_id, cand):
    """The workspace an existing calendar / address book gets: cand (the owner's organisation) when every member fits it,
    else private when every member fits that, else None + mismatch (private, flagged by the boundary check)."""
    rows = c.execute(members_sql, (obj_id,)).fetchall()
    def fits(oid):
        for r in rows:
            if r["kind"] == "agent":
                if (r["a_org"] or None) != (oid or None):
                    return False
            elif oid and not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, r["user_id"])).fetchone():
                return False
        return True
    if cand and fits(cand):
        return cand, False
    return None, not fits(None)


def ws_migrate_objs(c):
    """2.30.0 (#1036), once (like ws_migrate for lists): every calendar and address book gets its workspace. Up to 2.29 every
    object of a server with an organisation was the organisation's, so it goes into its owner's (first) organisation -- unless
    it is clearly private (named like "Private" / "Family" / "Home", an address book mirrored from an outside account) or a
    member does not fit (an agent of another workspace, a person outside the organisation): then it stays private. Nobody
    loses access: shares stay as they are; an agent that fits neither is kept and counted by the boundary check. The caller
    commits."""
    if gsetting(c, "migr_ws2300") == "1":
        return
    from ..accounts.orgs import INSTANCE_ENV
    if not has_workspaces(c) and INSTANCE_ENV == "shared":
        return  # no flag yet: a server that gets organisations later (mode switch) still migrates then
    # 2.46.0 (#1592): a server without organisations is done at once (its first organisation later moves nothing)
    gset(c, "migr_ws2300", "1")
    if not has_workspaces(c):
        return
    org_of = {r["user_id"]: r["oid"] for r in c.execute("SELECT user_id, MIN(org_id) AS oid FROM org_members GROUP BY user_id")}  # pg-ok: alias
    for (u, o) in c.execute("SELECT user_id, org_id FROM agents WHERE org_id IS NOT NULL").fetchall():
        org_of[u] = o  # an agent's calendar / address book: its own workspace
    for u in [r[0] for r in c.execute("SELECT user_id FROM agents WHERE org_id IS NULL")]:
        org_of.pop(u, None)
    cnt = {"cal": [0, 0, 0], "book": [0, 0, 0]}  # org, private, mismatch
    mem = "SELECT m.user_id, u.kind, a.org_id AS a_org FROM {t} m JOIN users u ON u.id=m.user_id LEFT JOIN agents a ON a.user_id=m.user_id WHERE m.{k}=?"
    for kind, table, mt, key, extra in (("cal", "ev_cals", "ev_cal_members", "cal_id", ""), ("book", "books", "book_members", "book_id", ", src_id")):
        for r in c.execute(f"SELECT id, owner_id, name{extra} FROM {table} WHERE org_id IS NULL").fetchall():
            cand = org_of.get(r["owner_id"])
            if PRIVATE_FOLDER_RE.match((r["name"] or "").strip()) or (kind == "book" and r["src_id"]):
                cand = None
            oid, bad = _obj_ws(c, mem.format(t=mt, k=key), r["id"], cand)
            if oid:
                c.execute(f"UPDATE {table} SET org_id=? WHERE id=?", (oid, r["id"]))
                cnt[kind][0] += 1
            else:
                cnt[kind][1] += 1
                cnt[kind][2] += 1 if bad else 0
    print("workspaces (#1036): calendars {} in their organisation, {} private ({} with a member of another workspace, kept); "
          "address books {} / {} ({})".format(*cnt["cal"], *cnt["book"]), flush=True)
