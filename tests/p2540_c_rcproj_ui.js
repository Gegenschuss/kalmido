// 2.540.0 part C UI test (#4471), own container (start.sh): the project of a receipt in the document sheet is picked with
// kalmido-suite:
// the project picker of quotations and invoices (tch_listPicker, #3606) instead of a native select: a button with the
// project's icon and name, the picker with "No project" on top, the recently chosen projects in their own group, the
// project icons, a search from 10 entries, a sheet on the phone; picking saves (one undo step) and the button shows it.
// A person without an organisation (private receipt), desktop and the phone width 390. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});

async function upload(name) {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([`Receipt ${name} total 12.50 EUR`]), name + '.txt');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const j = await r.json().catch(() => ({}));
  return (j.ids || (j.docs || j.items || []).map(x => x.id))[0];
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  check(!(st.me?.workspaces || []).length, 'setup: alice is in no organisation');
  const feat = (st.settings?.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...feat, 'docs'])].join(',')});
  const P = {};
  for (const n of ['🛒 Errands', 'Trade fair', ...Array.from({length: 9}, (_, i) => 'Extra ' + (i + 1))]) P[n] = (await call('POST', '/api/lists', {name: n, kind: 'project', org_id: null})).id;
  const D0 = await upload('older'), D1 = await upload('desk'), D2 = await upload('phone');
  check(D0 && D1 && D2, 'setup: three documents');
  check((await call('PUT', `/api/docs/${D0}/receipt`, {project_id: P['Extra 2'], category: 'Material'})).status === 200, 'setup: an older receipt with the project Extra 2');
  for (const d of [D1, D2]) await call('PUT', `/api/docs/${d}/receipt`, {project_id: null, category: 'Material'});
  const rc = async d => (await call('GET', `/api/docs/${d}/receipt`)).receipt?.project?.id || null;

  for (const [D, mobile, who] of [[D1, false, 'desktop'], [D2, true, 'phone']]) {
    const w = await boot({user: 'alice', hash: `docs/${D}`, mobile}), d = w.document;
    const b = await until(() => d.querySelector('.rc-slot #rc-proj'), 80);
    check(b?.tagName === 'BUTTON' && b.getAttribute('aria-haspopup') === 'menu' && /No project/.test(b.textContent) && b.value === '', `${who}: a button "No project" instead of a select ` + b?.tagName);
    check(!d.querySelector('.rc-slot select#rc-proj'), `${who}: no native select for the project`);
    b?.click();
    const pop = await until(() => { const p = d.querySelector('#pop:not(.hidden) .menu-list'); return p && p.querySelector('[role="menuitem"]') ? p : null; });
    check(!!pop, `${who}: the picker opens`);
    const items = [...(pop?.querySelectorAll('[role="menuitem"]') || [])], heads = [...(pop?.querySelectorAll('.mgh') || [])].map(g => g.textContent);
    check(/No project/.test(items[0]?.textContent || '') && items[0]?.classList.contains('on'), `${who}: "No project" on top, checked`);
    check(heads[0] === 'Recently chosen' && heads.includes('Other projects'), `${who}: the recently chosen projects on top ` + heads.join(' | '));
    const ex2 = items.find(x => /Extra 2/.test(x.textContent)), fair = items.find(x => /Trade fair/.test(x.textContent));
    check(ex2?.closest('.mgrp')?.querySelector('.mgh')?.textContent === 'Recently chosen' && items.indexOf(ex2) < items.indexOf(fair), `${who}: Extra 2 in the recent group, before the rest`);
    const err = items.filter(x => /Errands/.test(x.textContent));
    check(err.length === 1 && err[0].querySelector('.lic') && !/🛒/.test(err[0].textContent), `${who}: the project icon instead of the raw emoji ` + err.map(x => x.textContent).join(' | '));
    check(items.filter(x => /Extra|Trade fair|Errands/.test(x.textContent)).every(x => x.querySelector('.lic')), `${who}: every project with an icon (the same indent)`);
    check(!mobile || d.querySelector('#pop .tch-sh'), `${who}: a sheet on the phone`);
    const sq = d.querySelector('#pop #mq-q');
    check(!!sq, `${who}: a search field from 10 entries`);
    if (sq) {
      sq.value = 'trade'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
      const shown = [...pop.querySelectorAll('[role="menuitem"]')].filter(x => !x.closest('[hidden]') && !x.hidden);
      check(shown.length === 1 && /Trade fair/.test(shown[0].textContent), `${who}: the search leaves one entry ` + shown.map(x => x.textContent).join(' | '));
    }
    fair?.click();
    check(await until(async () => (await rc(D)) === P['Trade fair']), `${who}: picking saves the project`);
    check(await until(() => d.querySelector('.rc-slot #rc-proj')?.value === String(P['Trade fair']) && /Trade fair/.test(d.querySelector('.rc-slot #rc-proj').textContent)), `${who}: the button shows the project`);
    check(w.eval(`HIST.undo.length && /Changed receipt/.test(HIST.undo[HIST.undo.length - 1].label)`), `${who}: one undo step`);
    await w.eval(`histStep('undo')`);
    check(await until(async () => (await rc(D)) === null), `${who}: undo takes the project away again`);
    w.close();
  }
  console.log(`p2540_c_rcproj_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
