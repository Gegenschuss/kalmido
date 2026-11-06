// @ts-check
/* Kalmido web client: 2.609.0 (#3372) own ticket types per workspace (kalmido/tasks/ttypes.py) next to the built-in bug /
   feature / task (TTYPES, quickadd.js): what a type shows (ttInfo), what a project offers (ttOffered), the epic's progress; Settings > Data >
   Ticket types (an organisation's admins, a person their own; the others read) is in settings.js.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const TTY = {at: 0};
const ttyRows = () => S.ttypes || (S.ttypes = LS.get('ttypes', []) || []);
// every own type the person can meet; loaded with the state (at most every five minutes) and after a change in Settings
async function tty_load(force) {
  if (!force && Date.now() - TTY.at < 300000) return;
  TTY.at = Date.now();
  let j; try { j = await rawFetch('GET', '/api/ticket-types'); } catch { ttyRows(); return; }
  const was = JSON.stringify(S.ttypes || []), now = JSON.stringify(j.types || []);
  S.ttypes = j.types || []; LS.set('ttypes', S.ttypes);
  if (was !== now && S.tasks) render();
}
// the own types of the workspace list lid belongs to
const tty_ofList = lid => { const l = listById(lid); if (!l) return []; return ttyRows().filter(r => l.org_id ? r.org_id === l.org_id : !r.org_id && r.owner_id === l.owner_id); };
// {key, name, icon, color, own} of type k (in list lid's workspace first); an unknown key shows as itself
function ttInfo(k, lid) {
  if (!k) return null;
  const b = TTYPES.find(x => x[0] === k); if (b) return {key: k, name: tr(b[1]), icon: b[2], color: '', own: false};
  const r = (lid && tty_ofList(lid).find(x => x.key === k)) || ttyRows().find(x => x.key === k);
  return {key: k, name: r ? r.name : k, icon: r?.icon || 'tsq', color: r?.color || '', own: true};
}
// the type keys project lid offers: built-in, then the enabled own ones of its workspace; the project's pick (lists.ttypes) limits them
function ttOffered(lid) {
  const all = [...TTYPES.map(x => x[0]), ...tty_ofList(lid).filter(r => r.enabled).map(r => r.key)];
  let pick = null; try { pick = JSON.parse(listById(lid)?.ttypes || 'null'); } catch { /* bad json */ }
  return Array.isArray(pick) && pick.length ? all.filter(k => pick.includes(k)) : all;
}
// the quick-add words of the own types: key and name (one word, lower case) -> key
function ttOwnWords() {
  const w = {};
  for (const r of ttyRows()) if (r.enabled) { w[r.key] = r.key; const n = String(r.name || '').toLowerCase(); if (/^[\p{L}\p{N}_-]+$/u.test(n) && !(n in TT_WORDS)) w[n] = w[n] || r.key; }
  return w;
}
// an epic's progress: its subtasks (any project) done / all; null without subtasks
function ttEpicProg(t) {
  if (t?.ttype !== 'epic') return null;
  const k = children(t.id).filter(x => !x.deleted_at);
  return k.length ? {done: k.filter(x => x.status !== 0).length, all: k.length} : null;
}
// in the detail's field grid: a label and its value
const ttEpicLine = t => { const p = ttEpicProg(t); return p ? `<label>${tr('Progress')}</label><span class="ttepic"><progress max="${p.all}" value="${p.done}" aria-hidden="true"></progress> ${esc(tr('{0} of {1} subtasks done', p.done, p.all))}</span>` : ''; };
// Settings > Data > Ticket types: settings.js (loads on demand with the dialog, start budget #4198)
