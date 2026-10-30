// kalmido-suite: fresh
// 2.396.0 A (#3386) UI tests, own container (start.sh): the block "Git author" in the agent's settings (jsdom).
// The admin's agent dialog shows it below "Interim summary" with name + e-mail (placeholders = the default), the switch
// "Append Co-Authored-By" and the hint that it appears publicly in GitHub; every field saves at once; an invalid e-mail
// shows the error at the field and saves nothing. A person without an organisation finds it in the permissions dialog of
// her own agent (freelancer-matrix: agents). The repository's editor (gitrepo.js rpAuthorHtml): name + e-mail + hint.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  await call('POST', '/api/admin/orgs', {name: 'Alpha'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'claude', display_name: 'Claude'});
  const adm = async id => (await call('GET', '/api/admin/agents')).agents.find(a => a.id === id);

  // ================= the admin's agent dialog
  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  const md = await until(() => d.querySelector('#agg-name')?.closest('.modal'));
  const sec = md && md.querySelector('.agzgit');
  check(sec && /Git author/.test(sec.querySelector('h4')?.textContent || ''), 'agent dialog: block Git author');
  check(sec && sec.compareDocumentPosition(md.querySelector('.agzsec:not(.agzgit)')) & w.Node.DOCUMENT_POSITION_PRECEDING, 'below Interim summary');
  check(sec && sec.querySelector('#agg-name').placeholder === 'Kalmido' && sec.querySelector('#agg-mail').placeholder === 'noreply@kalmido.com'
    && sec.querySelector('#agg-name').value === '' && !sec.querySelector('#agg-co').checked, 'empty fields, the default as placeholder, switch off');
  check(sec && /publicly in GitHub/.test(sec.textContent), 'the hint: appears publicly in GitHub');
  change(w, sec.querySelector('#agg-mail'), 'not a mail'); await idle(w); await sleep(300);
  const err = sec.querySelector('#agg-err');
  check(err && !err.hidden && /valid email/.test(err.textContent) && sec.querySelector('#agg-mail').getAttribute('aria-invalid') === 'true',
    'an invalid e-mail: the error at the field');
  check((await adm(ag.id)).runtime.git_author_email === '', '... and nothing saved');
  change(w, sec.querySelector('#agg-mail'), 'bot@example.com');
  await until(async () => (await adm(ag.id)).runtime.git_author_email === 'bot@example.com');
  check((await adm(ag.id)).runtime.git_author_email === 'bot@example.com' && err.hidden, 'a valid e-mail saves at once, the error gone');
  change(w, sec.querySelector('#agg-name'), 'Acme Bot');
  await until(async () => (await adm(ag.id)).runtime.git_author_name === 'Acme Bot');
  check((await adm(ag.id)).runtime.git_author === 'Acme Bot <bot@example.com>', 'the name saves at once');
  change(w, sec.querySelector('#agg-co'), true);
  await until(async () => (await adm(ag.id)).runtime.git_coauthor === true);
  check((await adm(ag.id)).runtime.git_coauthor === true, 'the switch Append Co-Authored-By saves at once');
  // the interim summary still saves on its own (the git block has its own listener)
  change(w, md.querySelector('#agz-runs'), '120');
  await until(async () => (await adm(ag.id)).runtime.rotate_runs === 120);
  check((await adm(ag.id)).runtime.rotate_runs === 120 && (await adm(ag.id)).runtime.git_author_name === 'Acme Bot', 'Interim summary unchanged in its saving');

  // ================= the repository's editor (project level)
  const html = w.eval(`rpAuthorHtml({author_name: 'App <x>', author_email: 'app@example.com'})`);
  check(/id="rp-an"/.test(html) && /id="rp-am"/.test(html) && /App &lt;x&gt;/.test(html) && /publicly in GitHub/.test(html) && /data-rp="auth-save"/.test(html),
    'rpAuthorHtml: name (escaped) + e-mail + hint + Save');

  // ================= a person without an organisation: the permissions dialog of her own agent
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 2});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'agents,comments,collab'}, CF);
  check(!((await call('GET', '/api/state', null, CF)).me.workspaces || []).length, 'frida has no organisation');
  const fb = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read']}, CF);
  const w2 = await boot({user: 'frida', hash: 'today'}), d2 = w2.document;
  w2.eval(`(async () => { settingsModal('ai'); await new Promise(r => setTimeout(r, 500)); await aiSubShow(document.querySelector('.smodal'), 'setup', false); })()`);
  const permBtn = await until(() => d2.querySelector(`#s-myown [data-myag="${fb.id}"] [data-myag-act="perm"]`));
  permBtn?.dispatchEvent(new w2.MouseEvent('click', {bubbles: true, cancelable: true}));
  const pm = await until(() => lastModal(d2)?.querySelector('.agzgit') && lastModal(d2));
  const ps = pm && pm.querySelector('.agzgit');
  check(ps && ps.compareDocumentPosition(pm.querySelector('.foot')) & w2.Node.DOCUMENT_POSITION_FOLLOWING, 'frida: the block in her agent\'s permissions dialog');
  if (ps) change(w2, ps.querySelector('#agg-mail'), 'bot@frida.example.com');
  const mine = async () => ((await call('GET', '/api/my/agents', null, CF)).agents || []).find(a => a.id === fb.id);
  await until(async () => (await mine())?.runtime?.git_author_email === 'bot@frida.example.com');
  check((await mine())?.runtime?.git_author === 'Kalmido <bot@frida.example.com>', 'frida: her agent\'s e-mail saved at once');

  console.log(`p2396_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
