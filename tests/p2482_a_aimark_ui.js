// kalmido-suite:
// 2.482.0 A UI test (#3530, EU AI Act Art. 50 (4)): the quiet note before a text an AI agent wrote goes out. Own container
// (start.sh), jsdom. Invented names only. A person without an organisation (freelancer-matrix: office, wiki).
// - a letter draft of an agent (agent_id) shows the note above the buttons; "Insert label" adds the line "Created with AI
//   support" at the end of the text and saves it; the note does not come back for that letter; a person's own letter has none
// - a wiki page an agent changed last: the share dialog shows the note above the public link; "Insert label" adds the line to
//   the page; closing it = not shown again for that page
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = (fn, o) => require('./boot').until(fn, o);
const LINE = 'Created with AI support';

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['office', 'wiki']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'office,wiki'});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida: no organisation');
  const AG = 990001;  // an agent id the page counts as an agent (S.tl.agents): what made the text is all the note needs

  // ================= a letter an agent drafted
  const lt = await call(CF, 'POST', '/api/office/letters', {subject: 'Offer for the shoot', body: 'Dear Ms Example,\n\nhere is our offer.'});
  check(lt.http === 201 && lt.id, 'frida: a letter draft ' + lt.http);
  let w = await boot({user: 'frida', hash: 'office/letters/' + lt.id}), d = w.document;
  check(await until(() => d.querySelector('#lt-body')), 'the letter opens');
  check(!d.querySelector('.aiph'), "a person's own letter: no AI note");
  w.eval(`LT.cur.agent_id = ${AG}; ofcDraw()`);  // as lt_public sends it for a draft of an agent (letteragent.py)
  check(await until(() => d.querySelector('.aiph[data-aiph="letter"] [data-aiph-ins]')), 'an agent\'s draft: the AI note with "Insert label"');
  check(/AI agent/.test(d.querySelector('.aiph')?.textContent || '') && !!d.querySelector('.aiph + .foot [data-lt="sent"]'), 'the note sits right above the buttons that send it');
  d.querySelector('.aiph [data-aiph-ins]').click();
  check(await until(() => !d.querySelector('.aiph') && d.querySelector('#lt-body').value.endsWith(LINE)), 'Insert label: the line at the end of the text, the note gone');
  check(await until(async () => ((await call(CF, 'GET', `/api/office/letters/${lt.id}`)).body || '').endsWith('\n\n' + LINE)), 'the line is saved with the letter');
  w.eval(`LT.cur.agent_id = ${AG}; LT.cur.body = 'other text'; ofcDraw()`); await idle(w);
  check(!d.querySelector('.aiph'), 'once per letter: the note does not come back');
  w.close();

  // ================= a wiki page an agent changed last: the share dialog
  const pg = await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Press release', body: '# Press release\n\nNew studio opens.'});
  check(pg.id, 'frida: a wiki page ' + pg.http);
  w = await boot({user: 'frida', hash: 'wiki'}); d = w.document;
  await until(() => w.eval('!!S.booted'));
  const share = () => w.eval(`S.tl.agents = [...(S.tl.agents || []), ${AG}]; wsh_sharePage({...${JSON.stringify(pg)}, updated_by: ${AG}})`);
  share();
  check(await until(() => d.querySelector('.modal .aiph[data-aiph="wiki"]') && d.querySelector('.modal [data-wsh="link"]')), 'share dialog: the AI note above the public link');
  d.querySelector('.modal .aiph [data-aiph-ins]').click();
  check(await until(async () => ((await call(CF, 'GET', `/api/wiki/pages/${pg.id}`)).body || '').endsWith('*' + LINE + '*')), 'Insert label: the line is added to the page');
  check(!d.querySelector('.modal .aiph'), 'the note is gone');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  share();
  await until(() => d.querySelector('.modal [data-wsh="link"]'));
  check(!d.querySelector('.modal .aiph'), 'once per page: the note does not come back');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // a page of a person: no note
  const pg2 = await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Own notes', body: 'Written by me.'});
  w.eval(`wsh_sharePage(${JSON.stringify(pg2)})`);
  await until(() => d.querySelector('.modal [data-wsh="link"]'));
  check(!d.querySelector('.modal .aiph'), "a person's page: no AI note");
  w.close();

  console.log(`p2482_a_aimark_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
