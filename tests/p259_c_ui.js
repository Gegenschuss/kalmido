// 2.59.0 UI tests of part C (own container, start.sh). jsdom:
// - #1827: a job message's tag shows the job's name (job_name of the server), "Job #N" without one; the colour comes from
//   the name (the same name = the same colour, also "Walker (Fortsetzung)"), without a name from the number as before; a part
//   job takes its leader's colour (from the leader's name), class jpart = lighter; the job's bar takes the same colour
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const AG = (await call('POST', '/api/admin/agents', {username: 'helperbot', display_name: 'Helper bot'})).id;
  const w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  await until(() => w.jn9_hash && w.jc_barHtml && w.eval('typeof AC_COLORS') !== 'undefined');

  // ================= the hash: stable, case-blind, a bracket at the end does not count
  const h = n => w.eval(`jn9_hash(${JSON.stringify(n)})`);
  check(h('Walker') === h('walker') && h('Walker') === h('Walker (Fortsetzung)') && h('Walker') >= 0, 'same name = same hash (small letters, "(Fortsetzung)" ignored)');
  check(h('') === -1 && h(null) === -1, 'no name: no hash');
  // FNV-1a 32 bit of "walker", computed here independently
  let x = 0x811c9dc5; for (const ch of 'walker') { x ^= ch.charCodeAt(0); x = Math.imul(x, 0x01000193) >>> 0; }
  check(h('Walker') === x, `FNV-1a over the small-letter name ${h('Walker')} ${x}`);
  const cName = n => w.eval(`ux_jobColor(7, ${JSON.stringify(n)})`);
  check(cName('Walker') === w.eval(`AC_COLORS[${x % 12}]`) && w.eval('AC_COLORS.length') === 12, 'the colour = palette at hash mod length');
  check(w.eval('ux_jobColor(5)') === w.eval('AC_COLORS[5]') && w.eval('ux_jobColor(5, "")') === w.eval('AC_COLORS[5]'), 'without a name: the number as before');
  const names = ['Alma', 'Bruno', 'Cora', 'Dina', 'Emil', 'Fiona', 'Greta', 'Hugo'];
  check(new Set(names.map(cName)).size >= 4, 'different names spread over the palette ' + names.map(cName).join(','));

  // ================= the chat: tag + colour
  const html = w.eval(`S.chat.aid = ${AG}; S.chat.msgs = ${JSON.stringify([
    {id: 901, from: 'agent', kind: 'message', body: 'Walker: release runs', job_id: 248, job_name: 'Walker', created_at: '2026-10-16T20:00:00Z', reactions: []},
    {id: 902, from: 'agent', kind: 'message', body: 'Holston C: part done', job_id: 252, job_name: 'Walker E', job_parent: 248, job_parent_name: 'Walker', created_at: '2026-10-16T20:01:00Z', reactions: []},
    {id: 903, from: 'agent', kind: 'message', body: 'Walker (Fortsetzung): goes on', job_id: 260, job_name: 'Walker', created_at: '2026-10-16T20:02:00Z', reactions: []},
    {id: 904, from: 'agent', kind: 'message', body: 'Job #171: nameless', job_id: 171, created_at: '2026-10-16T20:03:00Z', reactions: []},
    {id: 905, from: 'agent', kind: 'message', body: 'part of a nameless leader', job_id: 172, job_name: 'Ida B', job_parent: 171, created_at: '2026-10-16T20:04:00Z', reactions: []},
    {id: 907, from: 'agent', kind: 'message', body: 'part without its leader', job_id: 253, job_name: 'Walker G', created_at: '2026-10-16T20:05:00Z', reactions: []},
    {id: 906, from: 'agent', kind: 'message', body: 'Job #300: an old message that names another job', job_id: 301, job_name: 'Nils', created_at: '2026-10-16T20:05:00Z', reactions: []}])}; chatMsgs()`);
  const box = d.createElement('div'); box.innerHTML = html;
  const msg = id => box.querySelector(`[data-mid="a:${id}"]`);
  const col = id => msg(id)?.style.getPropertyValue('--jcol');
  const tag = id => msg(id)?.querySelector('.jobtag')?.textContent.trim();
  check(tag(901) === 'Walker' && col(901) === cName('Walker'), `the tag shows the name, the colour comes from it: ${tag(901)} ${col(901)}`);
  check(tag(902) === 'Walker E' && msg(902).classList.contains('jpart') && col(902) === col(901), `a part job: its own name, the leader's colour, lighter (jpart): ${tag(902)} ${col(902)}`);
  check(tag(903) === 'Walker' && col(903) === col(901), 'a follow-up job with the same name: the same colour');
  // 2.59.0 (#1827): a part job without job_parent (older service) is told by its name "Walker G"
  check(tag(907) === 'Walker G' && msg(907).classList.contains('jpart') && col(907) === col(901), `a part job without job_parent: the leader's tone from its name: ${col(907)}`);
  check(tag(904) === 'Job #171' && col(904) === w.eval('AC_COLORS[171 % 12]'), `without a name: "Job #171" and the colour of the number: ${tag(904)}`);
  check(tag(905) === 'Ida B' && col(905) === col(904), 'a part of a nameless leader: the leader\'s number colour');
  check(tag(906) === 'Job #300' && col(906) === w.eval('AC_COLORS[300 % 12]'), `the text names another job than job_id: that job's tag, not job_name: ${tag(906)}`);
  const lbl = msg(902)?.querySelector('.jobtag')?.getAttribute('aria-label') || '';
  check(/Walker E/.test(lbl), 'the tag still says what it opens ' + lbl);

  // ================= the bar of a job's history: the same colour
  w.eval(`S.jc.jobs[248] = {id: 248, name: 'Walker', title: 'Walker: Release 2.59', state: 'running'}; S.jc.jobs[252] = {id: 252, name: 'Walker E', title: 'Walker E: Teil C', parent_id: 248, state: 'running'}; S.chat.job = {id: 252}`);
  const bar = d.createElement('div'); bar.innerHTML = w.eval('jc_barHtml()');
  const b = bar.querySelector('#jc-bar');
  check(b && b.classList.contains('jpart') && b.style.getPropertyValue('--jcol') === col(901), `the bar of a part job: the leader's colour, jpart ${b?.className} ${b?.style.getPropertyValue('--jcol')}`);
  w.eval('S.chat.job = {id: 248}');
  bar.innerHTML = w.eval('jc_barHtml()');
  check(!bar.querySelector('#jc-bar').classList.contains('jpart') && bar.querySelector('#jc-bar').style.getPropertyValue('--jcol') === col(901), 'the leader\'s bar: its colour, not lighter');
  w.eval('S.chat.job = null');

  // ================= CSS: the lighter tone mixes with the page background (light and dark theme), sizes in rem
  const css = require('fs').readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  const blk = css.slice(css.indexOf('/* 2.59.0 C (#1827)'));
  check(/\.cmsg\.agc\.jobm\.jpart \.cbub\{background:color-mix\(in srgb,color-mix\(in srgb,var\(--jcol\) 70%,var\(--bg\)\) var\(--agent-tint\)/.test(css) /* 2.174.0 (#2681): tinted, no stripe */ && /\.jcbar\.jpart \.jcdot/.test(blk) && !/\dpx/.test(blk.slice(0, 600)), 'CSS: part tone = leader mixed with the background');

  console.log(`p259_c_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
