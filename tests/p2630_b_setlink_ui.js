// 2.630.0 UI test, part B (#4519): "(Settings > Modules)" in a hint is a link that opens the settings at that section.
// kalmido-suite:
// - a view whose module is off (Clients) shows the hint with a link; a press opens the settings on Modules
// - setLinkHtml: "Settings > Organisation > People" links to the section Organisation (the whole way is the link text), a way
//   it does not know ("Settings > Nowhere") and text with markup stay text (escaped)
// Own container (start.sh), Firefox, invented data only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2630_b_setlink_ui', check, shots: 'P2630BSL_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2630BSL_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'});
  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#home');
    check(await ready(ev, `typeof setLinkHtml === 'function'`), 'the helper is there');
    // the helper alone
    const h = JSON.parse(await ev(`JSON.stringify({a: setLinkHtml('Off (Settings > Modules).'), b: setLinkHtml('Admins (Settings > Organisation > People); more'), c: setLinkHtml('Gone (Settings > Nowhere)'), d: setLinkHtml('<b>x</b> & (Settings > Modules)'), e: setLinkHtml('<i>x</i> (Settings > Modules)', true)})`));
    check(/\(<a [^>]*data-setlink="modules"[^>]*>Settings &gt; Modules<\/a>\)\./.test(h.a), 'Modules: the way is a link ' + h.a);
    check(/data-setlink="org"[^>]*>Settings &gt; Organisation &gt; People<\/a>\); more/.test(h.b), 'Organisation > People: the whole way is the link text ' + h.b);
    check(!/<a /.test(h.c) && /Nowhere/.test(h.c), 'an unknown way stays text ' + h.c);
    check(/^&lt;b&gt;x&lt;\/b&gt; &amp; \(<a /.test(h.d), 'markup in the text is escaped ' + h.d);
    check(/^<i>x<\/i> /.test(h.e), 'safe = true keeps the given HTML ' + h.e);
    // a real view: Clients are off
    await ready(ev, `typeof viewClients === 'function'`);
    // the view's output follows the settings the app is still loading after boot: draw the box anew until it shows the hint (a real state)
    check(await ready(ev, `(document.getElementById('slt')?.remove(), document.body.insertAdjacentHTML('beforeend', '<div id="slt">' + viewClients() + '</div>'), !!document.querySelector('#slt .empty a.setlink[data-setlink="modules"]'))`),
      'Clients are off: the hint has the link ' + (await ev(`typeof viewClients + ':' + (typeof clientsOn === 'function' && clientsOn()) + ':' + viewClients().slice(0, 200)`)));
    await ev(`document.querySelector('#slt .empty a.setlink').click()`);
    check(await ready(ev, `!!document.querySelector('.smodal #sp-modules:not(.hidden)')`), 'a press opens the settings on Modules');
  }, false);

  console.log(`p2630_b_setlink_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
