// 2.577.0 D (#4708 8) UI tests (jsdom), fresh DB: every dialog with fgModal keeps its input over an ended session / a reload /
// a closed tab (fdDialog with an automatic key: the dialog's title, its fields and their values when it opened)
// - typed into a dialog, the page goes (pagehide): kept; the same dialog in the same state opens again: the input is back
// - the same dialog with other opening values (the record was saved elsewhere meanwhile): nothing comes back
// - a dialog that calls fdDialog itself (own key) is not kept a second time under an automatic key
// - closing the dialog (page still there) drops what was kept
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: ck}, body: JSON.stringify({lang: 'en', tour: 'done'})});
  const w = await boot({user: 'alice'});
  check(await until(() => w.eval('S.booted')), 'setup: the app is up');
  const kept = () => w.eval(`(() => { const o = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (/\\.fdf\\./.test(k)) o[k] = localStorage.getItem(k); } return o; })()`);
  const open = (val, own) => w.eval(`(() => { const md = modal('<h3>Probe 4708</h3><input id="p4708" value="${val}"><textarea id="p4708t"></textarea>'); md.id = 'p4708md'; fgModal(md);${own ? " fdDialog(md, 'own.4708');" : ''} return 1; })()`);
  const type = v => w.eval(`(() => { const t = document.querySelector('#p4708md #p4708t'); t.value = ${JSON.stringify(v)}; t.dispatchEvent(new Event('input', {bubbles: true})); t.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
  const gone = () => w.eval(`(() => { dispatchEvent(new Event('pagehide')); document.querySelector('#p4708md')?.remove(); return 1; })()`);

  // ================= kept while typing, back in the same dialog
  open('Anfang');
  check(await until(() => w.eval('document.querySelector("#p4708md")?._fdOn === true')), 'fgModal hands the dialog to fdDialog (after the caller\'s own setup)');
  type('Entwurf eins');
  check(await until(() => Object.values(kept()).some(v => /Entwurf eins/.test(v))), 'the typed input is kept in this browser ' + JSON.stringify(Object.keys(kept())));
  check(Object.keys(kept()).some(k => /\.fdf\.\d+\.auto\./.test(k)), 'under an automatic key of the dialog');
  gone();
  check(Object.values(kept()).some(v => /Entwurf eins/.test(v)), 'the page went (pagehide): the input stays kept');
  open('Anfang');
  check(await until(() => w.eval('document.querySelector("#p4708md #p4708t")?.value') === 'Entwurf eins'), 'the same dialog in the same state: the input is back');
  w.eval('document.querySelector("#p4708md").remove()');
  check(await until(() => !Object.values(kept()).some(v => /Entwurf eins/.test(v))), 'closed with the page still there: the kept input is dropped');

  // ================= other opening values: nothing comes back
  open('Anfang');
  await until(() => w.eval('document.querySelector("#p4708md")?._fdOn === true'));
  type('Entwurf zwei');
  await until(() => Object.values(kept()).some(v => /Entwurf zwei/.test(v)));
  gone();
  open('Anders gespeichert');
  await until(() => w.eval('document.querySelector("#p4708md")?._fdOn === true'));
  check(w.eval('document.querySelector("#p4708md #p4708t")?.value') === '', 'the dialog opened with other values (saved elsewhere): nothing of the old input comes back');
  w.eval('document.querySelector("#p4708md").remove()');
  w.eval("for (const r of fdList('fdf')) fdDrop('fdf', r.id)");

  // ================= a dialog with its own fdDialog: one key only
  open('Anfang', true);
  await until(() => w.eval('document.querySelector("#p4708md")?._fdOn === true'));
  type('Eigener Schluessel');
  await until(() => Object.values(kept()).some(v => /Eigener Schluessel/.test(v)));
  const ks = Object.keys(kept()).filter(k => /Eigener Schluessel/.test(kept()[k]));
  check(ks.length === 1 && /\.own\.4708$/.test(ks[0]), 'a dialog with its own fdDialog keeps it once, under its own key ' + JSON.stringify(ks));
  w.eval('document.querySelector("#p4708md").remove()');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2577_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
