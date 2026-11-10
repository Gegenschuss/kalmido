// kalmido-suite: fresh
// 2.855.0 part C (#5456) UI test: the office settings. Own container (start.sh, mode workspaces), jsdom for both people,
// Firefox (desktop, mouse) for the layout. Invented data only. freelancer-matrix: office (an organisation's admin, a person
// without one)
// - "Next running number" is one form: every field with its hint ("at least … · applies to …") right below it, ONE "Apply"
//   at the end; it saves every changed series after one question naming each jump; a series the server refuses keeps its
//   value and says why at its field (no toast), the others are saved
// - the bank page links the bank accounts (Settings › Company & office › Bank & taxes) and the link opens them
// - the pages Import and Rights name where their back button leads ("Settings › Company & office")
// - Firefox: the hint sits between its field and the next series; in the quotation's "Transfer of rights" the tick
//   "Exclusive" stands in the field column, its text right of it
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2802_c_office_settings_ui', check, shots: 'P2802C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { j = null; } j = j || {}; j.http = r.status; return j; };
const until = async (fn, n = 120) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,files,docs,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK);
  const me = (await call('GET', '/api/state', null, CK)).me;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}, CK);
  await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}, CK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);

  for (const [who, ck] of [['alice', CK], ['frida', FCK]]) {
    const range = async k => (await call('GET', '/api/office/number-ranges', null, ck)).ranges?.find(x => x.kind === k);
    await call('PUT', '/api/office/settings', {offer_scheme: 'A-{seq:03}', invoice_scheme: 'RE-{yyyy}-{seq:03}'}, ck);

    // ---- the number ranges: one form, one Apply
    let w = await boot({user: who, hash: 'today'}), d = w.document;
    await until(() => d.querySelector('#side, main'));
    const asked = []; w.confirm = m => { asked.push(String(m)); return true; };  // boot's bridge answers the app's own question with it
    w.eval(`settingsModal('biz')`);
    check(!!await until(() => d.querySelector('.smodal #onum-invoice')), `${who}: the block "Next running number"`);
    const box = () => d.querySelector('#onum-box');
    const applyB = () => box().querySelector('[data-onum="apply"]');
    check(box().querySelectorAll('[data-onum="apply"]').length === 1 && !box().querySelector('[data-onum="set"]'), `${who}: one Apply for the form, none per row`);
    check(applyB()?.closest('.row') === box().lastElementChild, `${who}: Apply stands at the end, after the last series`);
    const rows = [...box().querySelectorAll('.onumrow:not(.onumshared)')];
    check(rows.length === 5 && rows.every(rw => { const h = rw.querySelector('.onumh'); return h && h.parentElement === rw.querySelector('input[data-onum-in]')?.parentElement && /at least/.test(h.textContent) && h.id === rw.querySelector('input[data-onum-in]').getAttribute('aria-describedby'); }),
      `${who}: every field's hint stands in its field's column and belongs to it (aria-describedby)`);
    check(applyB().disabled, `${who}: nothing changed: Apply off`);
    // two series at once: one question naming both, both saved, one "Saved"
    type(w, d.querySelector('#onum-offer'), '40'); type(w, d.querySelector('#onum-delivery'), '7');
    check(!applyB().disabled, `${who}: a changed field turns Apply on`);
    w.eval(`window.__T = []; { const t0 = toast; toast = (...a) => { window.__T.push(String(a[0])); return t0(...a); }; } 1`);
    click(w, applyB());
    check(await until(async () => (await range('offer'))?.next === 40 && (await range('delivery'))?.next === 7), `${who}: one Apply saves both series (40, 7)`);
    check(asked.length === 1 && /Quotation numbers/.test(asked[0]) && /Delivery note numbers/.test(asked[0]), `${who}: one question names both jumps ${JSON.stringify(asked)}`);
    check(await until(() => w.eval('window.__T.join("|")') === 'Saved'), `${who}: one "Saved" ${w.eval('JSON.stringify(window.__T)')}`);
    check(await until(() => /at least 40/.test(d.querySelector('.onumrow[data-kind="offer"]')?.textContent || '') && applyB()?.disabled), `${who}: the rows show the new state, Apply off again`);
    // a refused series: its field says why, the other one is saved, no toast
    await idle(w);
    w.eval('window.__T.length = 0; 1');
    type(w, d.querySelector('#onum-invoice'), '50');  // a jump in the invoice series needs a reason
    await until(() => d.querySelector('#onum-invoice-why'));
    type(w, d.querySelector('#onum-reminder'), '9');
    click(w, applyB());
    check(await until(async () => (await range('reminder'))?.next === 9), `${who}: the reminder series is saved`);
    const ia = await until(() => d.querySelector('.onumrow[data-kind="invoice"] [role="alert"]'));
    check(/reason/i.test(ia?.textContent || '') && d.querySelector('#onum-invoice')?.value === '50', `${who}: the refused series says why at its field and keeps 50: ${ia?.textContent}`);
    check((await range('invoice'))?.next === 1 && w.eval('window.__T.length') === 0, `${who}: nothing saved there, no toast ${w.eval('JSON.stringify(window.__T)')}`);
    check(!applyB().disabled, `${who}: Apply stays on for the series still changed`);
    // lower than the stored number: said at the field before anything is asked
    asked.length = 0;
    type(w, d.querySelector('#onum-offer'), '3');
    d.querySelector('#onum-invoice').value = '1'; d.querySelector('#onum-invoice').dispatchEvent(new w.Event('input', {bubbles: true}));
    click(w, applyB());
    check(await until(() => /Only upwards: at least 41/.test(d.querySelector('.onumrow[data-kind="offer"] [role="alert"]')?.textContent || '')) && asked.length === 0, `${who}: a lower number is said at its field, no question`);
    w.close();

    // ---- the bank page links the bank accounts; the link leads there
    w = await boot({user: who, hash: 'office/bank'}); d = w.document;
    const ln = await until(() => d.querySelector('.office .ofcsetl [data-setgo="biz-tax"]'));
    check(!!ln && /Bank accounts/.test(ln.closest('.ofcsetl').textContent) && /Bank & taxes/.test(ln.textContent), `${who}: the bank page names the bank accounts and where they are: ${ln?.closest('.ofcsetl')?.textContent}`);
    if (ln) click(w, ln);
    check(!!await until(() => d.querySelector('.smodal #s-biz .bkaset')), `${who}: the link opens Settings with the bank accounts`);
    w.close();

    // ---- Import and Rights name where they lead back
    for (const hash of ['office/import', 'office/rights']) {
      w = await boot({user: who, hash}); d = w.document;
      const b = await until(() => d.querySelector('.office [data-setgo="biz"]'));
      check(/Settings › Company & office/.test(b?.textContent || ''), `${who}: ${hash}: the back button names its goal: ${b?.textContent}`);
      w.close();
    }
  }

  // ---- Firefox: the layout (the person without an organisation)
  const Q = await call('POST', '/api/office/docs', {kind: 'offer', items: [{title: 'Schnitt', qty: 1, rate: 100}]}, FCK);
  check(Q.http === 201, 'a quotation for the rights ' + Q.http);
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.ofcSetSub', '"docs"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#onum-invoice')`), 'ff: the number ranges');
    await ev(`(() => { document.querySelector('#onum-box').scrollIntoView({block: 'start'}); return 1; })()`);
    // the hint between its field and the next series' label, closer to its own field
    const geo = await ev(`(() => { const r = document.querySelector('.onumrow[data-kind="offer"]'), n = r.nextElementSibling;
      const i = r.querySelector('input[data-onum-in]').getBoundingClientRect(), h = r.querySelector('.onumh').getBoundingClientRect(), l = n.querySelector('label').getBoundingClientRect();
      return JSON.stringify({gapOwn: Math.round(h.top - i.bottom), gapNext: Math.round(l.top - h.bottom), left: Math.round(h.left - i.left)}); })()`);
    const g = JSON.parse(geo || '{}');
    check(g.gapOwn >= -2 && g.gapOwn < g.gapNext && Math.abs(g.left) <= 2, 'ff: the hint sits right below its field, aligned with it, before the next series ' + geo);
    await shot('p2802c-numbers.png');
    await nav(B + '#office/offers/' + Q.id);
    check(await ready(ev, `!!document.querySelector('#ofd-r-exclusive')`), 'ff: the quotation editor with "Transfer of rights"');
    await ev(`(() => { const s = document.querySelector('details.ofdsec[data-sec="rights"]'); if (s && !s.open) s.open = true; document.querySelector('#ofd-r-exclusive').scrollIntoView({block: 'center'}); return 1; })()`);
    const ex = await ev(`(() => { const c = document.querySelector('#ofd-r-exclusive').getBoundingClientRect(), f = document.querySelector('#ofd-r-exceptions').getBoundingClientRect(),
      lb = document.querySelector('#ofd-r-exclusive').closest('label'), t = document.createRange(); t.selectNodeContents(lb); const tr = [...t.getClientRects()].pop();
      return JSON.stringify({chk: Math.round(c.left), field: Math.round(f.left), textRight: Math.round(tr.right), chkRight: Math.round(c.right), sameLine: Math.abs((c.top + c.bottom) / 2 - (tr.top + tr.bottom) / 2) < 8}); })()`);
    const e = JSON.parse(ex || '{}');
    check(Math.abs(e.chk - e.field) <= 4 && e.textRight > e.chkRight && e.sameLine, 'ff: "Exclusive": the tick in the field column, its text right of it on the same line ' + ex);
    await shot('p2802c-exclusive.png');
  }, false);

  console.log(`p2802_c_office_settings_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
