// @ts-check
/* Kalmido web client: 2.123.0 A (#2102, #2106) -- the history of a knowledge page and the text search of the page list.
   History: "History" in the page's "…" menu lists the saved states (date, person; saves of one person within ten minutes
   are one state), a state opens with a line comparison to the current text, "Restore" makes its text the current one
   (a new state; ONE Undo step: the text before comes back). Spaces encrypted in the browser keep no history (a hint).
   Search: from two characters in "Find a page" the server's word index adds the pages whose TEXT has the words (ranked,
   30 at a time, "Show more"); the names are still filtered here at once. Loaded with the module "wiki" (lazyload.js).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const WKH = {s: null, t: 0};
// ---- a small line diff (longest common subsequence over the lines; very long texts: the changed middle as removed + added)
function wkh_diff(a, b) {
  const A = String(a || '').split('\n'), B = String(b || '').split('\n');
  let s = 0; while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let e = 0; while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
  const a1 = A.slice(s, A.length - e), b1 = B.slice(s, B.length - e), mid = [];
  if (a1.length * b1.length > 1500000) { a1.forEach(x => mid.push(['-', x])); b1.forEach(x => mid.push(['+', x])); }
  else {
    const n = a1.length, m = b1.length, L = Array.from({length: n + 1}, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a1[i] === b1[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) { if (a1[i] === b1[j]) { mid.push([' ', a1[i]]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) mid.push(['-', a1[i++]]); else mid.push(['+', b1[j++]]); }
    while (i < n) mid.push(['-', a1[i++]]); while (j < m) mid.push(['+', b1[j++]]);
  }
  return [...A.slice(0, s).map(x => [' ', x]), ...mid, ...A.slice(A.length - e).map(x => [' ', x])];
}
function wkh_diffHtml(a, b) {
  const d = wkh_diff(a, b), add = d.filter(x => x[0] === '+').length, del = d.filter(x => x[0] === '-').length;
  if (!add && !del) return `<div class="muted mhint">${tr('No differences.')}</div>`;
  const near = d.map((x, i) => x[0] !== ' ' || d.slice(Math.max(0, i - 3), i + 4).some(y => y[0] !== ' '));
  let h = '', gap = false;
  d.forEach(([t, x], i) => {
    if (!near[i]) { if (!gap) h += `<div class="wkhd gap" aria-hidden="true">…</div>`; gap = true; return; }
    gap = false;
    h += `<div class="wkhd ${t === '+' ? 'add' : t === '-' ? 'del' : ''}"><span class="wkhdm" aria-hidden="true">${t === ' ' ? '' : t === '+' ? '+' : '−'}</span><span class="sr">${t === '+' ? tr('added:') : t === '-' ? tr('removed:') : ''}</span><span>${esc(x) || '&nbsp;'}</span></div>`;
  });
  return `<div class="muted wkhsum">${esc(tr('Lines: {0} added, {1} removed', add, del))}</div><div class="wkhdiff" role="group" aria-label="${esc(tr('Changes'))}">${h}</div>`;
}
// ---- the page menu entry and the dialog
const wkh_items = p => S.me?.kind === 'agent' ? [] : [{label: tr('History'), icon: 'clock', fn: () => wkh_dlg(p)}];
async function wkh_dlg(p) {
  await wk_flush();
  /** @type {any} */
  const md = modal(`<h3>${esc(tr('History'))} · ${esc(wk_base(p.path))}</h3><div class="wkhbody" id="wkh-b"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-wkh="close">${esc(tr('Close'))}</button></div>`);
  md.classList.add('wkhdlg');
  const box = $('#wkh-b', md), may = WK.idx[p.space]?.mayWrite !== false;
  let vs = [];
  const list = () => {
    box.innerHTML = vs.length ? `<p class="shint">${esc(tr('Saves of one person within ten minutes are one version.'))}</p><ul class="wkhlist">${vs.map(v => `<li><button type="button" class="wkhitem" data-wkh="open" data-id="${v.id}">${ic('clock', 's')}<span class="wkhwhen">${esc(fmtWhen(v.updated_at))}</span><span class="muted">${esc(v.by_name || '')}</span>${v.current ? `<span class="wkhcur">${esc(tr('current'))}</span>` : ''}</button></li>`).join('')}</ul>`
      : `<div class="muted mhint">${esc(tr('No earlier versions yet.'))}</div>`;
  };
  try {
    const j = await rawFetch('GET', `/api/wiki/pages/${p.id}/versions`);
    if (j.e2e) { box.innerHTML = `<div class="muted mhint">${esc(tr('Spaces encrypted in the browser keep no history: the server cannot read their texts.'))}</div>`; return; }
    vs = j.versions || []; list();
  } catch (e) { box.innerHTML = `<div class="muted mhint">${esc(e.message)}</div>`; return; }
  md.addEventListener('click', async e => {
    const a = /** @type {any} */ (e.target).closest('[data-wkh]'); if (!a) return;
    const k = a.dataset.wkh;
    if (k === 'close') modalClose(md);
    else if (k === 'list') list();
    else if (k === 'open') {
      const v = vs.find(x => x.id === +a.dataset.id); if (!v) return;
      box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`;
      let d; try { d = await rawFetch('GET', `/api/wiki/pages/${p.id}/versions/${v.id}`); } catch (er) { box.innerHTML = `<div class="muted mhint">${esc(er.message)}</div>`; return; }
      const cur = WK.pg?.id === p.id ? WK.pg : p;
      box.innerHTML = `<div class="wkhhead"><button type="button" class="iconbtn" data-wkh="list" aria-label="${esc(tr('Back'))}" title="${esc(tr('Back'))}">${ic('back')}</button><div><b>${esc(fmtWhen(d.updated_at))}</b>${d.by_name ? ` · ${esc(d.by_name)}` : ''}${d.path !== cur.path ? `<div class="muted">${esc(d.path)}</div>` : ''}</div><span class="spacer"></span>${may && !v.current ? `<button type="button" class="btn pri" data-wkh="restore" data-id="${v.id}">${ic('undo', 's')}${esc(tr('Restore'))}</button>` : ''}</div>
        <p class="muted">${esc(tr('Compared with the current text: + comes back with Restore, − goes.'))}</p>${wkh_diffHtml(cur.body, d.body)}`;
    } else if (k === 'restore') {
      a.disabled = true;
      if (await wkh_restore(p, +a.dataset.id)) modalClose(md); else a.disabled = false;
    }
  });
}
async function wkh_restore(p, vid) {
  const before = (WK.pg?.id === p.id ? WK.pg : p).body, sp = p.space;
  const put = r => { if (WK.pg?.id === p.id) Object.assign(WK.pg, r, {backlinks: WK.pg.backlinks}); wk_after(sp); return r; };
  let r; try { r = put(await rawFetch('POST', `/api/wiki/pages/${p.id}/versions/${vid}/restore`, {expect_updated_at: (WK.pg?.id === p.id ? WK.pg : p).updated_at})); }
  catch (e) { toast(e.status === 409 ? tr('The page was changed in the meantime. Open the history again.') : e.message); if (e.status === 409) wk_after(sp); return false; }
  const e = histAdd({label: tr('Restored version of {0}', qn(wk_base(r.path))), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { put(await rawFetch('PATCH', '/api/wiki/pages/' + p.id, {body: before})); return {skipped: []}; },
    redo: async () => { put(await rawFetch('POST', `/api/wiki/pages/${p.id}/versions/${vid}/restore`, {})); return {skipped: []}; }});
  histToast(tr('Version restored'), e);
  return true;
}
// ---- 2.376 (#3292): the snippet of a hit -- the server's (snippet + marks in code points) or, for a page whose text is here
// already (a space with the lock, offline), cut here with the rules of wksearch.py wks_plain / wks_snippet; never loaded extra
const WKS_SNIP = 180;
/** @type {Array<[RegExp, any]>} */
const WKS_PLAIN = [[/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/, ' '], [/^[ \t]*(?:`{3,}|~{3,}).*$/gm, ' '],
  [/!\[([^\[\]]*)\]\([^()\s]*\)/g, '$1'], [/\[\[([^\[\]|#\n]*)(?:#[^\[\]|\n]*)?\|([^\[\]\n]+)\]\]/g, '$2'],
  [/\[\[([^\[\]|#\n]+)(?:#[^\[\]\n]*)?\]\]/g, (m, a) => a.split('/').pop()], [/\[([^\[\]]+)\]\([^()\s]*\)/g, '$1'], [/<[^<>\n]{1,200}>/g, ' '],
  [/^[ \t]*(?:[-*_][ \t]*){3,}$/gm, ' '], [/^[ \t]*(?:>[ \t]?)*(?:#{1,6}[ \t]+|[-*+][ \t]+(?:\[[ xX]\][ \t]+)?|\d{1,9}[.)][ \t]+)?/gm, ''],
  [/[*~`]+|(?<![\p{L}\p{N}_])_+|_+(?![\p{L}\p{N}_])|\\(?=[!-/:-@[-`{-~])/gu, ''], [/[ \t]*\|[ \t]*/g, ' '], [/\s+/g, ' ']];
const wks_plain = text => WKS_PLAIN.reduce((s, [rx, to]) => s.replace(rx, to), String(text || '').slice(0, 200000)).trim();
const wks_fold = s => s.toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '').replace(/ß/g, 'ss');  // docs/rules.py fold
const wks_words = q => [...new Set(wks_fold(String(q || '')).match(/[\p{L}\p{N}_]+/gu) || [])].filter(w => w.length >= 2 && w.length <= 40).slice(0, 8);
function wks_snip(text, q) {
  const ws = wks_words(q), t = Array.from(wks_plain(text)); if (!ws.length || !t.length) return null;
  let ft = ''; const pos = [];
  t.forEach((ch, i) => { const f = wks_fold(ch) || ch.toLowerCase(); ft += f; for (let k = 0; k < f.length; k++) pos.push(i); });
  const marks = [];
  for (const w of ws) for (const m of ft.matchAll(new RegExp('(?<![\\p{L}\\p{N}_])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + (w.length < 4 ? '(?![\\p{L}\\p{N}_])' : ''), 'gu'))) { marks.push([pos[m.index], pos[m.index + m[0].length - 1] + 1]); if (marks.length > 400) break; }
  if (!marks.length) return null;
  marks.sort((a, b) => a[0] - b[0]);
  const mg = []; for (const [a, b] of marks) { if (mg.length && a <= mg[mg.length - 1][1]) mg[mg.length - 1][1] = Math.max(mg[mg.length - 1][1], b); else mg.push([a, b]); }
  const first = mg[0][0], sp = (from, to) => { for (let i = Math.max(0, from); i < to; i++) if (t[i] === ' ') return i; return -1; };
  let start = 0, end = t.length;
  if (t.length > WKS_SNIP) {
    start = Math.max(0, Math.min(first - Math.floor(WKS_SNIP / 3), t.length - WKS_SNIP)); if (start < 16) start = 0;
    if (start > 0) { const i = sp(start - 1, first); if (i >= 0) start = i + 1; }
    end = Math.min(t.length, start + WKS_SNIP);
    if (end < t.length) { for (let i = end; i >= Math.max(start + 1, mg[0][1]); i--) if (t[i] === ' ') { end = i; break; } }
  }
  const pre = start > 0 ? '…' : '', sh = pre.length - start;
  return {snippet: pre + t.slice(start, end).join('') + (end < t.length ? '…' : ''), marks: mg.filter(([a]) => a >= start && a < end).map(([a, b]) => [a + sh, Math.min(b, end) + sh])};
}
// the snippet line of a hit p (query q): escaped, the words <b>; '' without one
function wks_snipHtml(p, q) {
  const h = p.snippet ? p : typeof p.body === 'string' && p.body ? wks_snip(p.body, q) : null; if (!h?.snippet) return '';
  const cs = Array.from(h.snippet); let o = '', at = 0;
  for (const [a, b] of h.marks || []) { if (a < at) continue; o += esc(cs.slice(at, a).join('')) + '<b>' + esc(cs.slice(a, b).join('')) + '</b>'; at = b; }
  return `<small class="wksnip">${o + esc(cs.slice(at).join(''))}</small>`;
}
// the name of a hit with its snippet (wks_inner, wiki.js wk_hitHtml / the hit lists): the row wraps, the snippet goes below
const wks_nameHtml = (p, q, path = p.path) => `<span>${esc(path)}</span>${wks_snipHtml(p, q)}`;
// ---- the text search below the page list (wiki.js viewWiki: wks_html in #wk-res)
function wks_html(sp, q, shown) {
  q = String(q || '').trim();
  if (q.length < 2 || sp && wk_e2e(sp)) { WKH.s = null; return ''; }  // 2.198.0 A (#2743): sp '' = every space (under "All workspaces")
  const s = WKH.s;
  if (!s || s.q !== q || s.sp !== sp) { WKH.s = {q, sp, pages: [], more: false, busy: true}; clearTimeout(WKH.t); WKH.t = setTimeout(() => wks_load(false), 300); return `<section class="wks" id="wks" aria-live="polite"></section>`; }
  return `<section class="wks" id="wks" aria-live="polite">${wks_inner(s, shown)}</section>`;
}
function wks_inner(s, shown) {
  const ids = new Set((shown || []).map(p => p.id)), ps = s.pages.filter(p => !ids.has(p.id) && !(!s.sp && p.space && wk_e2e(p.space)));  // 2.198.0 A (#2743): a locked space's texts are searched in the browser
  if (!ps.length) return '';  // 2.126.2 A (#2363): only name hits = no "Found in the text" section, no "Show more"
  return `<h4 class="muted">${ic('search', 's')}${esc(tr('Found in the text'))}</h4><ul class="wktree">${ps.map(p => `<li><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}${wks_nameHtml(p, s.q)}${s.sp === '' && p.space ? `<small class="muted wkspn">${esc(wk_spaceName(p.space))}</small>` : ''}</a></li>`).join('')}</ul>
    ${s.more ? `<button type="button" class="btn sm wksmore" data-wks="more" ${s.busy ? 'disabled' : ''}>${esc(tr('Show more'))}</button>` : ''}`;
}
async function wks_load(more) {
  const s = WKH.s; if (!s) return;
  s.busy = true;
  let j; try { j = await rawFetch('GET', `/api/wiki/search?${s.sp ? `space=${encodeURIComponent(s.sp)}&` : ''}q=${encodeURIComponent(s.q)}&limit=30&offset=${more ? s.pages.length : 0}`); } catch { j = {pages: [], more: false}; }
  if (WKH.s !== s) return;  // another query meanwhile
  s.pages = more ? [...s.pages, ...(j.pages || [])] : (j.pages || []); s.more = !!j.more; s.busy = false;
  const el = $('#wks'); if (!el) return;
  const qq = s.q.toLowerCase(), shown = (s.sp ? wk_pages(s.sp) : wk_spaces().flatMap(wk_pages)).filter(p => p.path.toLowerCase().includes(qq));
  el.innerHTML = wks_inner(s, shown);
  if (el.innerHTML) el.parentElement?.querySelector(':scope > .empty')?.remove();  // "No page matches." only when the text has none either
}
document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-wks="more"]'); if (!a || !$('#view')?.contains(a)) return;
  a.disabled = true; wks_load(true);
});
