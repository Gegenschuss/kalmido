/* Kalmido web client: The quick-add parser (six languages) and small task helpers: ticket types, milestones, links, repeat rules, reminders, deadlines.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ quick-add parser
// 2.4.0 (#340): ticket types of a task in a list with ticket types on (list setting "tickets"); quick add !bug / !feature /
// !task (German !fehler / !funktion / !aufgabe). New bugs / features with empty notes get the list's template (server).
const TTYPES = [['bug', N_('Bug'), 'bug'], ['feature', N_('Feature'), 'bulb'], ['task', N_('Task|ticket'), 'tsq']];
const TT_WORDS = {bug: 'bug', fehler: 'bug', feature: 'feature', funktion: 'feature', task: 'task', aufgabe: 'task'};
const ticketsOn = lid => !!listById(lid)?.tickets;
// 2.13.0: "Show task numbers" for any list (per device; lists with tickets always show them)
const idsOn = lid => !!LS.get('ids.' + lid, false);
const ticketsAny = () => S.lists.some(l => l.tickets && !l.archived);
const ttName = k => tr((TTYPES.find(x => x[0] === k) || [0, ''])[1]);
const ttChip = t => { const x = TTYPES.find(y => y[0] === t.ttype); return x ? `<span class="ttchip tt-${x[0]}" title="${esc(tr('Type: {0}', tr(x[1])))}">${ic(x[2], 's')}${esc(tr(x[1]))}</span>` : ''; };
// ---- 2.18.0 (#430): milestones are tasks (t.ms = 1): a diamond instead of the round status glyph, top level, no subtasks.
// A task can belong to one milestone of its own list (t.milestone_id): the release / version it ships in.
const isMs = t => !!t?.ms;
const msOfList = lid => [...S.tasks.values()].filter(x => x.ms && x.list_id === lid && !x.deleted_at).sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999') || a.id - b.id);
const msGlyph = t => isMs(t) ? `<i class="msd" aria-hidden="true"></i><span class="sr">${esc(tr('Milestone'))}: </span>` : '';
function msChip(t) {  // the milestone a task belongs to, small (hidden on phones: rows stay calm)
  const m = t.milestone_id && S.tasks.get(t.milestone_id);
  if (m?.deleted_at) return '';  // 2.18.0: a milestone in the trash keeps its link (back on restore) but shows nowhere
  return m ? `<span class="mschip" title="${esc(tr('Milestone') + ': ' + m.title)}"><i class="msd" aria-hidden="true"></i><span class="sr">${esc(tr('Milestone'))}: </span>${esc(m.title)}</span>` : '';
}
// the one list of the multi-selection when "Set milestone" applies (all in one list with an open milestone, none a milestone)
function msBulkList() {
  const ts = [...S.multi].map(i => S.tasks.get(i)).filter(Boolean);
  if (!ts.length || ts.some(isMs) || new Set(ts.map(x => x.list_id)).size !== 1 || !canEditList(ts[0].list_id)) return 0;
  return msOfList(ts[0].list_id).some(m => m.status === 0) ? ts[0].list_id : 0;
}
async function msToggle(id, on) {
  const t = taskById(id); if (!t) return;
  on = on ?? !isMs(t);
  try { await patchUndoable(id, {ms: on ? 1 : 0}, on ? tr('Now a milestone') : tr('Now a normal task')); } catch { renderDetail(); }
}
// the milestone section of a milestone's task panel: GET /api/tasks/<id>/milestone (online), again whenever its tasks change
function msReportHtml(t) {
  const loc = [...S.tasks.values()].filter(x => x.milestone_id === t.id && !x.deleted_at);
  const sig = t.id + '|' + t.title + '|' + t.due + '|' + loc.map(x => x.id + ':' + x.status + ':' + x.ttype + ':' + x.title).join(',');
  if (S.msr?.id !== t.id || (S.msr.sig !== sig && !S.msr.busy)) {
    const keep = S.msr?.id === t.id ? S.msr.j : null;
    S.msr = {id: t.id, sig, busy: true, j: keep, err: false};
    api('GET', `/api/tasks/${t.id}/milestone`).then(j => { if (S.msr?.id === t.id) { S.msr.j = j; S.msr.busy = false; if (S.sel === t.id) renderDetail(); } })
      .catch(() => { if (S.msr?.id === t.id) { S.msr.busy = false; S.msr.err = true; if (S.sel === t.id) renderDetail(); } });
  }
  const j = S.msr.j;
  const tasks = j ? j.tasks : loc.map(x => ({id: x.id, title: x.title, status: x.status === 2 ? 'done' : x.status === -1 ? 'wont_do' : 'open'})).sort((a, b) => (a.status !== 'open') - (b.status !== 'open'));
  const total = tasks.length, done = tasks.filter(x => x.status !== 'open').length, pct = total ? Math.round(100 * done / total) : 0;
  const prog = `<div class="msprog"><div class="msbar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="${esc(tr('Progress'))}"><i style="width:${pct}%"></i></div><span class="msnum">${esc(tr('{0} of {1} done', done, total))}</span></div>`;
  const list = total ? `<ul class="mstasks">${tasks.map(x => `<li class="${x.status !== 'open' ? 'done' : ''}"><span class="mst-st" aria-hidden="true">${x.status === 'done' ? ic('check', 's') : x.status === 'wont_do' ? ic('x', 's') : ''}</span><button type="button" class="linkbtn" data-act="ms-open" data-id="${x.id}">${esc(x.title)}${x.status !== 'open' ? `<span class="sr"> (${esc(x.status === 'done' ? tr('done') : tr("Won't do"))})</span>` : ''}</button></li>`).join('')}</ul>`
    : `<div class="muted msempty">${tr('No tasks yet. Choose this milestone in a task of the list, or select several tasks and use “Set milestone”.')}</div>`;
  const off = !j ? `<div class="muted msempty">${S.msr.err ? tr('Burndown and release notes are available online.') : tr('Loading…')}</div>` : '';
  const bd = j && total ? `<h6>${tr('Burndown')}</h6>${msBurnSvg(j.burndown, total)}<details class="msbtab"><summary>${tr('Show as table')}</summary><table><thead><tr><th scope="col">${tr('Day')}</th><th scope="col">${tr('Open tasks')}</th></tr></thead><tbody>${j.burndown.days.map(d => `<tr><td>${esc(fmtDate(d.day))}</td><td>${d.open}</td></tr>`).join('')}</tbody></table></details>` : '';
  const rn = j ? `<div class="msrnh"><h6>${tr('Release notes')}</h6><button type="button" class="btn sm" data-act="ms-copy" aria-label="${esc(tr('Copy release notes'))}">${ic('copy', 's')}<span>${tr('Copy')}</span></button></div><div class="md msrn">${renderMd(j.release_notes, true)}</div>` : '';
  return `<h5>${tr('Milestone')}</h5>${t.due ? '' : `<div class="muted msnodate"><i class="msd" aria-hidden="true"></i>${tr('No date yet: set one with the date button above.')}</div>`}${prog}${list}${off}${bd}${rn}`;
}
function msBurnSvg(b, total) {
  const days = b.days || []; if (!days.length) return '';
  // 2.18.0 review (R9): one day of history is only a dot at the start of the ideal line: a note says why
  const few = days.length < 2 ? `<div class="muted msempty msbnone">${esc(tr('Not enough history yet: the line grows from tomorrow on.'))}</div>` : '';
  const end = b.due && b.due > b.end ? b.due : b.end, n = Math.max(1, diffDays(b.start, end)), W = 300, H = 100, P = 4;
  const max = Math.max(1, total, ...days.map(d => d.open));
  const X = d => (P + Math.max(0, diffDays(b.start, d)) / n * (W - 2 * P)).toFixed(1), Y = v => (H - P - v / max * (H - 2 * P)).toFixed(1);
  const pts = days.length > 1 ? days.map(d => `${X(d.day)},${Y(d.open)}`).join(' ') : `${X(days[0].day)},${Y(days[0].open)} ${(+X(days[0].day) + 2).toFixed(1)},${Y(days[0].open)}`;
  const id = b.ideal || [], last = days[days.length - 1].open;
  const lab = tr('Burndown: {0} of {1} tasks open on {2}', last, total, fmtDate(b.end)) + (b.due ? ' · ' + tr('Due: {0}', fmtDate(b.due)) : '');
  return `<svg class="msburn" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(lab)}"><line class="msb-ax" x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}"/>${id.length === 2 ? `<line class="msb-ideal" x1="${X(id[0].day)}" y1="${Y(id[0].open)}" x2="${X(id[1].day)}" y2="${Y(id[1].open)}"/>` : ''}<polyline class="msb-act" points="${pts}"/></svg><div class="msblg" aria-hidden="true"><span class="lg-act">${tr('Open tasks')}</span>${id.length === 2 ? `<span class="lg-ideal">${tr('Ideal')}</span>` : ''}</div>${few}`;
}
const PRIO_WORDS = {'!!!': 5, '!3': 5, '!hoch': 5, '!high': 5, '!!': 3, '!2': 3, '!mittel': 3, '!medium': 3, '!': 1, '!1': 1, '!niedrig': 1, '!low': 1};
const WDAY = {sonntag: 0, montag: 1, dienstag: 2, mittwoch: 3, donnerstag: 4, freitag: 5, samstag: 6,
  sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6};
const WDAY_RE = Object.keys(WDAY).join('|');
function nextWeekday(wd, fromNextWeek) {
  const t = pd(today()); let d = (wd - t.getDay() + 7) % 7; if (d === 0) d = 7;
  if (fromNextWeek && d < 7) { const mon = pd(mondayOf(today())); mon.setDate(mon.getDate() + 7 + ((wd + 6) % 7)); return ds(mon); }
  return addDays(today(), d);
}
// 2.12.0: quick add in French, Spanish, Italian and Dutch. English and German words always work (as before); the words of
// these four only while the app runs in that language (a Spanish "domingo" in an English title stays text). Regex parts,
// matched case-insensitively between spaces. Priority, tags and the list stay symbols (!!! / #tag / ~list) in every language.
//   wd: weekday names (Sunday first, like Date.getDay()), pre: "on / this <weekday>", next / nextPost: "next <weekday>" /
//   "<weekday> next", inN + one + units: "in 3 days" / "in a week", at / atH: times ("à 15h30", "a las 9", "om 15 uur"),
//   rep: repeat words (daily, weekdays, weekly, monthly, yearly; every: "every <weekday>", everyN: "every 2 weeks")
const QL = {
  fr: {today: "aujourd['’]hui", tomorrow: 'demain', after: 'après-demain', nextWeek: '(?:la )?semaine prochaine', nextMonth: '(?:le )?mois prochain', weekend: '(?:ce |le )?week-end',
    wd: ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'], pre: 'le|ce', next: '', nextPost: 'prochain',
    inN: 'dans', one: 'une?', units: ['jours?', 'semaines?', 'mois'], at: 'à', atH: true, datePre: 'le',
    rep: {daily: 'tous les jours|chaque jour|quotidiennement', weekdays: 'en semaine|chaque jour ouvré|les jours ouvrés', weekly: 'chaque semaine|toutes les semaines|hebdomadaire',
      monthly: 'chaque mois|tous les mois|mensuellement', yearly: 'chaque année|tous les ans|annuellement', every: '(?:chaque|tous les)', everyN: '(?:tous|toutes) les', unitsN: ['jours', 'semaines', 'mois']}},
  es: {today: 'hoy', tomorrow: 'mañana', after: 'pasado mañana', nextWeek: '(?:la )?(?:próxima semana|semana que viene)', nextMonth: '(?:el )?(?:próximo mes|mes que viene)', weekend: '(?:este |el )?fin de semana',
    wd: ['domingo', 'lunes', 'martes', 'mi[ée]rcoles', 'jueves', 'viernes', 's[áa]bado'], pre: 'el|este', next: '(?:el )?próximo', nextPost: 'que viene',
    inN: 'en|dentro de', one: 'una?', units: ['d[íi]as?', 'semanas?', 'mes(?:es)?'], at: 'a las?', atH: false, datePre: 'el',
    rep: {daily: 'todos los días|cada día|a diario|diariamente', weekdays: 'entre semana|cada día laborable|días laborables', weekly: 'cada semana|todas las semanas|semanalmente',
      monthly: 'cada mes|todos los meses|mensualmente', yearly: 'cada año|todos los años|anualmente', every: '(?:cada|todos los)', everyN: 'cada', unitsN: ['días', 'semanas', 'meses']}},
  it: {today: 'oggi', tomorrow: 'domani', after: 'dopodomani', nextWeek: '(?:la )?(?:settimana prossima|prossima settimana)', nextMonth: '(?:il )?(?:mese prossimo|prossimo mese)', weekend: '(?:questo |il |nel )?fine settimana',
    wd: ['domenica', 'luned[ìi]', 'marted[ìi]', 'mercoled[ìi]', 'gioved[ìi]', 'venerd[ìi]', 'sabato'], pre: 'il|la|questo|questa', next: 'prossim[oa]', nextPost: 'prossim[oa]',
    inN: 'tra|fra', one: 'una?', units: ['giorni|giorno', 'settimane|settimana', 'mesi|mese'], at: 'alle(?: ore)?', atH: false, datePre: 'il',
    rep: {daily: 'ogni giorno|tutti i giorni|quotidianamente', weekdays: 'nei giorni feriali|ogni giorno feriale|giorni feriali', weekly: 'ogni settimana|settimanalmente',
      monthly: 'ogni mese|mensilmente', yearly: 'ogni anno|annualmente', every: 'ogni', everyN: 'ogni', unitsN: ['giorni', 'settimane', 'mesi']}},
  nl: {today: 'vandaag', tomorrow: 'morgen', after: 'overmorgen', nextWeek: 'volgende week', nextMonth: 'volgende maand', weekend: '(?:dit |het )?weekend',
    wd: ['zondag', 'maandag', 'dinsdag', 'woensdag', 'donderdag', 'vrijdag', 'zaterdag'], pre: 'op|deze', next: 'volgende|aanstaande', nextPost: '',
    inN: 'over', one: 'een|één', units: ['dagen|dag', 'weken|week', 'maanden|maand'], at: 'om', atH: false, uur: true, datePre: 'op',
    rep: {daily: 'dagelijks|elke dag|iedere dag', weekdays: 'elke werkdag|op werkdagen|doordeweeks', weekly: 'wekelijks|elke week|iedere week',
      monthly: 'maandelijks|elke maand|iedere maand', yearly: 'jaarlijks|elk jaar|ieder jaar', every: '(?:elke|iedere)', everyN: '(?:elke|iedere|om de)', unitsN: ['dagen', 'weken', 'maanden']}},
};
// the weekday number of a name matched by one of the QL patterns
const qlWd = (L, w) => L.wd.findIndex(p => new RegExp(`^(?:${p})$`, 'i').test(w));
function parseQuick(text, ignore = new Set()) {
  const out = {title: text, chips: []};
  let s = ' ' + text + ' ';
  const take = (re, type, fn) => {
    if (ignore.has(type)) { const m = s.match(re); if (m) out.chips.push({type, label: m[0].trim(), off: true}); return; }
    const m = s.match(re);
    if (m) { const label = fn(m); if (label !== false) { out.chips.push({type, label}); s = s.replace(m[0], ' '); } }
  };
  // website link: the first http(s) URL goes into the link field, not the title
  take(/\s(https?:\/\/[^\s]+)(?=\s)/i, 'link', m => { out.url = m[1].replace(/[.,;:!?]+$/, ''); return urlHost(out.url); });
  // repeat (before dates, "jeden montag" contains a weekday)
  take(new RegExp(`\\s(täglich|jeden tag|daily|every day|werktags|jeden werktag|weekdays|every weekday|wöchentlich|jede woche|weekly|every week|monatlich|jeden monat|monthly|every month|jährlich|jedes jahr|yearly|annually|every year|(?:jeden|every) (${WDAY_RE})|(?:alle|every) (\\d+) (tage|wochen|monate|days?|weeks?|months?))(?=\\s)`, 'i'), 'repeat', m => {
    const w = m[1].toLowerCase();
    if (/täglich|jeden tag|daily|every day/.test(w)) out.repeat = 'FREQ=DAILY';
    else if (/werktag|weekday/.test(w)) { out.repeat = 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'; }
    else if (m[2]) { const wd = WDAY[m[2].toLowerCase()]; out.repeat = 'FREQ=WEEKLY;BYDAY=' + RR_WD[wd]; out.due = out.due || nextOrToday(wd); }
    else if (m[3]) { const n = +m[3], u = m[4].toLowerCase(); out.repeat = `FREQ=${u.startsWith('tag') || u.startsWith('day') ? 'DAILY' : u.startsWith('woche') || u.startsWith('week') ? 'WEEKLY' : 'MONTHLY'};INTERVAL=${n}`; }
    else if (/woch|week/.test(w)) out.repeat = 'FREQ=WEEKLY';
    else if (/monat|month/.test(w)) out.repeat = 'FREQ=MONTHLY';
    else out.repeat = 'FREQ=YEARLY';
    return repeatLabel(out.repeat);
  });
  const L = QL[I18N.code] || null, dayIn = (n, u) => { const d = pd(today()); if (u === 0) d.setDate(d.getDate() + n); else if (u === 1) d.setDate(d.getDate() + 7 * n); else d.setMonth(d.getMonth() + n); return ds(d); };
  const unitOf = (us, w) => us.findIndex(p => new RegExp(`^(?:${p})$`, 'i').test(w));
  if (L) {  // 2.12.0: repeat, dates and times in the app language (fr / es / it / nl), before the English / German ones
    const R = L.rep, WDS = L.wd.join('|');
    take(new RegExp(`\\s(${R.daily}|${R.weekdays}|${R.weekly}|${R.monthly}|${R.yearly}|${R.every} (${WDS})s?|${R.everyN} (\\d+) (${R.unitsN.join('|')}))(?=\\s)`, 'i'), 'repeat', m => {
      const w = m[1];
      if (m[2]) { const wd = qlWd(L, m[2]); out.repeat = 'FREQ=WEEKLY;BYDAY=' + RR_WD[wd]; out.due = out.due || nextOrToday(wd); }
      else if (m[3]) { const u = unitOf(R.unitsN, m[4]); out.repeat = `FREQ=${['DAILY', 'WEEKLY', 'MONTHLY'][u]};INTERVAL=${+m[3]}`; }
      else out.repeat = [[R.daily, 'FREQ=DAILY'], [R.weekdays, 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'], [R.weekly, 'FREQ=WEEKLY'], [R.monthly, 'FREQ=MONTHLY'], [R.yearly, 'FREQ=YEARLY']]
        .find(([re]) => new RegExp(`^(?:${re})$`, 'i').test(w))[1];
      return repeatLabel(out.repeat);
    });
    take(new RegExp(`\\s(${L.after}|${L.today}|${L.tomorrow})(?=\\s)`, 'i'), 'date', m => {
      const w = m[1].toLowerCase();
      out.due = new RegExp(`^(?:${L.after})$`, 'i').test(w) ? addDays(today(), 2) : new RegExp(`^(?:${L.tomorrow})$`, 'i').test(w) ? addDays(today(), 1) : today();
      return dayLabel(out.due);
    });
    if (!out.due || ignore.has('date')) take(new RegExp(`\\s(${L.nextWeek})(?=\\s)`, 'i'), 'date', () => { out.due = nextWeekday(1); return dayLabel(out.due); });
    if (!out.due || ignore.has('date')) take(new RegExp(`\\s(${L.nextMonth})(?=\\s)`, 'i'), 'date', () => { const d = pd(today()); d.setMonth(d.getMonth() + 1, 1); out.due = ds(d); return dayLabel(out.due); });
    if (!out.due || ignore.has('date')) take(new RegExp(`\\s(${L.weekend})(?=\\s)`, 'i'), 'date', () => { out.due = nextOrToday(6); return dayLabel(out.due); });
    if (!out.due || ignore.has('date')) take(new RegExp(`\\s(?:(${[L.pre, L.next].filter(Boolean).join('|')})\\s)?(${WDS})(?:\\s(${L.nextPost || '(?!)'}))?(?=\\s)`, 'i'), 'date', m => {
      const wd = qlWd(L, m[2]), nx = (L.next && m[1] && new RegExp(`^(?:${L.next})$`, 'i').test(m[1])) || !!m[3];
      out.due = nx ? nextWeekday(wd, true) : nextWeekday(wd); return dayLabel(out.due);
    });
    if (!out.due || ignore.has('date')) take(new RegExp(`\\s(?:${L.inN}) (\\d+|${L.one}) (${L.units.join('|')})(?=\\s)`, 'i'), 'date', m => {
      const n = /^\d+$/.test(m[1]) ? +m[1] : 1; out.due = dayIn(n, unitOf(L.units, m[2])); return dayLabel(out.due);
    });
  }
  // 2.12.0: day / month with a slash (3/10, 3/10/27), in every language (day first, like the dotted 3.10.)
  if (!out.due || ignore.has('date')) take(new RegExp(`\\s(?:(?:${L ? L.datePre : 'am|on'})\\s)?(\\d{1,2})/(\\d{1,2})(?:/(\\d{2}|\\d{4}))?(?=\\s)`, 'i'), 'date', m => {
    const t = pd(today()); let y = m[3] ? +m[3] : t.getFullYear(); if (y < 100) y += 2000;
    if (+m[2] < 1 || +m[2] > 12) return false;
    const d = new Date(y, +m[2] - 1, +m[1]); if (isNaN(d) || d.getDate() !== +m[1]) return false;
    if (!m[3] && ds(d) < today()) d.setFullYear(y + 1);
    out.due = ds(d); return dayLabel(out.due);
  });
  if (L) {  // times: "à 15h30", "15h", "a las 9", "alle 15:30", "om 15 uur"
    const hm = (h, mi) => { h = +h; mi = +(mi || 0); if (h > 23 || mi > 59) return false; out.due_time = `${pad(h)}:${pad(mi)}`; out.due = out.due || (out.due_time < nowHM() ? addDays(today(), 1) : today()); return out.due_time; };
    if (L.atH) take(new RegExp(`\\s(?:(?:${L.at})\\s)?(\\d{1,2})\\s?h(\\d{2})?(?=\\s)`, 'i'), 'time', m => hm(m[1], m[2]));
    if (L.uur) take(new RegExp(`\\s(?:(?:${L.at})\\s)?(\\d{1,2})(?::(\\d{2}))?\\s?uur(?=\\s)`, 'i'), 'time', m => hm(m[1], m[2]));
    take(new RegExp(`\\s(?:${L.at})\\s(\\d{1,2})(?:[:h](\\d{2}))?(?=\\s)`, 'i'), 'time', m => hm(m[1], m[2]));
  }
  take(/\s(übermorgen|(?:the )?day after tomorrow|heute|morgen|today|tomorrow)(?=\s)/i, 'date', m => {
    const w = m[1].toLowerCase();
    out.due = w === 'übermorgen' || w.endsWith('after tomorrow') ? addDays(today(), 2) : (w === 'morgen' || w === 'tomorrow') ? addDays(today(), 1) : today();
    return dayLabel(out.due);
  });
  if (!out.due || ignore.has('date')) take(/\s(nächste woche|next week)(?=\s)/i, 'date', () => { out.due = nextWeekday(1); return dayLabel(out.due); });
  if (!out.due || ignore.has('date')) take(/\s(nächsten monat|next month)(?=\s)/i, 'date', () => { const d = pd(today()); d.setMonth(d.getMonth() + 1, 1); out.due = ds(d); return dayLabel(out.due); });
  if (!out.due || ignore.has('date')) take(/\s(am |this |on the |next )?(wochenende|weekend)(?=\s)/i, 'date', () => { out.due = nextOrToday(6); return dayLabel(out.due); });
  if (!out.due || ignore.has('date')) take(new RegExp(`\\s(?:(am|nächsten|nächste|kommenden|next|on|this)\\s)?(${WDAY_RE})(?=\\s)`, 'i'), 'date', m => {
    const wd = WDAY[m[2].toLowerCase()]; out.due = /nächst|kommend|next/i.test(m[1] || '') ? nextWeekday(wd, true) : nextWeekday(wd); return dayLabel(out.due);
  });
  if (!out.due || ignore.has('date')) take(/\sin (\d+|an?) (tagen|tag|wochen|woche|monaten|monat|days?|weeks?|months?)(?=\s)/i, 'date', m => {
    const n = /^an?$/i.test(m[1]) ? 1 : +m[1], u = m[2].toLowerCase(); const d = pd(today());
    if (/^(tag|day)/.test(u)) d.setDate(d.getDate() + n); else if (/^(woch|week)/.test(u)) d.setDate(d.getDate() + 7 * n); else d.setMonth(d.getMonth() + n);
    out.due = ds(d); return dayLabel(out.due);
  });
  if (!out.due || ignore.has('date')) take(/\s(?:am\s)?(\d{1,2})\.(\d{1,2})\.(\d{2,4})?(?=\s)/, 'date', m => {
    const t = pd(today()); let y = m[3] ? +m[3] : t.getFullYear(); if (y < 100) y += 2000;
    const d = new Date(y, +m[2] - 1, +m[1]); if (isNaN(d) || d.getDate() !== +m[1]) return false;
    if (!m[3] && ds(d) < today()) d.setFullYear(y + 1);
    out.due = ds(d); return dayLabel(out.due);
  });
  if (!out.due_time) take(/\s(?:um\s)?(\d{1,2})(?::(\d{2}))?\s?uhr(?=\s)|\sum\s(\d{1,2})(?::(\d{2}))?(?=\s)|\s(?:at\s)?(\d{1,2}):(\d{2})(?=\s)|\s(?:at\s)?(\d{1,2})(?::(\d{2}))?\s?(am|pm)(?=\s)/i, 'time', m => {
    let h = +(m[1] ?? m[3] ?? m[5] ?? m[7]), mi = +(m[2] ?? m[4] ?? m[6] ?? m[8] ?? 0);
    if (m[9]) { if (m[9].toLowerCase() === 'pm' && h < 12) h += 12; if (m[9].toLowerCase() === 'am' && h === 12) h = 0; }
    if (h > 23 || mi > 59) return false;
    out.due_time = `${pad(h)}:${pad(mi)}`; out.due = out.due || (out.due_time < nowHM() ? addDays(today(), 1) : today());
    return out.due_time;
  });
  // 2.4.0 (#340): ticket type, only while some list has ticket types on
  if (ticketsAny() || ignore.has('ttype')) take(/\s!(bug|feature|task|fehler|funktion|aufgabe)(?=\s)/i, 'ttype', m => { out.ttype = TT_WORDS[m[1].toLowerCase()]; return ttName(out.ttype); });
  // 2.18.0 (#430): !milestone / !meilenstein / !ms makes the new task a milestone
  take(/\s!(milestone|meilenstein|ms)(?=\s)/i, 'ms', () => { out.ms = 1; return tr('Milestone'); });
  // 2.22.0 (#686): waiting on external right away: wartet:Kunde / waiting:client (a word, "in quotes" or with_underscores)
  take(/\s(?:wartet|waiting|attend|espera|attesa|wacht):(?:"([^"]+)"|“([^”]+)”|„([^“”]+)[“”]|([^\s"“„]+))(?=\s)/i, 'wait', m => {
    out.wait = (m[1] || m[2] || m[3] || m[4] || '').replace(/_/g, ' ').trim().slice(0, 300); return out.wait ? '⏳ ' + out.wait : false;
  });
  // priority: standalone token
  take(/\s(!!!|!!|!hoch|!mittel|!niedrig|!high|!medium|!low|![123]|!)(?=\s)/i, 'prio', m => { out.priority = PRIO_WORDS[m[1].toLowerCase()]; return tr(['', N_('Low'), '', N_('Medium'), '', N_('High')][out.priority]); });
  // tags
  if (!ignore.has('tag')) {
    out.tags = [];
    s = s.replace(/\s#([\p{L}\p{N}_\-/]+)(?=\s)/gu, (_, t) => { out.tags.push(t); out.chips.push({type: 'tag', label: '#' + t}); return ' '; });
  }
  // list: ~Name (prefix match, ignores emoji / case)
  take(/\s[~^]([^\s]+)(?=\s)/, 'list', m => {
    const q = norm(m[1]); const nm = x => norm(lname(x)) + ' ' + norm(x.name);  // display name (inbox: "Inbox" in English) or stored name
    const W = S.lists.filter(x => canAddTo(x.id));
    const l = W.find(x => norm(lname(x)).startsWith(q) || norm(x.name).startsWith(q)) || W.find(x => nm(x).includes(q));
    if (!l) return false; out.list_id = l.id; return lname(l);
  });
  // 2.0.0 (#277): the list in plain words (see quickListWords)
  if (out.list_id === undefined && !out.chips.some(c => c.type === 'list')) {
    const hit = quickListWords(s);
    if (hit && ignore.has('list')) out.chips.push({type: 'list', label: hit.phrase, off: true});
    else if (hit) { out.list_id = hit.list.id; out.chips.push({type: 'list', label: lname(hit.list)}); s = s.slice(0, hit.start) + ' ' + s.slice(hit.end); }
  }
  if (out.repeat && !out.due) out.due = today();
  out.title = s.replace(/\s+/g, ' ').trim();
  return out;
}
// 2.0.0 (#277): "Liste X" / "in Liste X" / "list X" / "to list X" anywhere (X = a list name; after "Liste" or a preposition
// also the start of one, at least 3 letters, when only one list fits), and "in X" / "auf X" / "into X" at the very END only
// when X is exactly the name of a list the task can go to (emoji / case ignored, several words allowed) -- "Letter to grandma
// in Berlin" stays text unless a list is called "Berlin". Returns {list, start, end, phrase} (positions in s) or null.
function quickListWords(s) {
  const W = S.lists.filter(x => canAddTo(x.id) && !x.archived);
  if (!W.length) return null;
  const words = l => lname(l).split(/\s+/).filter(w => norm(w));
  const toks = [...s.matchAll(/\S+/g)].map(m => ({w: m[0], i: m.index, e: m.index + m[0].length}));
  const eqAt = (j, l) => { const nw = words(l); return nw.length && j + nw.length <= toks.length && norm(toks.slice(j, j + nw.length).map(t => t.w).join('')) === norm(nw.join('')) ? nw.length : 0; };
  const hit = (a, j, n, l) => ({list: l, start: toks[a].i, end: toks[j + n - 1].e, phrase: s.slice(toks[a].i, toks[j + n - 1].e)});
  const PREP = /^(in|auf|to|into|zur|onto)$/i, ART = /^(die|der|the|meine|my)$/i;
  for (let k = 0; k < toks.length - 1; k++) {
    if (!/^(liste|list)$/i.test(toks[k].w)) continue;
    let a = k;
    if (a > 1 && ART.test(toks[a - 1].w) && PREP.test(toks[a - 2].w)) a -= 2;
    else if (a > 0 && PREP.test(toks[a - 1].w)) a--;
    if (a === 0) continue;  // "Liste Einkauf" alone is a title, not a list choice
    const j = k + 1;
    let best = null;
    for (const l of W) { const n = eqAt(j, l); if (n && (!best || n > best.n)) best = {l, n}; }
    if (!best && (a < k || /^liste$/i.test(toks[k].w))) {
      const q = norm(toks[j].w), fit = q.length >= 3 ? W.filter(x => norm(lname(x)).startsWith(q) || norm(x.name).startsWith(q)) : [];
      if (fit.length === 1) best = {l: fit[0], n: 1};
    }
    if (best) return hit(a, j, best.n, best.l);
  }
  let best = null;
  for (const l of W) {
    const n = words(l).length, j = toks.length - n;
    if (n && j >= 2 && /^(in|auf|into)$/i.test(toks[j - 1].w) && eqAt(j, l) && (!best || n > best.n)) best = {l, n, j};
  }
  return best ? hit(best.j - 1, best.j, best.n, best.l) : null;
}
// leading emoji of a list name gets a space after it ("🌀3D" -> "🌀 3D"), display only
const listName = n => String(n ?? '').replace(/^((?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\uFE0F|\u200D)+)\s*/u, '$1 ');
// display name of a list object: an inbox with its default name ("Eingang" before 2.15, since then "Inbox" in its owner's
// language, #632: S.inboxNames) is shown in the UI language
const inboxDef = n => n === 'Eingang' || (S.inboxNames || []).includes(n);
const lname = l => !l ? '' : l.is_inbox && inboxDef(l.name) ? tr('Inbox') : listName(l.name);
const norm = s => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
// website link display: domain without www. (chip), domain + path (title of a bare shared link)
const urlParse = u => { try { return new URL(u); } catch { return null; } };
const urlHost = u => { const x = urlParse(u); return x ? x.hostname.replace(/^www\./, '') : String(u || ''); };
const urlTitle = u => { const x = urlParse(u); return x ? (x.hostname.replace(/^www\./, '') + x.pathname.replace(/\/+$/, '')).slice(0, 120) : String(u || '').slice(0, 120); };
// shared text -> [link, text without it]: the first http(s) URL, trailing punctuation is not part of it
function shareLink(text, url) {
  text = String(text || '');
  const clean = s => s.replace(/\s+/g, ' ').trim().replace(/^[-–—|:·\s]+|[-–—|:·\s]+$/g, '');
  if (url) return [url, clean(text.replace(url, ''))];
  const m = text.match(/https?:\/\/\S+/);
  if (!m) return ['', clean(text)];
  return [m[0].replace(/[.,;:!?]+$/, ''), clean(text.slice(0, m.index) + text.slice(m.index + m[0].length))];
}
const validUrl = u => /^https?:\/\/[^\s/?#]+\S*$/i.test(u || '') && u.length <= 2000;
const nowHM = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
function nextOrToday(wd) { const t = pd(today()); return addDays(today(), (wd - t.getDay() + 7) % 7); }

const rrParts = r => Object.fromEntries((r || '').replace(/^RRULE:/, '').split(';').filter(Boolean).map(x => x.split('=')));
const rrBase = r => (r || '').replace(/^RRULE:/, '').split(';').filter(x => x && !/^(COUNT|UNTIL)=/.test(x)).join(';');
function rrEnd(r) {
  const p = rrParts(r);
  if (p.COUNT) return {type: 'count', val: +p.COUNT};
  if (p.UNTIL) return {type: 'until', val: `${p.UNTIL.slice(0, 4)}-${p.UNTIL.slice(4, 6)}-${p.UNTIL.slice(6, 8)}`};
  return {type: 'never'};
}
// the custom repeat form (U06): every n days / weeks / months / years, weekdays for weeks; extra = parts it cannot show
function rrForm(base) {
  const p = {}; for (const x of String(base || '').split(';')) { const [k, v] = x.split('='); if (k) p[k] = v; }
  const f = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].includes(p.FREQ) ? p.FREQ : 'WEEKLY';
  const extra = Object.keys(p).some(k => !['FREQ', 'INTERVAL', 'BYDAY', 'WKST'].includes(k)) || (p.BYDAY && (f !== 'WEEKLY' || /\d/.test(p.BYDAY)));
  return {f, n: Math.max(1, +p.INTERVAL || 1), days: new Set(f === 'WEEKLY' && p.BYDAY && !/\d/.test(p.BYDAY) ? p.BYDAY.split(',') : []), extra, raw: base};
}
function rrBuild(cu) {
  if (cu.extra) return cu.raw;
  const days = RR_WD.filter(d => cu.days.has(d));
  return `FREQ=${cu.f}${cu.n > 1 ? `;INTERVAL=${cu.n}` : ''}${cu.f === 'WEEKLY' && days.length ? `;BYDAY=${days.join(',')}` : ''}`;
}
function rrSetEnd(r, end) {
  const b = rrBase(r); if (!b) return '';
  if (end.type === 'count') return `${b};COUNT=${Math.max(1, Math.min(999, +end.val || 1))}`;
  if (end.type === 'until' && end.val) return `${b};UNTIL=${end.val.replace(/-/g, '')}`;
  return b;
}
function repeatLabel(r) {
  if (!r) return '';
  const e = rrEnd(r);
  const suffix = e.type === 'count' ? ' · ' + tr('{0}× left', e.val) : e.type === 'until' ? ' · ' + tr('until {0}', fmtDate(e.val)) : '';
  return repeatLabelBase(rrBase(r)) + suffix;
}
function repeatLabelBase(r) {
  if (!r) return '';
  const p = Object.fromEntries(r.replace(/^RRULE:/, '').split(';').map(x => x.split('=')));
  const n = +(p.INTERVAL || 1);
  const days = p.BYDAY ? p.BYDAY.split(',').map(d => WD[RR_WD.indexOf(d.replace(/^[-\d]+/, ''))]).join(', ') : '';
  if (p.FREQ === 'DAILY') return n === 1 ? tr('Daily') : tr('Every {0} days', n);
  if (p.FREQ === 'WEEKLY') {
    if (p.BYDAY === 'MO,TU,WE,TH,FR') return tr('Weekdays');
    return (n === 1 ? tr('Weekly') : tr('Every {0} weeks', n)) + (days ? ` (${days})` : '');
  }
  if (p.FREQ === 'MONTHLY') return (n === 1 ? tr('Monthly') : tr('Every {0} months', n)) + (p.BYMONTHDAY ? ' ' + tr('on day {0}', p.BYMONTHDAY) : '');
  if (p.FREQ === 'YEARLY') return n === 1 ? tr('Yearly') : tr('Every {0} years', n);
  return tr('Repeats');
}
const REM_OPTS = [['0', N_('On time')], ['5', N_('5 min before')], ['15', N_('15 min')], ['30', N_('30 min')], ['60', N_('1 h')], ['120', N_('2 h')], ['1440', N_('1 day')], ['2880', N_('2 days')], ['10080', N_('1 week')],
  ['20160', N_('2 weeks')], ['43200', N_('1 month')]];  // 2.7.0 (#412): up to a month in the presets, anything up to a year via "Other…"
// ---- 2.7.0 (#412): reminders are minutes before the due time, from 0 up to 366 days (the server's limit). The date
// popover offers the common ones as chips and "Other…" for any number of minutes / hours / days / weeks.
const REM_CHIPS = ['0', '15', '60', '1440', '10080', '20160', '43200'];
const REM_MAX = 366 * 1440;
const REM_UNITS = [['1', N_('minutes')], ['60', N_('hours')], ['1440', N_('days')], ['10080', N_('weeks')]];
function remDur(m) {  // "3 weeks", "90 minutes"
  const a = Math.abs(+m);
  return a % 10080 === 0 ? trn('{0} week', '{0} weeks', a / 10080) : a % 1440 === 0 ? trn('{0} day', '{0} days', a / 1440) : a % 60 === 0 ? trn('{0} hour', '{0} hours', a / 60) : trn('{0} minute', '{0} minutes', a);
}
const fmtRem = m => !+m ? tr('On time') : +m < 0 ? tr('{0} after', remDur(m)) : tr('{0} before', remDur(m));
const fmtNum = (n, d = 1) => (+n).toLocaleString(LOCALE(), {maximumFractionDigits: d});
const remChip = v => { const o = REM_OPTS.find(x => x[0] === String(v)); return o ? tr(o[1]) : +v < 0 ? fmtRem(v) : remDur(v); };
const remLabel = m => { const o = REM_OPTS.find(x => x[0] === String(m)); return o ? tr(o[1]) : fmtRem(m); };
// ---- 2.7.0 (#412): a due date can be a deadline: the rows and the task panel count down ("12 days left") and highlight
// it from its first reminder on (no reminder: from the due day); deadline 2 = also on Today from the first reminder on
function remStart(t) {  // the first reminder of a task (Date), null without a due date
  if (!t?.due) return null;
  const at = new Date(`${t.due}T${t.due_time || S.settings?.allday_time || '09:00'}`);
  const offs = String(t.reminders || '').split(',').filter(x => /^-?\d+$/.test(x.trim())).map(Number);
  return offs.length ? new Date(at - Math.max(...offs) * 60000) : at;
}
const dlActive = t => !!t?.deadline && !!t.due && t.status === 0 && (t.due <= today() || Date.now() >= +remStart(t));
const dlToday = t => t?.deadline === 2 && dlActive(t);
function dlLeft(t) {  // "12 days left" / "due today" / "3 days over"
  const n = diffDays(today(), t.due);
  return n > 0 ? trn('{0} day left', '{0} days left', n) : n === 0 ? tr('Deadline today') : trn('{0} day over', '{0} days over', -n);
}
const dlChip = (t, cls = '') => t.deadline && t.due && t.status === 0 ? `<span class="dlc ${dlActive(t) ? 'hot' : ''} ${cls}" title="${esc(tr('Deadline') + ': ' + dayLabel(t.due))}">${ic('flag', 's')}${esc(dlLeft(t))}</span>` : '';
// ---- 2.7.0 (#413): nags = the reminder repeats until the task is done; '' on a task = its list's default
const NAG_OPTS = [['off', N_('Off|nag')], ['5', N_('every 5 min')], ['10', N_('every 10 min')], ['15', N_('every 15 min')], ['30', N_('every 30 min')], ['60', N_('every hour')], ['1d', N_('daily')]];
const nagLabel = v => tr((NAG_OPTS.find(x => x[0] === v) || NAG_OPTS[0])[1]);
const nagOf = t => { const v = t?.nag || ''; return v === 'off' ? '' : v || listById(t?.list_id)?.nag || ''; };
