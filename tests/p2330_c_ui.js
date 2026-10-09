// 2.33.0 UI tests, part C, own container (start.sh, KALMIDO_NOTIF_TEMPLATE=read). Firefox, 390 x 844 touch:
// #927 Share > "Notifications for members" (owner): four templates as radio cards (44 px), Read only chosen for a new share,
//      a tap saves (the folded line says which), Custom shows the events, a template per person; "Share folder" has the
//      same block; members see who limited it (Share dialog + list menu > Notifications); the one-time question to owners
//      of lists shared before 2.33 (bar with "Choose template" / "Keep as it is", answered for good)
// #834 Administration > Server > "Your IP": the address the server sees + the warning (every sign-in here comes through the
//      docker gateway, so the warning shows)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2330_c_ui', check, shots: 'P2330C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_NOTIF_TEMPLATE: 'read'}});
const sql = (q, args = []) => execFileSync('python3', ['-c', 'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], json.loads(sys.argv[3])); c.commit()',
  path.join(DATA, 'tasks.db'), q, JSON.stringify(args)]);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  await login('carol');
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const F1 = (await call('POST', '/api/lists', {name: 'In the folder', folder: 'Crew'})).id;
  await call('PUT', '/api/folders/people', {folder: 'Crew', user_id: BOB, role: 'edit'});

  const ffLogin = async ({ev, nav}, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'login alice');
    await nav(B + '#l/' + L); await ready(ev);

    // ================= #927 the owner's block in the Share dialog
    await ev(`(() => { shareModal(${L}); return 1; })()`); await sleep(1200);
    const s1 = await ev(`(() => { const sec = document.querySelector('#sh-sec-ntf'); if (!sec) return null; sec.open = true; const rs = [...sec.querySelectorAll('input[name="ntf-tpl"]')];
      return {n: rs.length, vals: rs.map(x => x.value).join(), on: rs.find(x => x.checked)?.value, st: document.querySelector('#sh-st-ntf').textContent, h: Math.min(...[...sec.querySelectorAll('.ntfopt')].map(x => x.getBoundingClientRect().height)),
        ppl: [...sec.querySelectorAll('[data-ntfu]')].map(x => +x.dataset.ntfu).join(), cust: sec.querySelector('.ntfcust').hidden}; })()`);
    check(s1 && s1.n === 4 && s1.vals === 'read,work,all,custom' && s1.on === 'read' && s1.st === 'Read only', '#927: four templates, a new share on Read only ' + JSON.stringify(s1));
    check(s1 && s1.h >= 44 && s1.ppl === String(BOB) && s1.cust === true, '#927: cards >= 44 px, bob per person, events hidden ' + JSON.stringify(s1));
    await ev(`(() => { document.querySelector('#sh-sec-ntf input[value="work"]').click(); return 1; })()`); await sleep(1000);
    let j = await call('GET', `/api/lists/${L}/notify-template`);
    check(j.own?.tpl === 'work' && await ev(`document.querySelector('#sh-st-ntf').textContent`) === 'Collaborate', '#927: a tap saves Collaborate ' + JSON.stringify(j.own));
    await ev(`(() => { document.querySelector('#sh-sec-ntf input[value="custom"]').click(); return 1; })()`); await sleep(1000);
    const s2 = await ev(`(() => { const c = document.querySelector('#sh-sec-ntf .ntfcust'); return {hid: c.hidden, n: c.querySelectorAll('[data-ntfc]').length, on: [...c.querySelectorAll('[data-ntfc]:checked')].map(x => x.dataset.ntfc).join()}; })()`);
    check(!s2.hid && s2.n === 14 && s2.on === 'mention,reply,assign,approval,comment,reminder', '#927: Custom shows the events, starting from Collaborate ' + JSON.stringify(s2));
    await ev(`(() => { document.querySelector('#sh-sec-ntf [data-ntfc="comment"]').click(); return 1; })()`); await sleep(1000);
    j = await call('GET', `/api/lists/${L}/notify-template`);
    check(j.own?.tpl === 'custom' && j.own.custom.comment === 0 && j.own.custom.mention === 1, '#927: unticking an event saves it ' + JSON.stringify(j.own));
    await ev(`(() => { const s = document.querySelector('#sh-sec-ntf [data-ntfu]'); s.closest('details').open = true; s.value = 'all'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`); await sleep(1000);
    j = await call('GET', `/api/lists/${L}/notify-template`);
    check(j.people.find(p => p.user_id === BOB)?.own?.tpl === 'all', '#927: a template for bob only ' + JSON.stringify(j.people));
    await ev(`(() => { document.querySelector('#sh-sec-ntf input[value="read"]').click(); return 1; })()`); await sleep(900);
    await ev(`(() => { document.querySelector('#sh-sec-ntf').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p2330c-390-share.png');
    await ev(`(() => { document.querySelectorAll('.modal, .mwrap').forEach(m => m.remove()); return 1; })()`);

    // ================= "Share folder" has the same block
    await ev(`(() => { folderPeopleModal('Crew'); return 1; })()`); await sleep(1500);
    const s3 = await ev(`(() => { const sec = document.querySelector('#fp-sec-ntf'); if (!sec) return null; return {n: sec.querySelectorAll('input[name="ntf-tpl"]').length, st: document.querySelector('#fp-st-ntf').textContent}; })()`);
    check(s3 && s3.n === 4 && s3.st === 'Read only', '#927: Share folder has the block ' + JSON.stringify(s3));
    await ev(`(() => { const sec = document.querySelector('#fp-sec-ntf'); sec.open = true; sec.querySelector('input[value="work"]').click(); return 1; })()`); await sleep(1000);
    j = await call('GET', '/api/folders/notify-template?folder=Crew');
    check(j.own?.tpl === 'work', '#927: the folder template saved ' + JSON.stringify(j.own));
    await ev(`(() => { document.querySelectorAll('.modal, .mwrap').forEach(m => m.remove()); return 1; })()`);

    // ================= #834 Administration > Server > Your IP
    await ev(`(() => { settingsModal('users'); return 1; })()`); await sleep(800);
    await ev(`(() => { document.querySelector('[data-admsub="server"]').click(); return 1; })()`); await sleep(1500);
    const s4 = await ev(`(() => { const b = document.querySelector('#s-ipbox'); return b ? {ip: b.querySelector('.ipv')?.textContent || '', priv: b.textContent.includes('private address'), warn: !!b.querySelector('.ipwarn')} : null; })()`);
    check(s4 && /^[0-9a-f.:]+$/i.test(s4.ip) && s4.priv, '#834: Your IP shows the address the server sees ' + JSON.stringify(s4));
    check(s4 && s4.warn, '#834: the warning shows (three accounts from the one gateway address) ' + JSON.stringify(s4));
    await ev(`(() => { document.querySelector('#s-ip-h').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p2330c-390-ip.png');
    await ev(`(() => { document.querySelectorAll('.modal, .mwrap, .smodal').forEach(m => m.remove()); return 1; })()`);

    // ================= the one-time question (as after the migration)
    sql("INSERT OR REPLACE INTO list_notif(list_id,user_id,tpl,custom,updated_at) VALUES(?,0,'all',NULL,'2026-10-01T00:00:00Z')", [L]);
    sql("INSERT OR REPLACE INTO user_settings(user_id,key,value) VALUES(1,'notif_tpl_ask','1')");
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + L); await ready(ev);
    const s5 = await ev(`(() => { const b = document.querySelector('#ntfask'); if (!b) return null; const bs = [...b.querySelectorAll('button')]; return {txt: bs.map(x => x.textContent).join('|'), h: Math.min(...bs.map(x => x.getBoundingClientRect().height)), w: b.getBoundingClientRect().right <= innerWidth + .5}; })()`);
    check(s5 && s5.txt === 'Choose template|Keep as it is' && s5.h >= 44 && s5.w, '#927: the owner is asked once (bar, 44 px buttons) ' + JSON.stringify(s5));
    await shot('p2330c-390-ask.png');
    await ev(`(() => { document.querySelector('#ntfask [data-act="ntfask-choose"]').click(); return 1; })()`); await sleep(1500);
    check(await ev(`!!document.querySelector('#sh-sec-ntf[open]')`), '#927: "Choose template" opens the Share dialog at the notifications');
    await ev(`(() => { document.querySelectorAll('.modal, .mwrap').forEach(m => m.remove()); document.querySelector('#ntfask [data-act="ntfask-keep"]').click(); return 1; })()`); await sleep(1000);
    const st = await call('GET', '/api/state');
    check(!(await ev(`!!document.querySelector('#ntfask')`)) && st.notif_ask.length === 0, '#927: "Keep as it is" answers it for good');

    // ================= the member's view
    check(await ffLogin(o, 'bob') === 200, 'login bob');
    sql('DELETE FROM list_notif WHERE list_id=?', [L]);
    await nav(B + '#l/' + L); await ready(ev);
    const s6 = await ev(`(() => { shareModal(${L}); const h = document.querySelector('.ntfhint'); const own = !!document.querySelector('#sh-sec-ntf'); document.querySelectorAll('.modal, .mwrap').forEach(m => m.remove()); return {h: h ? h.textContent.trim() : '', own}; })()`);
    check(s6.h === 'Alice has limited the notifications for this list: Read only' && !s6.own, '#927: the member sees who limited it, without the owner block ' + JSON.stringify(s6));
    await ev(`(() => { bellMenu(document.querySelector('#top h1'), ${L}); return 1; })()`); await sleep(400);
    const s7 = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()).join('|')`);
    check(s7.includes('Alice has limited the notifications for this list: Read only'), '#927: list menu > Notifications says it too ' + s7);
    await ev(`(() => { closePop(); return 1; })()`);
    check(!(await ev(`!!document.querySelector('#ntfask')`)), '#927: members are not asked');
  });
  console.log(`p2330_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
