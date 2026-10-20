// 2.139.0 UI tests, part D, own container (start.sh), Firefox (1440 x 900):
// - #2130: "Save as task" under every comment (own, another person's); the dialog; the "Saved" mark
// - #2401: proposal cards: no thumb emoji in the buttons' source, a bigger checkbox in .ppi
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2139_d_ui', check, shots: 'P2139D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Work'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Discuss', list_id: L})).id;
  const C1 = (await call(CA, 'POST', `/api/tasks/${T}/comments`, {body: '## My idea\nOwn words.'})).id;

  await firefox(async o => {
    const {ev, nav, shot, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(() => 1)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof openDetail === 'function' && !!document.querySelector('#view [data-id="${T}"]')`, 60), 'the list');
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"]')`), '#2130: the comment in the timeline');
    check(await ev(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-save"]')`), '#2130: "Save as task" under the own comment');
    await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-save"]').click(); return 1; })()`);
    check(await ready(`!!document.querySelector('.modal [name="cs-as"][value="sub"]')`), '#2130: the dialog');
    const dlg = await ev(`(() => { const m = document.querySelector('.modal'); return {title: m.querySelector('#cs-title')?.value, sub: m.querySelector('[name="cs-as"][value="sub"]')?.checked}; })()`);
    check(dlg.title === 'My idea' && dlg.sub === true, '#2130: title from the heading, subtask preselected ' + JSON.stringify(dlg));
    await ev(`(() => { document.querySelector('.modal [data-m="ok"]').click(); return 1; })()`);
    check(await ready(`[...S.tasks.values()].some(t => t.title === 'My idea' && t.parent_id === ${T})`, 40), '#2130: the subtask exists');
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-saved"]')`, 40), '#2130: the comment shows "Saved"');
    // #2401: no thumb emoji in the proposal buttons, bigger checkbox
    const src = await ev(`Promise.all(['asstprop','importprop','lyprop','contractprop','rules'].map(f => fetch('/static/js/' + f + '.js').then(r => r.text()))).then(a => a.some(t => t.split('\\n').some(l => /data-pp="(discard|apply)"/.test(l) && /[\\u{1F44D}\\u{1F44E}]/u.test(l))))`);
    check(src === false, '#2401: no thumb emoji inside the proposal buttons');
    const px = await ev(`(() => { const d = document.createElement('div'); d.className = 'ppi'; d.innerHTML = '<input type="checkbox" class="ppc">'; document.body.appendChild(d); const w = d.querySelector('.ppc').getBoundingClientRect().width; d.remove(); return w; })()`);
    check(px >= 21, '#2401: the proposal checkbox is bigger than 18 px: ' + px);
  }, false);

  console.log(`p2139_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
