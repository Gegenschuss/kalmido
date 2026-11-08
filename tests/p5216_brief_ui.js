// kalmido-suite: fresh
// 2.739.0 UI tests (#5216; own container, start.sh). jsdom, the agent chat on the phone page: the brief of a job (kind
// brief, the exact wording its agent gave the job)
// - the job's own chat: the brief is the first row, folded, titled "Job brief" with "Show the brief"; a tap opens it and
//   shows the whole text as Markdown; a refresh keeps it open
// - the whole chat never shows it (the job's card, the plain messages stay as they are)
// - a job without a brief: no such row
// - CSS: hit area of the fold >= 2.75rem, rem sizes, no new colours
// freelancer-matrix: agents (the route is covered by p5216_brief_api as a person without an organisation)
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P5216_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.739', user_id: me.id, state: 'running', log: 'Started'})).id;
  const J2 = (await v1('POST', '/agent/jobs', {title: 'Mira: no brief', user_id: me.id, state: 'running'})).id;
  check(J && J2, 'setup: two jobs');
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  const br = await say('# Build the card\n\nPlease make **the brief** readable.\n\n- step one\n- step two', {kind: 'brief', job_id: J});
  check(br.status === 201 && br.kind === 'brief', 'setup: the brief ' + br.status);
  await say('Knox: building', {job_id: J, job_msg: 'say'});
  await say('Hello, a plain answer');

  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  const box = () => d.querySelector('#chat-msgs');
  await until(() => /plain answer/.test(box()?.textContent || '') && d.querySelector(`#chat-msgs .jcd[data-jcd="${J}"]`));

  // ================= the whole chat: no brief
  check(!d.querySelector('#chat-msgs .jcbrief') && !/Build the card|step two/.test(box().textContent), 'the whole chat never shows the brief');

  // ================= the job's own chat: first row, folded
  w.eval(`jc_open(${CL}, ${J})`);
  await until(() => d.querySelector('#jc-bar') && d.querySelector('#chat-msgs .jcbrief') && /Knox: building/.test(box().textContent));
  const brief = () => d.querySelector('#chat-msgs .jcbrief');
  const rows = [...box().children], bi = rows.indexOf(brief());
  const msgRows = rows.filter(x => x.classList.contains('cmsg') || x.classList.contains('cnotice'));
  check(bi >= 0 && msgRows.every(x => rows.indexOf(x) > bi), 'the brief is the first row of the job\'s chat (before the start line, messages, progress) ' + rows.map(x => x.className).join('|'));
  check(brief().tagName === 'DETAILS' && !brief().open, 'folded at first');
  const sum = brief().querySelector('summary');
  check(/Job brief/.test(sum.textContent) && /Show the brief/.test(sum.textContent), 'the title "Job brief" and "Show the brief" ' + sum.textContent);
  const body = brief().querySelector('.jcbb');
  check(body && body.querySelector('b') && /the brief/.test(body.querySelector('b').textContent) && body.querySelectorAll('li').length === 2, 'the whole text as Markdown (bold, list)');
  brief().open = true;
  check(brief().open, 'a tap opens it');
  const k0 = brief().dataset.k;
  await say('Knox: still building', {job_id: J, job_msg: 'say'});
  await w.eval('chatLoad()');
  await until(() => /still building/.test(box().textContent));
  check(brief() && brief().open && brief().dataset.k === k0, 'a refresh keeps it open (same row)');
  check([...box().children].filter(x => x.classList.contains('jcbrief')).length === 1, 'exactly one brief row');

  // ================= a job without a brief
  w.eval(`jc_open(${CL}, ${J2})`);
  await until(() => w.eval('S.chat.job && +S.chat.job.id') === J2 && !d.querySelector('#chat-msgs .jcbrief'));
  check(!d.querySelector('#chat-msgs .jcbrief'), 'a job without a brief: no brief row');

  // ================= German
  const de = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'i18n', 'de.json'), 'utf8'));
  check(de['Job brief'] === 'Auftrag' && de['Show the brief'] === 'Auftrag anzeigen', 'German: "Auftrag", "Auftrag anzeigen"');

  // ================= CSS
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  const blk = css.slice(css.indexOf('/* 2.739.0 (#5216)'));
  check(/\.jcbrief>summary\{[^}]*min-height:2\.75rem/.test(blk), 'the fold has a hit area of 2.75rem');
  const plain = blk.replace(/\/\*[\s\S]*?\*\//g, '');
  check(!/(?<![\d.])([3-9]|\d{2,})px/.test(plain) && !/#[0-9a-f]{3,6}\b/i.test(plain), 'CSS: rem sizes, no new colours');

  console.log(`p5216_brief_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
