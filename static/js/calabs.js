// @ts-check
// 2.155.0 B (#2076, #2077): public holidays and absences in the calendar (module "calabs", loaded on demand by the
// "Calendars" window and the event editor). The entries themselves come with the events answer (kalmido/hub/abscal.py)
// and are drawn by calendar.js like other read-only entries (abcX, cvxKey "x:hol" / "x:abs" / "x:team").
// - abc_group: the group "Holidays and absences" of the "Calendars" window: three switches (settings cal_holidays,
//   cal_abs, cal_abs_team; switched through cvxShow), my state of the holidays (setting holiday_state, '' = my area's)
//   and the subscription link of my own absences + holidays (abc_feedModal)
// - 2.240.0 C (#2868): whose busy times colleagues see in their availability bar (setting freebusy_share org | all | off),
//   shown to members of an organisation only (nobody else can ask about a person without one)
// - efb_draw: the availability bar of the event editor (GET /api/events/freebusy): me and every invited colleague, one
//   line from 7 to 20 o'clock (wider when the event is earlier / later), busy spans grey, away hatched, the event's time
//   marked; only spans come from the server, never what they are.
const ABC = {info: /** @type {any} */ (null), loading: false};

async function abc_load(done) {
  if (ABC.loading) return;
  ABC.loading = true;
  try { ABC.info = await api('GET', '/api/team/absences/feed'); } catch { ABC.info = ABC.info || {offline: true}; }
  ABC.loading = false;
  if (done) done();
}

function abc_group() {
  if (S.me?.kid) return '';
  if (!ABC.info && !ABC.loading) setTimeout(() => abc_load(() => { const b = $('#evc-body'); if (b && b.closest('.evcmodal')) b.dispatchEvent(new Event('abc-redraw', {bubbles: true})); }), 0);
  const sw = (k, on, label) => `<label class="swc" title="${esc(label)}"><input type="checkbox" data-cvx="show" data-key="x:${k}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(label)}</span></label>`;
  const st = ABC.info?.states || {}, cur = ABC.info?.state || '';
  // the switch sits in the column "Calendar" of the rows above (invisible stand-ins for Today / Plan / the menu keep it there)
  const pad = '<span class="abchid abcsw" aria-hidden="true"></span>';
  const row = (k, on, name, hint) => `<div class="cvxrow abcrow" style="--cc:var(--muted)"><i class="cevdot"></i><span class="evcn">${esc(name)}${hint ? `<span class="muted"> · ${esc(hint)}</span>` : ''}</span>${sw(k, on, tr('Show {0} in my calendar', name))}${pad}${pad}<span class="iconbtn abchid" aria-hidden="true">${ic('dots')}</span></div>`;
  const team = (S.me?.workspaces || []).length > 0;
  const sel = ABC.info?.states ? `<div class="row abcst"><label for="abc-state">${tr('Holidays of')}</label><select id="abc-state" data-sheet-ico="cal">
      <option value="">${esc(ABC.info.area ? tr('As my organisation ({0})', st[ABC.info.area] || ABC.info.area) : tr('None'))}</option>
      ${Object.entries(st).map(([k, v]) => `<option value="${esc(k)}" ${k === ABC.info.own ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>` : '';
  const fbv = S.settings.freebusy_share || 'org';
  const fbo = [['org', tr('Only calendars of my organisations')], ['all', tr('All my calendars')], ['off', tr('To nobody')]];
  const fb = team ? `<div class="row abcst"><label for="abc-fb">${tr('Show my free / busy times')}</label><select id="abc-fb" data-sheet-ico="cal">
      ${fbo.map(([k, v]) => `<option value="${k}" ${k === fbv ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>
      <span class="muted mhint">${esc(tr('Colleagues only see busy or free, never titles.'))}</span></div>` : '';
  return `<div class="cvxgrp">${tr('Holidays and absences')}</div>
    ${row('hol', S.settings.cal_holidays !== '0', tr('Public holidays'), cur ? st[cur] || cur : tr('no state chosen'))}
    ${row('abs', S.settings.cal_abs !== '0', tr('My absences'), '')}
    ${team ? row('team', S.settings.cal_abs_team === '1', tr('Team absences'), tr('only “away”')) : ''}
    ${sel}${fb}<div class="row abcfeed"><button type="button" class="btn sm" data-abc="feed">${ic('link', 's')} ${tr('Subscription link…')}</button></div>`;
}

// once per "Calendars" window: the state picker, the link button and the redraw after loading
function abc_wire(md, draw) {
  if (md._abc) return;
  md._abc = true;
  md.addEventListener('abc-redraw', () => draw());
  md.addEventListener('change', async e => {
    const t = /** @type {any} */ (e.target);
    if (t.id === 'abc-fb') {  // 2.240.0 C (#2868)
      const was = S.settings.freebusy_share || 'org', to = t.value;
      const put = v => async () => { await cvxSave('freebusy_share', v); const x = $('#abc-fb', md); if (x) x.value = v; };
      await put(to)();
      histAdd({label: tr('Changed setting: {0}', tr('Show my free / busy times')), sett: true, undo: put(was), redo: put(to)});
      return;
    }
    if (t.id !== 'abc-state') return;
    const from = ABC.info?.own || '', to = t.value;
    const put = v => async () => { await cvxSave('holiday_state', v); if (ABC.info) ABC.info.own = v; await abc_load(); cvxRedraw(); draw(); };
    await put(to)();
    histAdd({label: tr('Changed setting: {0}', tr('Public holidays')), sett: true, undo: put(from), redo: put(to)});
  });
  md.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-abc="feed"]')) abc_feedModal(); });
}

async function abc_feedModal() {
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('link', 's')} ${esc(tr('Subscription link'))}</h3><span class="spacer"></span><button class="iconbtn" data-abf="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${esc(tr('My absences and the public holidays of my state, for the calendar app of your phone. Nobody else’s absences are in it; a sick leave shows as “Away”.'))}</p>
    <div id="abf-body"><div class="muted mhint">${esc(tr('Loading…'))}</div></div>
    <p class="muted mhint">${esc(tr('Anyone who has the link sees your absences. Keep it to yourself.'))}</p>
    <div class="foot"><span class="spacer"></span><button class="btn" data-abf="close">${esc(tr('Close'))}</button></div>`);
  md.classList.add('evfmodal');
  const draw = j => {
    const box = $('#abf-body', md); if (!box) return;
    if (!j.url) { box.innerHTML = `<div class="row"><button class="btn pri" data-abf="create">${ic('cal', 's')} ${esc(tr('Create subscription link'))}</button></div>`; return; }
    box.innerHTML = `<div class="row icalrow"><input id="abf-url" readonly value="${esc(j.url)}" aria-label="${esc(tr('Subscription link'))}"><button class="btn pri" data-abf="copy">${ic('copy', 's')} ${esc(tr('Copy'))}</button></div>
      <div class="row evfbtns"><a class="btn" href="${esc(j.url.replace(/^https?:/, 'webcal:'))}">${ic('cal', 's')} ${esc(tr('Open in calendar app'))}</a><button class="btn" data-abf="rotate">${ic('key', 's')} ${esc(tr('New link'))}</button><button class="btn danger" data-abf="off">${esc(tr('Turn the link off'))}</button></div>`;
  };
  try { draw(await api('GET', '/api/team/absences/feed')); } catch { $('#abf-body', md).innerHTML = `<div class="muted mhint">${esc(tr('Only available online.'))}</div>`; }
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-abf]'); if (!b) return;
    const a = b.dataset.abf;
    if (a === 'close') { md.remove(); return; }
    if (a === 'copy') {
      const i = $('#abf-url', md);
      try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); }
      return;
    }
    if (a === 'rotate' && !await askConfirm(tr('Create a new link?'), tr('Calendars subscribed with the old one stop updating.'), {ok: tr('New link'), danger: true})) return;
    if (a === 'off' && !await askConfirm(tr('Turn the link off'), tr('Subscribed calendars stop updating.'), {ok: tr('Turn off'), danger: true})) return;
    b.disabled = true;
    try { draw(await api('POST', '/api/team/absences/feed', {action: a})); } catch { b.disabled = false; return; }
    if (a === 'rotate') toast(tr('New link created, the old one no longer works'));
  });
  return md;
}

// ---- #2077: the availability bar of the event editor
const EFB = {cache: new Map()};
const efb_min = s => { const m = /^(\d{2}):(\d{2})$/.exec(s || ''); return m ? +m[1] * 60 + +m[2] : 0; };

// called by evEditor's drawAtts (attendees changed) and by its own listener (date / time / time zone changed)
function efb_draw(md, atts, ev) {
  if (!feat('events') || S.me?.kid) return;
  if (!md._efb) {
    md._efb = {atts, ev, seq: 0, t: 0};
    md.addEventListener('change', e => { if (/^ev-(sd|stm|etm|ed|allday|tz)$/.test(/** @type {any} */ (e.target).id || '')) efb_draw(md, md._efb.atts, md._efb.ev); });
  }
  md._efb.atts = atts;
  let box = $('#ev-fb', md);
  if (!box) {
    const w = $('#ev-atts', md)?.closest('.evatt-w'); if (!w) return;
    w.insertAdjacentHTML('beforeend', '<div class="efb" id="ev-fb" aria-live="polite"></div>');
    box = $('#ev-fb', md);
  }
  clearTimeout(md._efb.t);
  md._efb.t = setTimeout(() => efb_fetch(md, box), 200);
}

async function efb_fetch(md, box) {
  const val = id => $('#' + id, md)?.value || '';
  const day = val('ev-sd'), ad = !!$('#ev-allday', md)?.checked;
  const ids = [S.me.id, ...md._efb.atts.filter(a => a.user_id && a.user_id !== S.me.id).map(a => a.user_id)].slice(0, 20);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) { box.innerHTML = ''; return; }
  const tz = val('ev-tz') || (typeof evTz === 'function' ? evTz() : '');
  const q = new URLSearchParams({day, users: ids.join(','), ...(tz ? {tz} : {}), ...(md._efb.ev?.id ? {skip: String(md._efb.ev.id)} : {})}).toString();
  const seq = ++md._efb.seq;
  let j = EFB.cache.get(q);
  if (!j) {
    try { j = await calReq('GET', '/api/events/freebusy?' + q); } catch { j = null; }  // no toast: the bar just stays away
    if (j) { EFB.cache.set(q, j); setTimeout(() => EFB.cache.delete(q), 60000); }
  }
  if (seq !== md._efb.seq || !md.isConnected) return;
  if (!j || !j.people?.length) { box.innerHTML = ''; return; }
  // the event's span (minutes of the start day); all day = the whole day
  const s0 = ad ? 0 : efb_min(val('ev-stm')), s1 = ad ? 1440 : (val('ev-ed') > day ? 1440 : Math.max(efb_min(val('ev-etm')), s0 + 15));
  const lo = Math.min(7 * 60, ad ? 7 * 60 : Math.floor(s0 / 60) * 60), hi = Math.max(20 * 60, ad ? 20 * 60 : Math.ceil(s1 / 60) * 60);
  const pct = m => `${(Math.max(lo, Math.min(hi, m)) - lo) / (hi - lo) * 100}%`;
  const wid = (a, b) => `${(Math.max(lo, Math.min(hi, b)) - Math.max(lo, Math.min(hi, a))) / (hi - lo) * 100}%`;
  const name = id => id === S.me.id ? tr('You') : (md._efb.atts.find(a => a.user_id === id)?.name || personNameAny(id));
  const rows = j.people.map(p => {
    const sl = p.slots.map(x => ({a: efb_min(x.start), b: x.end === '24:00' ? 1440 : efb_min(x.end), k: x.kind}));
    const away = sl.some(x => x.k === 'away' && x.a < s1 && x.b > s0), busy = sl.some(x => x.k === 'busy' && x.a < s1 && x.b > s0);
    const st = away ? tr('away') : busy ? tr('busy') : tr('free');
    return `<div class="efbr ${away ? 'away' : busy ? 'busy' : 'free'}"><span class="efbn">${esc(name(p.user_id))}</span><div class="efbt" role="img" aria-label="${esc(tr('{0}: {1} at this time', name(p.user_id), st))}">
      ${sl.filter(x => x.b > lo && x.a < hi).map(x => `<i class="efbb ${x.k}" style="left:${pct(x.a)};width:${wid(x.a, x.b)}"></i>`).join('')}
      <i class="efbsel" style="left:${pct(s0)};width:${wid(s0, s1)}"></i></div><span class="efbs">${esc(st)}</span></div>`;
  }).join('');
  box.innerHTML = `<div class="efbh"><span>${tr('Availability')}</span><span class="muted">${esc(fmtDayAbs(day))} · ${pad(lo / 60)}–${pad(hi / 60)}</span></div>${rows}`;
}
