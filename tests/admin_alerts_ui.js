// Admin alerts UI (jsdom): Settings > Users > Whole server > Admin alerts -- form, save, test alert, recent list,
// clear, German labels, nothing for non-admins. Runs after admin_alerts_test.py on its last container
// (KALMIDO_ADMIN_TOPIC=env-admins; alice + carol (German) are admins, bob is not).
const fs = require('fs');
const path = require('path');
const {boot, errs, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DATA = process.argv[2];
const ntfy = () => { try { return fs.readFileSync(path.join(DATA, 'ntfy.log'), 'utf8').split('\n').filter(Boolean).map(JSON.parse); } catch { return []; } };
const api = async (w, m, u, b) => (await w.fetch(u, {method: m, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: b ? JSON.stringify(b) : undefined})).json();
(async () => {
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('users')`); await sleep(800);
  let md = d.querySelector('.smodal');
  const box = md.querySelector('#s-aa');
  check(box && md.querySelector('#s-aa-h')?.textContent === 'Admin alerts', 'users pane: Admin alerts section');
  check(md.querySelector('#aa-on')?.checked === true, 'switch on');
  const topic = md.querySelector('#aa-topic');
  check(topic && topic.readOnly && topic.value === 'env-admins' && /KALMIDO_ADMIN_TOPIC/.test(box.textContent), 'env topic: read-only with a note');
  check(md.querySelectorAll('[data-aakind]').length === 6 && [...md.querySelectorAll('[data-aakind]')].every(x => x.checked), 'six kinds, all on');
  check(md.querySelectorAll('.aarow').length > 0 && /share inbox was not started/.test(box.textContent), 'recent list shows the alerts');
  check(md.querySelector('#aa-dtime-w').hidden, 'summary time hidden in instant mode');
  // 1.5: every change is saved at once (no "Save alert settings")
  check(!md.querySelector('[data-aa="save"]'), 'no Save button');
  const ch = (sel, v) => { const e = md.querySelector(sel); if (typeof v === 'boolean') e.checked = v; else e.value = v; e.dispatchEvent(new w.Event('change', {bubbles: true})); };
  ch('#aa-prio', '5'); await sleep(400);
  ch('[data-aakind="storage"]', false); await sleep(400);
  ch('#aa-mode', 'digest'); await sleep(400);
  check(!md.querySelector('#aa-dtime-w').hidden, 'summary time shown in summary mode');
  w.eval(`dpSet(document.querySelector('#aa-dtime'), '07:30')`); await sleep(400);
  ch('#aa-cool', '12'); await sleep(900);
  let j = await api(w, 'GET', '/api/admin/alerts');
  check(j.prio === '5' && !j.kinds.includes('storage') && j.kinds.length === 5 && j.mode === 'digest' && j.digest_time === '07:30' && j.cooldown_h === 12,
    'saved: ' + JSON.stringify([j.prio, j.kinds, j.mode, j.digest_time, j.cooldown_h]));
  check(md.querySelector('.ssaved.on') && /Admin alerts/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), '"Saved" + history step');
  // back via undo (five steps)
  await w.eval(`histStep('undo', 5)`); await sleep(300);
  j = await api(w, 'GET', '/api/admin/alerts');
  check(j.prio === '4' && j.kinds.length === 6 && j.mode === 'instant' && j.cooldown_h === 6, 'restored via undo: ' + JSON.stringify([j.prio, j.kinds.length, j.mode, j.cooldown_h]));
  md = d.querySelector('.smodal');
  // test alert
  const n0 = ntfy().length;
  click(w, md.querySelector('[data-aa="test"]')); await sleep(1200);
  const sent = ntfy().slice(n0).filter(x => x.title === 'Kalmido test alert');
  check(sent.length === 1 && sent[0].topic === 'env-admins', 'test alert sent to the env topic: ' + JSON.stringify(sent));
  check(/Test alert sent/.test(d.querySelector('#toast').textContent), 'toast Test alert sent');
  check(md.querySelector('.aarow b')?.textContent === 'Test alert', 'list redrawn, newest first');
  // clear
  click(w, md.querySelector('[data-aa="clear"]')); await sleep(800);
  check(!md.querySelector('.aarow') && /No admin alerts yet/.test(md.querySelector('#s-aa').textContent), 'cleared');
  md.remove(); w.close();
  // Help: project links (new tab, no opener / referrer) + palette entries
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('help')`); await sleep(400); md = d.querySelector('.smodal');
  const links = [...md.querySelectorAll('.aboutlinks a')];
  check(links.map(a => a.getAttribute('href')).join(' ') === 'https://kalmido.com https://github.com/Gegenschuss/kalmido https://github.com/Gegenschuss/kalmido/issues'
    && links.every(a => a.target === '_blank' && a.rel === 'noopener noreferrer'), 'help: website, GitHub, report a problem links');
  md.remove();
  let opened = null; w.open = (u, t, f) => { opened = [u, t, f]; return null; };
  const pi = w.eval(`palAll().filter(x => x.id === 'a:website' || x.id === 'a:issue').map(x => x.label)`);
  check(pi.join('|') === 'Open website|Report a problem', 'palette: Open website + Report a problem: ' + pi);
  w.eval(`palAll().find(x => x.id === 'a:website').fn()`);
  check(opened && opened[0] === 'https://kalmido.com' && opened[1] === '_blank' && /noopener/.test(opened[2]) && /noreferrer/.test(opened[2]), 'palette opens the website in a new tab without opener');
  w.close();
  // German
  w = await boot({user: 'carol'}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(800); md = d.querySelector('.smodal');
  check(md.querySelector('#s-aa-h')?.textContent === 'Admin-Warnungen' && /Warnungen zum Server gehen an die Admins über ihren eigenen Benachrichtigungskanal/.test(md.querySelector('#s-aa').textContent)
    && /Sicherheitsereignisse/.test(md.querySelector('#aa-kinds').textContent), 'German labels');
  md.remove(); w.close();
  // non-admin
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(600); md = d.querySelector('.smodal');
  check(!md.querySelector('#s-aa') && !md.querySelector('.snav [data-sec="users"]'), 'non-admin: no Users tab, no admin alerts');
  md.remove(); w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
