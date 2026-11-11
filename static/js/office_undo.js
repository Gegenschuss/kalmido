// @ts-check
// 2.111.0 A (#2233): Undo for the office documents, which save every change at once.
// 2.905.0 (#5255, undo across devices stage 7): every own saved change of a document is one step of the person's server
// history (kalmido/office/owrite.py ow_write -> core/undogroups.py; its answer names the group, core.js rawFetch0): this file
// only puts a labelled entry for it into the window's history (undo.js histAdd), so the arrow and Ctrl/Cmd+Z name it. The editor
// sessions (header X-Kalmido-Undo, "everything since opening" when leaving) and the table sessions are gone; finalising,
// sending, a payment and DATEV are barriers the server writes itself (office/oubar.py) and the undo stops there.
const OUN_DOC_RE = /^\/api\/office\/docs\/(\d+)(\/items|\/parts(?:\/\d+(?:\/items)?)?)?$/;
function oun_key(method, url) {  // the document a write belongs to: 'doc:5' (null = none)
  const u = String(url || '').split('?')[0];
  const m = u.match(OUN_DOC_RE);
  if (!m) return null;
  const sub = m[2] || '';
  const ok = sub === '' ? method === 'PATCH' : sub === '/items' ? method === 'PUT' : /\/parts$/.test(sub) ? method === 'POST'
    : /\/items$/.test(sub) ? method === 'PUT' : method === 'PATCH' || method === 'DELETE';
  return ok ? 'doc:' + m[1] : null;
}
const oun_docName = d => !d || !d.kind ? '' : d.number || d.project_title || (typeof ofdKindName === 'function' ? ofdKindName(d.kind, true) : '');
// core.js rawFetch0: a document's change went through and the server recorded its step -> one entry with its name
function oun_ok(method, url, j) {
  if (!oun_key(method, url) || !j?._ugid) return;
  histAdd({label: tr('{0} changed', oun_docName(j) || tr('Document')), ids: [], lids: [], res: j, area: 'office'});
}
