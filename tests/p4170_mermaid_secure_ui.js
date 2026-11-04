// 2.522.0 (#4170): a diagram's own %%{init: …}%% may not switch HTML labels back on or bring its own CSS / DOMPurify
// settings / font: diagram.js locks htmlLabels, dompurifyConfig, themeCSS and fontFamily on top of Mermaid's defaults.
// kalmido-suite: fresh
// Firefox, frida (a person WITHOUT an organisation, freelancer-matrix: knowledge), invented texts only.
// Without the fix the first diagram is drawn with HTML labels (foreignObject) and the second carries the injected colour.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P4170_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p4170_mermaid_secure_ui', check, lazy: true});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const BODY = '# Locked\n\n```mermaid\n%%{init: {"htmlLabels": true, "flowchart": {"htmlLabels": true}}}%%\nflowchart LR\n  A[Alpha] --> B[Beta]\n```\n\n'
  + '```mermaid\n%%{init: {"themeCSS": ".node rect { fill: #a1b2c3; }", "fontFamily": "Papyrus", "dompurifyConfig": {"ADD_TAGS": ["iframe"]}}}%%\nflowchart LR\n  C[Gamma] --> D[Delta]\n```';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const pg = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Locked', body: BODY})).id;
  check(pg, 'setup: frida\'s private page');

  await firefox(async ({ev, nav, cmd, ctx}) => {
    const until = async (expr, n = 160) => { for (let i = 0; i < n; i++) { const x = await ev(expr).catch(() => null); if (x) return x; await sleep(250); } return ev(expr).catch(() => null); };
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + `#wiki/${pg}`);
    const r = await until(`(() => { const s = [...document.querySelectorAll('#wk-md .wkdgmm svg')]; if (s.length < 2) return null;
      return s.map(x => ({fo: x.querySelectorAll('foreignObject').length, html: x.querySelectorAll('div, span, iframe').length,
        txt: [...x.querySelectorAll('text, foreignObject')].map(t => t.textContent).join(' ').replace(/\\s+/g, ' ').trim().slice(0, 80), css: [...x.querySelectorAll('style')].map(t => t.textContent).join(' ')})); })()`);
    console.log('svgs', JSON.stringify(r && r.map(x => ({...x, css: x.css.length}))));
    check(r && r.length === 2, 'both diagrams are drawn');
    check(r && r[0].fo === 0 && r[0].html === 0 && /Alpha/.test(r[0].txt) && /Beta/.test(r[0].txt), `%%{init}%% htmlLabels: the labels stay SVG text, no foreignObject (${JSON.stringify(r && r[0].fo)})`);
    check(r && !/a1b2c3/i.test(r[1].css) && !/Papyrus/.test(r[1].css) && /Gamma/.test(r[1].txt), '%%{init}%% themeCSS / fontFamily do not reach the drawing');
    check(r && r[1].html === 0, 'dompurifyConfig from the text allows nothing more');
  });
  console.log(`p4170_mermaid_secure_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
