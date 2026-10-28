// @ts-check
/* Kalmido web client: 2.111.0 C (#2057) quick add, second part: @person (assign), a duration and a reminder (minutes before
   the due time, or at a fixed time "remind me Tue 9:00", also without a due date), and the fixed-time row of the date
   dialog. parseQuick (quickadd.js) calls qa2_early before the dates and qa2_late at its end; whoever creates a task from
   its result calls qa2_body. Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

// lower case without accents: "Zoë" = "zoe"
const qa2_n = s => String(s || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
const qa2_re = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// reminder words: German and English always, the others in their app language (like the date words of QL)
const QA2_KW = {de: 'erinnere(?: mich)?|erinner(?: mich)?|erinnerung', en: 'remind(?: me)?|reminder',
  fr: 'rappelle-moi|rappelle moi|rappel', es: 'recu[ée]rdame|av[íi]same|recordatorio', it: 'ricordami|avvisami|promemoria',
  nl: 'herinner(?: me| mij)?|herinnering'};
// a fixed time only after the verbs ("Erinnerung Freitag schreiben" stays a task due on Friday)
const QA2_KWF = {de: 'erinnere(?: mich)?|erinner mich', en: 'remind(?: me)?', fr: 'rappelle-moi|rappelle moi', es: 'recu[ée]rdame|av[íi]same',
  it: 'ricordami|avvisami', nl: 'herinner(?: me| mij)?'};
const QA2_BEFORE = {de: 'vorher|davor', en: 'before|earlier|ahead', fr: 'avant', es: 'antes', it: 'prima', nl: 'vooraf|van tevoren|ervoor|eerder'};
// units: minutes, hours, days, weeks (any language: numbers + units rarely mean something else)
const QA2_U = [[1, 'min\\.?|mins|minuten?|minutes?|minutos?|minuti|minuto|minuut'],
  [60, 'h|hrs?|hours?|std\\.?|stunden?|heures?|horas?|ore|ora|uur'],
  [1440, 'tage?n?|days?|jours?|d[íi]as?|giorn[oi]|dagen|dag'], [10080, 'wochen?|weeks?|semaines?|semanas?|settiman[ae]|weken|week']];
const qa2_unit = w => +(QA2_U.find(([, re]) => new RegExp(`^(?:${re})$`, 'i').test(w)) || [0])[0];
const qa2_langs = () => [...new Set(['de', 'en', typeof I18N === 'object' && QA2_KW[I18N.code] ? I18N.code : 'en'])];
const qa2_words = M => qa2_langs().map(k => M[k]).join('|');
// short weekdays inside a reminder phrase only ("erinnere mich Di 9:00"): in a title "so" or "do" stay words
const QA2_WD = {mo: 'montag', di: 'dienstag', mi: 'mittwoch', do: 'donnerstag', fr: 'freitag', sa: 'samstag', so: 'sonntag',
  mon: 'monday', tue: 'tuesday', tues: 'tuesday', wed: 'wednesday', thu: 'thursday', thur: 'thursday', thurs: 'thursday', fri: 'friday', sat: 'saturday', sun: 'sunday'};
const qa2_wdLong = s => s.replace(/\S+/g, w => QA2_WD[w.toLowerCase().replace(/\.$/, '')] || w);
const qa2_durLabel = v => tr('Duration {0}', v < 60 ? v + ' min' : fmtNum(v / 60) + ' h');  // as the date dialog says it

// the reminder ("erinnere mich 15 min vorher" / "remind me tomorrow 9am") and the duration ("30 min", "für 2 Std")
function qa2_early(take, out, cur) {
  const KW = qa2_words(QA2_KW), U = QA2_U.map(u => u[1]).join('|');
  take(new RegExp(`\\s(?:${KW})\\s+(\\d{1,4})\\s?(${U})\\s+(?:${qa2_words(QA2_BEFORE)})(?=\\s)`, 'i'), 'rem', m => {
    const v = +m[1] * qa2_unit(m[2]);
    if (!v || v > REM_MAX) return false;
    out.reminders = String(v); return fmtRem(v);
  });
  if (out.reminders === undefined) {  // a fixed time: the longest few words after the keyword that are only a date / time
    const s = cur(), k = s.match(new RegExp(`\\s(?:${qa2_words(QA2_KWF)})(?=\\s)`, 'i'));
    if (k) {
      const rest = s.slice(k.index + k[0].length), toks = [...rest.matchAll(/\S+/g)].slice(0, 5);
      for (let n = toks.length; n > 0; n--) {
        const txt = rest.slice(0, toks[n - 1].index + toks[n - 1][0].length), r = parseQuick(qa2_wdLong(txt.trim()), new Set(), true);
        if (r.title || !(r.due || r.due_time) || r.repeat || r.list_id || r.priority || r.tags?.length || r.url) continue;
        const d = r.due || today(), hm = r.due_time || rat_allday();
        const at = `${d}T${hm}`;
        take(new RegExp(qa2_re(k[0] + txt) + '(?=\\s)'), 'rem', () => { out.remind_at = at; return `${tr('Reminder')} ${dayLabel(d)} ${hm}`; });
        break;
      }
    }
  }
  // duration: "für / for 2 Std" anywhere; "30 min" / "2h" alone too, but never "in 30 min" (a time from now), "15 min vorher"
  // (a reminder without its word), a French "15h" or a Dutch "15 uur" (times there)
  const H = `(\\d{1,3}(?:[.,]\\d{1,2})?)\\s?(${QA2_U[0][1]}|${QA2_U[1][1]})(?:(\\d{2})(?=\\s))?`;
  const qd = m => {
    const u = qa2_unit(m[2]); if (u !== 1 && u !== 60) return false;
    const v = Math.round(+m[1].replace(',', '.') * u + (u === 60 && m[3] ? +m[3] : 0));
    if (!(v >= 1) || v > 7 * 1440) return false;
    out.duration = v; return qa2_durLabel(v);
  };
  take(new RegExp(`\\s(?:für|fuer|for|pendant|durante|per|voor|gedurende)\\s${H}(?=\\s)`, 'i'), 'dur', qd);
  if (out.duration === undefined) {
    const L = typeof QL === 'object' ? QL[I18N.code] : null;
    const bare = L?.atH ? /^h$/i : L?.uur ? /^uur$/i : null;
    take(new RegExp(`(?<!\\s(?:in|dans|en|de|tra|fra|over|om|um|at|à|a|alle|las|binnen))\\s${H}(?!\\s+(?:${Object.values(QA2_BEFORE).join('|')})(?=\\s))(?=\\s)`, 'i'), 'dur',
      m => bare && bare.test(m[2]) ? false : qd(m));
  }
}

// the people a task in list l can be assigned to: the same as the assign menu (list people + the organisation's people
// who may edit it; agents only where the list opens them), plus the list's groups
function qa2_people(l) {
  if (!l || typeof collab !== 'function' || !collab()) return [];
  const ppl = [...listPeople(l), ...(typeof o3a_ovPeople === 'function' ? o3a_ovPeople(l) : [])]
    .filter(p => l.agents_open !== false || !(p.agent || (typeof agentById === 'function' && agentById(p.user_id))))
    .map(p => ({id: p.user_id, name: p.name || (S.me && p.user_id === S.me.id ? S.me.display_name : '') || ''}));
  const gs = (l.groups || []).map(g => ({gid: g.group_id, name: g.name || ''}));
  return [...ppl, ...gs].filter(p => p.name);
}
const QA2_ME = ['ich', 'mich', 'me', 'moi', 'yo', 'io', 'ik', 'mij'];
// "@Anna", "@Anna Schmidt", "@ich": the longest full name, else a first name only one person has; null = nobody / unclear
function qa2_match(l, words) {
  const ppl = qa2_people(l), w = words.map(qa2_n);
  let best = null, amb = false;
  for (const p of ppl) {
    const nw = qa2_n(p.name).split(/\s+/).filter(Boolean);
    if (nw.length && nw.length <= w.length && nw.every((x, i) => x === w[i]) && (!best || nw.length > best.n)) best = {p, n: nw.length};
  }
  if (best) return best;
  const first = ppl.filter(p => qa2_n(p.name).split(/\s+/)[0] === w[0]);
  if (first.length === 1) return {p: first[0], n: 1};
  if (first.length > 1) amb = true;
  if (!amb && QA2_ME.includes(w[0]) && S.me) { const me = ppl.find(p => p.id === S.me.id); if (me) return {p: me, n: 1}; }
  return null;
}
function qa2_ctxList(out) {
  let d = {}; try { d = quickDefaults(); } catch { /* no view yet */ }
  return listById(out.list_id || d.list_id) || inbox();
}
// @person at the end of parseQuick (an e-mail address "a@b.de" never: the @ must start a word)
function qa2_late(take, out, cur) {
  const s = cur(), m = s.match(/\s@([^\s@<>~#!]+(?:\s+[^\s@<>~#!]+){0,3})(?=\s)/u);
  if (!m) return;
  const words = m[1].split(/\s+/), hit = qa2_match(qa2_ctxList(out), words);
  if (!hit) return;
  const raw = '@' + words.slice(0, hit.n).join(' ');
  out.qa2At = {words: words.slice(0, hit.n), title: s.replace(/\s+/g, ' ').trim()};  // the title with the @ text, if it stays
  take(new RegExp('\\s' + qa2_re(raw) + '(?=\\s)'), 'who', () => {
    if (hit.p.gid) out.assignee_group_id = hit.p.gid; else out.assignee_id = hit.p.id;
    return tr('Assigned to {0}', hit.p.name);
  });
  if (out.assignee_id === undefined && out.assignee_group_id === undefined) delete out.qa2At;
}
// the parsed extras into a new task's body (body.list_id = where it really goes): the person is looked up again in that
// list; nobody there = the @ text stays in the title (never a wrong assignment)
function qa2_body(r, body) {
  if (!r) return body;
  if (r.duration) body.duration = r.duration;
  if (r.reminders !== undefined) body.reminders = r.reminders;
  if (r.remind_at) body.remind_at = r.remind_at;
  if (r.qa2At) {
    const hit = qa2_match(listById(body.list_id) || inbox(), r.qa2At.words);
    if (hit && hit.n === r.qa2At.words.length) {
      if (hit.p.gid) { body.assignee_group_id = hit.p.gid; delete body.assignee_id; } else { body.assignee_id = hit.p.id; delete body.assignee_group_id; }
    } else body.title = r.qa2At.title;
  }
  return body;
}

// ---- the date dialog: "At a fixed time" (date + time, removable), also without a due date
function rat_row(st) {
  const [d, hm] = (st.remind_at || 'T').split('T');
  return `<div class="prow ratrow" role="group" aria-label="${esc(tr('At a fixed time'))}">${ic('bell', 's')}<span class="muted plab">${tr('At a fixed time')}</span>${dateIn('p-ratd', d || '', {label: tr('Date'), empty: tr('none')})}${timeIn('p-ratt', hm || '', {label: tr('Time'), empty: '--:--'})}${st.remind_at ? `<button class="iconbtn" data-q="ratx" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>` : ''}</div>`;
}
// a change in the row: true = handled (the dialog redraws)
function rat_change(e, st) {
  if (/** @type {any} */ (e.target).id !== 'p-ratd' && /** @type {any} */ (e.target).id !== 'p-ratt') return false;
  const [d0, t0] = (st.remind_at || 'T').split('T');
  let d = $('#p-ratd')?.value || d0, hm = $('#p-ratt')?.value || t0;
  if (!d && !hm) { st.remind_at = null; return true; }
  if (!hm) hm = rat_allday();
  if (!d) d = hm < nowHM() ? addDays(today(), 1) : today();
  st.remind_at = `${d}T${hm}`;
  return true;
}
// the time of a reminder without one: the all-day reminder time of the settings
const rat_allday = () => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(S.settings?.allday_time || '') ? S.settings.allday_time : '09:00';
// the bell of a row / the date button: a reminder before the due time, or at a fixed time
const rat_has = t => !!t && (!!(t.reminders && t.due) || !!t.remind_at);
