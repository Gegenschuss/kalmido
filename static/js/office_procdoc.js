// @ts-check
// 2.148.0 C (#2472): the procedure documentation (GoBD) in the office: Bookkeeping -> "Procedure documentation"
// (#office/books/procdoc). Five sections as cards; per field the prefilled text (grey, "from the settings": company, members
// and roles, number ranges, cash books, bank imports, locked months, DATEV, backup, encryption) and the own text (textarea).
// Gaps "[ ... fill in ]" are marked. No autosave here: every save is a new version (a clear button); older versions open read
// only from the version picker; Markdown / PDF of the state shown. Admins write, everybody with office access reads.
// Server: kalmido/office/procdoc.py.
const PD = {oid: null, data: null, versions: null, view: 0, own: {}, err: null, seq: 0, busy: false};

const pdReset = () => Object.assign(PD, {oid: OFC.info?.org_id, data: null, versions: null, view: 0, own: {}, err: null});
async function pdLoad() {
  const seq = ++PD.seq;
  try {
    const q = PD.view ? `?version=${PD.view}` : '';
    const [data, vs] = await Promise.all([api('GET', `/api/office/procdoc${q}`), api('GET', '/api/office/procdoc/versions')]);
    if (seq !== PD.seq) return;
    Object.assign(PD, {data, versions: vs.items || [], err: null});
  } catch (x) { if (seq === PD.seq) PD.err = /** @type {any} */ (x).message || tr('unknown'); }
  ofcDraw();
}
const pdEdit = () => !!(PD.data?.can_edit && !PD.view);
/** @param {string} s */
const pdText = s => esc(s || '').split(esc(PD.data?.gap_marker || '\u0000')).join(`<mark class="pd-gap">${esc(PD.data?.gap_marker || '')}</mark>`);
/** @param {string} iso */
const pdDay = iso => iso ? fmtDateNum(new Date(iso)) : '';  // 2.368.0 B (#2982): one locale source

/** @param {any} f */
function pdField(f) {
  const own = f.key in PD.own ? PD.own[f.key] : f.own, open = !own && (f.need || (f.auto || '').includes(PD.data.gap_marker));
  const auto = f.auto ? `<div class="pd-auto"><span class="pd-src">${tr('from the settings')}</span><div class="pd-txt">${pdText(f.auto)}</div></div>` : '';
  const ownHtml = pdEdit()
    ? `<label class="pd-own"><textarea rows="3" data-pdf="${esc(f.key)}" aria-label="${esc(f.title)}" placeholder="${esc(f.need ? tr('Fill in') : tr('Own addition (optional)'))}">${esc(own)}</textarea></label>`
    : own ? `<div class="pd-txt pd-owntxt">${esc(own)}</div>` : open ? `<div class="pd-txt"><mark class="pd-gap">${esc(PD.data.gap_marker)}</mark></div>` : '';
  return `<div class="pd-field${open ? ' pd-open' : ''}" data-pdk="${esc(f.key)}"><h4 class="pd-ft"><span class="pd-no">${esc(f.no)}</span>${esc(f.title)}</h4>${auto}${ownHtml}</div>`;
}

function pdHtml() {
  if (PD.oid !== OFC.info?.org_id) pdReset();
  if (PD.err) return `<div class="empty">${esc(PD.err)}</div>`;
  if (!PD.data) { if (!PD.loadingT) PD.loadingT = setTimeout(() => { PD.loadingT = 0; pdLoad(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = PD.data, q = PD.view ? `?version=${PD.view}` : '';
  const opts = [['0', tr('Current state')], ...(PD.versions || []).map(v => [String(v.version), tr('Version {0} from {1}', v.version, pdDay(v.created_at)) + (v.created_by ? ` · ${v.created_by}` : '')])];
  const state = PD.view ? tr('Version {0} from {1}, read only', d.viewing, pdDay(d.saved_at))
    : d.version ? tr('Last saved: version {0} from {1}', d.version, pdDay(d.saved_at)) + (d.saved_by ? ` · ${d.saved_by}` : '') : tr('No version saved yet');
  const gaps = PD.view ? 0 : d.sections.reduce((n, s) => n + s.fields.filter(f => !(f.key in PD.own ? PD.own[f.key] : f.own) && (f.need || (f.auto || '').includes(d.gap_marker))).length, 0);
  const head = `<div class="ofcbar pd-bar"><a class="btn sm ghost" href="#office/books">${ic('back', 's')}<span>${tr('Bookkeeping')}</span></a><span class="spacer"></span>
    <a class="btn sm ghost" href="/api/office/procdoc.md${q}" download>${ic('download', 's')}<span>Markdown</span></a><a class="btn sm ghost" href="/api/office/procdoc.pdf${q}" download>${ic('download', 's')}<span>PDF</span></a></div>
    <h2 class="pd-h">${tr('Procedure documentation')}</h2>
    <p class="muted ofchint">${tr('Describes how the bookkeeping works in this office (GoBD).')}${d.version ? '' : ' ' + tr('Kalmido fills in what it knows from the settings; complete the marked gaps and save a version.')}</p>
    <div class="pd-meta"><label class="pd-ver"><span class="muted">${tr('Version')}</span>${ofcSel('pd-ver', String(PD.view), opts)}</label><span class="muted pd-state">${esc(state)}</span>
    ${gaps ? `<span class="pd-gaps">${esc(trn('{0} gap to fill in', '{0} gaps to fill in', gaps))}</span>` : ''}</div>`;
  const body = d.sections.map(s => `<section class="pd-sec" aria-labelledby="pd-s${esc(s.no)}"><h3 class="pd-st" id="pd-s${esc(s.no)}"><span class="pd-no">${esc(s.no)}</span>${esc(s.title)}</h3>${s.fields.map(pdField).join('')}</section>`).join('');
  const foot = pdEdit() ? `<div class="pd-foot"><button type="button" class="btn pri" data-pd="save"${PD.busy ? ' disabled' : ''}>${ic('check', 's')}<span>${tr('Save new version')}</span></button>
    <span class="muted ofchint">${tr('Every save keeps the previous versions readable.')}</span></div>`
    : !PD.view && !d.can_edit ? `<p class="muted ofchint">${tr('Only an admin of this workspace can do this')}</p>` : '';
  return head + body + foot;
}

async function pdSave() {
  if (PD.busy || !PD.data) return;
  const own = {};
  for (const s of PD.data.sections) for (const f of s.fields) { const v = (f.key in PD.own ? PD.own[f.key] : f.own) || ''; if (v.trim()) own[f.key] = v; }
  PD.busy = true; ofcDraw();
  try {
    const d = await api('PUT', '/api/office/procdoc', {own, lang: PD.data.lang, base: PD.data.version});
    Object.assign(PD, {data: d, own: {}});
    PD.versions = (await api('GET', '/api/office/procdoc/versions')).items || [];
    toast(tr('Version {0} saved', d.version));
  } catch (x) { toast(/** @type {any} */ (x).message || tr('unknown')); }
  PD.busy = false; ofcDraw();
}

// ---- events
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-pd]'); if (!b) return;
  if (b.dataset.pd === 'save') { e.preventDefault(); pdSave(); }
});
document.addEventListener('input', e => {
  const x = /** @type {any} */ (e.target); if (!x.dataset?.pdf) return;
  PD.own[x.dataset.pdf] = x.value;
  const f = x.closest('.pd-field'), auto = f?.querySelector('.pd-auto')?.textContent || '';
  const fd = PD.data?.sections.flatMap(s => s.fields).find(y => y.key === x.dataset.pdf);
  if (f && fd) f.classList.toggle('pd-open', !x.value.trim() && (fd.need || auto.includes(PD.data.gap_marker)));
});
document.addEventListener('change', e => {
  const x = /** @type {any} */ (e.target);
  if (x.id === 'pd-ver') { PD.view = +x.value || 0; PD.data = null; ofcDraw(); }
});
