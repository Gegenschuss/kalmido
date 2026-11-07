// 2.637.0 UI test (part B, #4768), own container (start.sh). jsdom:
// kalmido-suite: fresh
// the rule dialog: the due trigger has Before the due date / Overdue + days; "Add action" adds blocks up to five (then it is
// gone), a block can be removed; "Only if" with priority / person / tag / column; saving stores the chain, the conditions and
// the distance; the list of rules shows the chain ("..., ... and ...") and the condition; editing a stored chain shows its
// blocks again; a rule without new parts still saves as before (one action, no conditions).
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG, kind: 'project'})).id;
  const REV = (await call('POST', '/api/sections', {list_id: W, name: 'Review'})).id;
  const TAG = (await call('POST', `/api/lists/${W}/tags`, {name: 'urgent'})).id;

  const w = await boot({user: 'alice'}), d = w.document;
  w.eval(`listModal(${W})`);
  await until(() => d.querySelector('#l-rules [data-rul-add]'));
  click(w, d.querySelector('#l-rules [data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  const dl = () => d.querySelector('.rul-dlg'), q = s => dl().querySelector(s);
  q('#rul-name').value = 'Late chain';
  change(w, q('#rul-trig'), 'due');
  check(q('#rul-dwhen') && q('#rul-ddays'), '#4768: the due trigger shows when + days');
  change(w, q('#rul-dwhen'), 'overdue');
  q('#rul-ddays').value = '2';
  // three actions: priority, tag, comment; a fourth added and removed again
  change(w, q('#rul-act'), 'priority');
  change(w, q('#rul-prio'), 'urgent');
  click(w, q('[data-rul-addact]'));
  check(q('#rul-act-1'), '#4768: Add action adds a second block');
  change(w, q('#rul-act-1'), 'tag');
  change(w, q('#rul-atag-1'), String(TAG));
  click(w, q('[data-rul-addact]'));
  change(w, q('#rul-act-2'), 'comment');
  q('#rul-text-2').value = 'Two days late';
  click(w, q('[data-rul-addact]'));
  check(q('#rul-act-3') && q('[data-rul-delact="3"]'), '#4768: a fourth block with a remove button');
  click(w, q('[data-rul-delact="3"]'));
  check(!q('#rul-act-3') && q('#rul-prio').value === 'urgent' && q('#rul-text-2').value === 'Two days late',
    '#4768: removing a block keeps the others as they were');
  for (let i = 0; i < 3; i++) click(w, q('[data-rul-addact]'));
  check(q('#rul-act-4') && q('[data-rul-addact]').disabled, '#4768: at most five actions (Add action is off then)');
  for (const i of [4, 3]) click(w, q(`[data-rul-delact="${i}"]`));
  // only if: the column and the tag
  q('#rul-cond').open = true;
  change(w, q('#rul-csec'), String(REV));
  change(w, q('#rul-ctag'), String(TAG));
  click(w, q('[data-m="save"]'));
  await until(async () => ((await call('GET', `/api/lists/${W}/rules`)).rules || []).length === 1);
  const rr = ((await call('GET', `/api/lists/${W}/rules`)).rules || [])[0] || {};
  check(rr.trigger?.when === 'overdue' && rr.trigger?.days === 2, '#4768: the distance is saved ' + JSON.stringify(rr.trigger));
  check(JSON.stringify((rr.actions || []).map(a => a.kind)) === '["priority","tag","comment"]' && rr.actions[2].text === 'Two days late',
    '#4768: the chain is saved in order ' + JSON.stringify(rr.actions));
  check(rr.conditions?.section_id === REV && rr.conditions?.tag_id === TAG && !rr.conditions?.priority, '#4768: the conditions are saved ' + JSON.stringify(rr.conditions));
  await until(() => d.querySelector('#l-rules .rul-row'));
  const txt = d.querySelector('#l-rules .rul-row')?.textContent || '';
  check(/overdue for 2 days/.test(txt) && /add the tag/.test(txt) && / and comment/.test(txt) && /in the column “Review”/.test(txt),
    '#4768: the list shows the chain and the condition: ' + txt.replace(/\s+/g, ' '));
  // editing shows the stored chain again
  click(w, d.querySelector('#l-rules [data-rul-edit]'));
  await until(() => d.querySelector('.rul-dlg #rul-act-2'));
  check(q('#rul-act').value === 'priority' && q('#rul-act-1').value === 'tag' && q('#rul-text-2')?.value === 'Two days late'
    && q('#rul-dwhen').value === 'overdue' && q('#rul-ddays').value === '2' && q('#rul-cond').open && q('#rul-csec').value === String(REV),
    '#4768: editing shows the chain, the distance and the conditions');
  click(w, q('[data-m="close"]'));
  // a plain rule as before: one action, no conditions
  click(w, d.querySelector('#l-rules [data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  q('#rul-name').value = 'Plain';
  change(w, q('#rul-trig'), 'done');
  change(w, q('#rul-act'), 'comment');
  q('#rul-text').value = 'Done';
  click(w, q('[data-m="save"]'));
  await until(async () => ((await call('GET', `/api/lists/${W}/rules`)).rules || []).length === 2);
  const pl = ((await call('GET', `/api/lists/${W}/rules`)).rules || []).find(x => x.name === 'Plain') || {};
  check((pl.actions || []).length === 1 && JSON.stringify(pl.conditions) === '{}', '#4768: a plain rule stays one action without conditions ' + JSON.stringify(pl));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
