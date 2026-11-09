// @ts-check
// 2.111.0 A (#2233): Undo for the editors that save every change at once: office documents (with their parts) and tables
// (2.747.0, #5246: clients and the office master data moved to objsave.js objSess / objSaved). Every own saved change is one step of the history
// (Ctrl/Cmd+Z, undo.js); leaving a changed document or table turns its steps into ONE entry and shows "... saved · Undo"
// for 10 seconds, which takes back everything since it was opened. The server (kalmido/office/undo.py) keeps a copy before
// each step that came with the header X-Kalmido-Undo and refuses (409) when someone else changed it in between or it is
// finalised / sent meanwhile. Finalising, sending, payments, status and DATEV stay final: they end the session (barrier).
// 2.747.0 (#5252): finalising, sending, a payment and the DATEV copy no longer end it silently: once the write went through,
// the history shows it as a barrier entry (OUN_BAR, oun_bar) - Undo there names why it stays (the server's own message) and
// "Undo up to here" stops at it; the server writes the same barrier into the person's step groups (office/oubar.py).
const OUN = {s: {}, ms: 10000};
const OUN_BAR = /^\/api\/office\/docs\/(\d+)\/(finalize|send|datev|payments)(?:\/\d+)?$/;
const OUN_BAR_LABEL = {finalize: N_('Finalised: {0}'), send: N_('Sent: {0}'), datev: N_('Sent to DATEV: {0}'), payments: N_('Payment recorded: {0}'), unpay: N_('Payment reversed: {0}')};
const OUN_DOC_RE = /^\/api\/office\/docs\/(\d+)(\/items|\/parts(?:\/\d+(?:\/items)?)?)?$/;
const OUN_FREE = /^\/api\/office\/docs\/\d+\/(duplicate|invoice|credit|pdf|xml|render|log)\b/;  // makes another document / reads: no barrier
const oun_tok = () => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
function oun_key(method, url) {  // the editor a write belongs to: 'doc:5' | 'client:7' | 'services:3' (null = none)
  const u = String(url || '').split('?')[0];
  const m = u.match(OUN_DOC_RE);
  if (m) {
    const sub = m[2] || '';
    const ok = sub === '' ? method === 'PATCH' : sub === '/items' ? method === 'PUT' : /\/parts$/.test(sub) ? method === 'POST'
      : /\/items$/.test(sub) ? method === 'PUT' : method === 'PATCH' || method === 'DELETE';
    return ok ? 'doc:' + m[1] : null;
  }
  // 2.747.0 (#5246): clients and the master data left for objsave.js (objSess / objSaved, the core's session undo)
  return null;
}
// core.js rawFetch0: the header of a write (the session token of its editor); another write of an open document ends it
function oun_hdr(method, url) {
  if (method === 'GET') return '';
  const key = oun_key(method, url);
  if (!key) {
    const d = String(url || '').match(/^\/api\/office\/docs\/(\d+)\b/);
    if (d && !OUN_FREE.test(url) && !OUN_BAR.test(String(url).split('?')[0]) && OUN.s['doc:' + d[1]]) oun_end('doc:' + d[1]);  // 2.747.0 (#5252): a barrier ends it in oun_ok
    return '';
  }
  const s = OUN.s[key] || (OUN.s[key] = {key, tok: oun_tok(), name: ''});
  s.busy = (s.busy || 0) + 1; s.busyAt = Date.now();
  return s.tok;
}
// core.js rawFetch0: the write went through -> one step (documents)
function oun_ok(method, url, j) {
  if (typeof SHV !== 'undefined') oun_sheetWrite(url, j);
  oun_bar(method, url, j);
  const key = oun_key(method, url), s = key && OUN.s[key]; if (!s) return;
  s.n = (s.n || 0) + 1; s.busy = Math.max(0, (s.busy || 0) - 1);
  if (!key.startsWith('doc:')) { s.name = j?.name || j?.name_de || j?.key || s.name; return; }
  s.name = oun_docName(j) || s.name;
  histAdd({label: tr('{0} changed', s.name || tr('Document')), ids: [], snaps: [], lids: [], oun: key, tok: s.tok, srv: true,  // 2.773.0 (#5250): srv = the server's list "Recent steps" has it
    undo: () => oun_run(key, s.tok, 'undo'), redo: () => oun_run(key, s.tok, 'redo')});
}
const oun_docName = d => !d || !d.kind ? '' : d.number || d.project_title || (typeof ofdKindName === 'function' ? ofdKindName(d.kind, true) : '');
// the request to the server; the answer is the object as it is now (an open document shows it at once)
async function oun_run(key, tok, op) {
  const [kind, id] = key.split(':');
  const j = await api('POST', `/api/office/undo/${kind}/${id}`, {sess: tok, op});
  if (kind === 'doc' && typeof OFD !== 'undefined') {
    if (OFD.doc && OFD.doc.id === +id) { OFD.doc = j; OFD.log = null; }
    OFD.list = null;
    if (typeof ofdDraw === 'function') ofdDraw();
  } else if (kind !== 'client' && typeof ofcReload === 'function') ofcReload(kind);
  return {skipped: []};
}
// the steps of a session out of the history (they become one entry or end)
function oun_pull(key) {
  const mine = e => e && (e.oun === key || (e.parts || []).some(p => p.oun === key));
  const steps = HIST.undo.filter(mine);
  HIST.undo = HIST.undo.filter(e => !mine(e)); HIST.redo = HIST.redo.filter(e => !mine(e));
  if (HIST.toastE && mine(HIST.toastE)) HIST.toastE = null;
  return steps;
}
function oun_end(key) { oun_pull(key); delete OUN.s[key]; if (typeof renderHist === 'function') renderHist(); }
// 2.747.0 (#5252): a barrier went through (finalised, sent, paid, DATEV): the open session's steps leave the history (they
// cannot go back any more) and one entry names what happened; undo.js histStep stops there and shows e.barrier
function oun_bar(method, url, j) {
  const m = String(url || '').split('?')[0].match(OUN_BAR); if (!m || (method !== 'POST' && method !== 'DELETE')) return;
  const key = 'doc:' + m[1], s = OUN.s[key];
  const what = m[2] === 'payments' && method === 'DELETE' ? 'unpay' : m[2];
  if (s) oun_end(key);
  const name = oun_docName(j) || s?.name || tr('Document');
  histAdd({label: tr(OUN_BAR_LABEL[what], name), ids: [], snaps: [], lids: [], srv: true, barrier: tr('Finalised or sent in the meantime, so the changes stay'),
    undo: async () => ({skipped: []}), redo: async () => ({skipped: []})});
}
// leaving a document: its remaining own steps -> one entry "Undo all since opening" + the 10-second hint
function oun_leave(key) {
  const s = OUN.s[key]; if (!s) return;
  // a save still on its way (the field's change fired by the click on Back): wait for it (a failed one: at most 8 s)
  if (s.busy && Date.now() - s.busyAt < 8000) { if (!s.wait) s.wait = setTimeout(() => { s.wait = 0; oun_leave(key); }, 150); return; }
  delete OUN.s[key];
  const steps = oun_pull(key);
  if (!steps.length) { if (typeof renderHist === 'function') renderHist(); return; }
  const msg = tr('{0} saved', s.name || tr('Document'));
  const e = histAdd({label: msg, ids: [], snaps: [], lids: [], ounAll: key, srv: true,
    undo: () => oun_run(key, s.tok, 'all'), redo: () => oun_run(key, s.tok, 'redoall')});
  histToast(msg, e, OUN.ms);
}
// ---- tables (sheets.js): their steps are in the history already (tagged by oun_tag); the session keeps the table's rev
// as this person's own last write left it (the answers carry it)
const OUN_SHEET_RE = /^\/api\/sheets\/(\d+)(?:\/|$)/;
function oun_sheetWrite(url, j) {
  const m = String(url || '').split('?')[0].match(OUN_SHEET_RE); if (!m || /\/presence$/.test(url)) return;
  const sid = +m[1], key = 'sheet:' + sid, s = OUN.s[key] || (OUN.s[key] = {key, sid, name: ''});
  if (SHV.sh?.id === sid) s.name = SHV.sh.title || tr('Untitled table');
  if (typeof j?.rev === 'number') s.rev = j.rev; else oun_sheetRev(sid).then(r => { s.rev = r; });
}
// undo.js histAdd: a step made while a table is open belongs to its session
function oun_tag(e) {
  /** @type {any} */
  const r = S.route || {};
  if (!e || e.oun || e.ounAll || (e.ids || []).length || r.mod !== 'sheets' || !r.sh) return;
  const key = 'sheet:' + r.sh;
  if (OUN.s[key]) e.oun = key;
}
async function oun_sheetRev(sid) { try { return (await rawFetch('GET', '/api/sheets/' + sid)).rev; } catch { return null; } }
function oun_sheetLeave(key) {
  const s = OUN.s[key]; if (!s) return;
  delete OUN.s[key];
  const steps = oun_pull(key);
  if (!steps.length) { if (typeof renderHist === 'function') renderHist(); return; }
  const msg = tr('{0} saved', s.name || tr('Table'));
  const run = async (dir, want) => {
    if (await oun_sheetRev(s.sid) !== want()) return {skipped: [msg], none: true};  // someone else changed the table meanwhile
    for (const p of dir === 'undo' ? [...steps].reverse() : steps) await histRun(p, dir);  // undo.js: groups (a paste) step through their parts
    const rev = await oun_sheetRev(s.sid);
    if (dir === 'undo') s.back = rev; else s.rev = rev;
    if (SHV.sh?.id === s.sid && typeof shvReload === 'function') await shvReload();
    return {skipped: []};
  };
  const e = histAdd({label: msg, ids: [], snaps: [], lids: [], ounAll: key, undo: () => run('undo', () => s.rev), redo: () => run('redo', () => s.back)});
  histToast(msg, e, OUN.ms);
}

// ---- leaving: any change of the view (menu, back, link, another document) ends the open editor's session
function oun_route() {
  /** @type {any} */
  const r = S.route || {};
  for (const key of Object.keys(OUN.s)) {
    const [kind, id] = key.split(':');
    if (kind === 'doc' && !(r.mod === 'office' && +r.id === +id)) oun_leave(key);
    else if (kind === 'sheet' && !(r.mod === 'sheets' && +r.sh === +id)) oun_sheetLeave(key);
  }
}
window.addEventListener('hashchange', () => setTimeout(oun_route, 0));
