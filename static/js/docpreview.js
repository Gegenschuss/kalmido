/* Kalmido web client: the Word / Excel preview and "Summarise" by an agent (2.92.0 C, #1926).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md); loads with the
   PDF preview (module pdf, lazyload.js). dpvOpen({url, name, size, dlUrl, aid?}) opens a .docx / .xlsx in a lightbox like
   the PDF and text viewers: the server reads the file in a limited worker and sends a small model (files/officeprev.py);
   everything here is built from that model through esc() -- no HTML or XML of the file reaches the page.
   dpvSumMount(lightbox, o) adds "Summarise" to a preview of a task / comment file (aid): only when an agent that sees the
   task can be asked (GET /api/attachments/{id}/agents); the request is a normal comment that mentions the agent (one undo
   step). Kalmido itself calls no language model. */
'use strict';

const DPV_COLS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const dpvCol = i => { let s = ''; i += 1; while (i > 0) { const r = (i - 1) % 26; s = DPV_COLS[r] + s; i = Math.floor((i - 1) / 26); } return s; };
const dpvRuns = rs => (rs || []).map(r => {
  let h = esc(r.x || '').replace(/\n/g, '<br>');
  if (r.b) h = `<strong>${h}</strong>`;
  if (r.i) h = `<em>${h}</em>`;
  return h;
}).join('');

function dpvDocHtml(j) {
  const out = [];
  let list = null;  // the open <ul>/<ol> of consecutive list items (one level deep enough for a preview: depth = indent)
  const endList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const b of j.blocks || []) {
    if (b.t === 'li') {
      const tag = b.o ? 'ol' : 'ul';
      if (list !== tag) { endList(); out.push(`<${tag} class="dpvlist">`); list = tag; }
      out.push(`<li style="margin-inline-start:${Math.min(+b.l || 0, 8) * 1.25}rem">${dpvRuns(b.r)}</li>`);
      continue;
    }
    endList();
    if (b.t === 'h') { const l = Math.min(Math.max(+b.l || 1, 1), 6) + 1; out.push(`<h${Math.min(l, 6)} class="dpvh">${dpvRuns(b.r)}</h${Math.min(l, 6)}>`); }
    else if (b.t === 'tbl') out.push(`<div class="dpvtwrap"><table class="dpvtbl">${(b.rows || []).map(r => `<tr>${r.map(c => `<td>${esc(c).replace(/\n/g, '<br>')}</td>`).join('')}</tr>`).join('')}</table></div>`);
    else out.push(`<p>${dpvRuns(b.r)}</p>`);
  }
  endList();
  if (!out.length) return `<div class="tvmsg">${esc(tr('The document is empty.'))}</div>`;
  return `<div class="dpvdoc">${out.join('')}</div>${j.truncated ? `<p class="dpvcut muted">${esc(tr('Only the beginning is shown. Download the file for everything.'))}</p>` : ''}`;
}

function dpvSheetHtml(sh, more) {
  if (!sh || !(sh.rows || []).length) return `<div class="tvmsg">${esc(tr('The sheet is empty.'))}</div>`;
  const w = Math.max(1, sh.cols || 1);
  const head = `<tr><th class="dpvrn" aria-hidden="true"></th>${Array.from({length: w}, (_, i) => `<th scope="col">${dpvCol(i)}</th>`).join('')}</tr>`;
  const rows = sh.rows.map(r => `<tr><th scope="row" class="dpvrn">${+r.n || ''}</th>${Array.from({length: w}, (_, i) => {
    const v = r.c[i] ?? '';
    return `<td${/^-?[\d.,]+( %)?$/.test(v) ? ' class="dpvnum"' : ''}>${esc(v)}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="dpvtwrap dpvgrid"><table class="dpvtbl dpvsheet"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`
    + (sh.truncated || more ? `<p class="dpvcut muted">${esc(tr('Only the beginning is shown. Download the file for everything.'))}</p>` : '');
}

async function dpvOpen(o) {
  $('.lightbox')?.remove();
  const back = document.activeElement, m = document.createElement('div');
  let j = null, sheet = 0, gone = false;
  m.className = 'lightbox tview dpview';
  m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true'); m.setAttribute('aria-label', o.name || tr('Preview'));
  m.innerHTML = `<div class="tvbox dpvbox"><div class="tvbar"><div class="tvname"><b>${esc(o.name || '')}</b><span>${o.size ? fmtSize(o.size) : ''}</span></div>
    <span class="spacer"></span><span class="dpvsumslot"></span>
    <a class="iconbtn" href="${esc(o.dlUrl || '')}" download="${esc(o.name || '')}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download'))}">${ic('download')}</a>
    <button type="button" class="iconbtn" data-dpv="x" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="dpvtabs" role="tablist" hidden></div>
    <div class="tvbody dpvbody" tabindex="-1"><div class="tvmsg muted">${tr('Loading…')}</div></div>
    <div class="dpvfoot" hidden></div></div>`;
  const body = $('.dpvbody', m), tabs = $('.dpvtabs', m);
  const close = () => { gone = true; m.remove(); if (back?.isConnected) back.focus?.(); };
  const fail = msg => {
    body.innerHTML = `<div class="pvfail dpvfail">${ic('file')}<p>${esc(msg)}</p><a class="btn pri" href="${esc(o.dlUrl || '')}" download="${esc(o.name || '')}">${ic('download')} ${esc(tr('Download'))}</a></div>`;
  };
  const draw = () => {
    if (j.type === 'xlsx') {
      const sh = j.sheets || [];
      tabs.hidden = sh.length < 2;
      tabs.innerHTML = sh.map((s, i) => `<button type="button" role="tab" class="dpvtab${i === sheet ? ' on' : ''}" aria-selected="${i === sheet}" data-dpv="sheet" data-i="${i}">${esc(s.name || tr('Sheet {0}', i + 1))}</button>`).join('')
        + (j.sheets_total > sh.length ? `<span class="muted dpvmore">${esc(tr('+{0} more sheets', j.sheets_total - sh.length))}</span>` : '');
      body.innerHTML = dpvSheetHtml(sh[sheet], false);
    } else body.innerHTML = dpvDocHtml(j);
  };
  m.addEventListener('click', e => {
    if (e.target === m) { close(); return; }
    const b = e.target.closest('[data-dpv]'); if (!b) return;
    if (b.dataset.dpv === 'x') close();
    else if (b.dataset.dpv === 'sheet') { sheet = +b.dataset.i || 0; draw(); $(`.dpvtab[data-i="${sheet}"]`, m)?.focus(); }
  });
  m.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } });
  document.body.appendChild(m);
  $('[data-dpv="x"]', m)?.focus();
  if (o.aid) dpvSumMount(m, o);
  try {
    if (!navigator.onLine) throw new TypeError('offline');
    const r = await fetch(o.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    let d = null; try { d = await r.json(); } catch { d = null; }
    if (gone) return;
    if (!r.ok) { fail(d?.error || (r.status === 404 ? tr('File damaged or missing') : tr('The preview could not be loaded.'))); return; }
    j = d || {}; draw();
  } catch (e) {
    if (!gone) fail(e instanceof TypeError ? tr('The preview needs a connection. You can download the file when you are online again.') : tr('The preview could not be loaded.'));
  }
}

const DPV_AG = new WeakMap();
// ---- "Summarise" (task / comment files only; the slot in a preview's bar, the hint below when no agent can be asked)
async function dpvSumMount(m, o) {
  if (!o?.aid || !feat('comments')) return;
  // the text viewer draws its bar again (Formatted / Source): one question per opened viewer
  let j = DPV_AG.get(m) || null;
  if (!j) { try { j = await rawFetch('GET', `/api/attachments/${encodeURIComponent(o.aid)}/agents`); } catch { return; } DPV_AG.set(m, j); }
  if (!m.isConnected || $('.dpvsum', m) || $('.dpvfoot:not([hidden])', m)) return;  // drawn meanwhile by another call
  const ags = j?.agents || [];
  if (!ags.length) {
    if (typeof agentsOn === 'function' && !agentsOn()) return;
    let foot = $('.dpvfoot', m);
    if (!foot) { foot = document.createElement('div'); foot.className = 'dpvfoot'; $('.tvbox', m)?.appendChild(foot); }
    foot.hidden = false;
    foot.innerHTML = `${ic('bot', 's')}<span>${esc(tr('To have a file summarized, connect an agent (Settings > Agents) and share this project with it.'))}</span>`;
    return;
  }
  const slot = $('.dpvsumslot', m) || $('.tvbar .spacer', m);  // looked up now: the viewer may have drawn its bar again
  if (!slot) return;
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'btn sm dpvsum';
  b.innerHTML = `${ic('bot', 's')}<span>${esc(tr('Summarize'))}</span>`;
  b.title = tr('An agent reads the file and writes a summary as a comment');
  b.setAttribute('aria-label', tr('Summarize'));
  b.addEventListener('click', () => dpvSummarise({...o, task_id: j.task_id}, ags, m));
  slot.classList.contains('spacer') ? slot.after(b) : slot.replaceWith(b);
}

async function dpvSummarise(o, ags, m) {
  let pick = ags[0];
  const many = ags.length > 1;
  const html = (many ? `<p>${esc(tr('Which agent should summarize “{0}”?', o.name))}</p><div class="dpvpick" role="radiogroup">${ags.map((a, i) => `<label class="dpvag"><input type="radio" name="dpvag" value="${a.id}"${i ? '' : ' checked'}><span>${esc(a.name)}</span></label>`).join('')}</div>` : '')
    + `<p class="dpvwho">${esc(tr('The file “{0}” goes to {1}, which writes a summary as a comment on the task.', o.name, pick.name))}</p>`;
  m?.remove();  // the dialog would sit behind the preview
  const ok = await askConfirm(tr('Summarize file'), '', {ok: tr('Summarize'), html, after: md => md.addEventListener('change', e => {
    const r = e.target.closest('input[name="dpvag"]'); if (!r) return;
    pick = ags.find(a => a.id === +r.value) || pick;
    const w = $('.dpvwho', md); if (w) w.textContent = tr('The file “{0}” goes to {1}, which writes a summary as a comment on the task.', o.name, pick.name);
  })});
  if (!ok) return;
  const tid = o.task_id;
  const text = `<@${pick.id}> ` + tr('Please summarize the attachment “{0}” (attachment_id {1}) and post the summary as a comment.', o.name, o.aid);
  const post = async () => (await capi('POST', `/api/tasks/${tid}/comments`, {body: text})).id;
  let cid;
  try { cid = await post(); } catch { return; }
  const redraw = () => { if (S.sel === tid && typeof loadTimeline === 'function') loadTimeline(tid); };
  const undo = async () => { if (cid) await api('DELETE', `/api/comments/${cid}`); cid = null; redraw(); return {skipped: []}; };
  const redo = async () => { cid = await post(); redraw(); return {skipped: []}; };
  redraw();
  const label = tr('{0} was asked for a summary', pick.name);
  histToast(label, histAdd({label, ids: [], undo, redo}));
}
