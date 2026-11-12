// 2.213.0 UI tests (#2788 the chat box on the phone), Firefox. Own container (start.sh; P2213_NOSTART=1: the container
// runs already). Invented data only.
// - phone widths 360 and 412 px, agent chat, team chat and thread: the box takes at least 60 % of the row, every button
//   in the row is at least 44 x 44 px, nothing sticks out; the tools (attach, meeting, reference, microphone) sit behind
//   ONE plus; Send is a round icon button without text (its name stays in aria-label)
// - the plus opens a menu with the tools as labelled rows (44 px high, inside the window), a second tap, a tap elsewhere,
//   a chosen tool and Esc close it; the attach row still opens the file picker
//   2.1011.0 (#5689): the menu is the shared menu() in #pop: on a phone the sheet from below with the title "More" and X; a tap
//   on the scrim (elsewhere), Esc and a chosen tool close it; after the tool the focus is back in the box
// - (2.411.0 #3446: Stop is no button in the box any more, it is the first entry of the header's ⋯ menu)
// - the voice message bar covers the whole team chat row (not the plus menu)
// - desktop 1280 px: the chat panel: icon Send, the box >= 60 % (2.350.0 #2793; before: Send with its text)
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2213_ui', check, shots: 'P2213_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2213_NOSTART) {
  fs.rmSync(DATA, {recursive: true, force: true}); fs.mkdirSync(DATA, {recursive: true});
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
}
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,agents,team,contacts,events';

// in the page: the row's measures (only what is drawn; the plus menu's rows apart)
const MEASURE = `window.__vis = el => { if (!el) return false; const s = getComputedStyle(el), r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
window.__row = sel => { const c = document.querySelector(sel); if (!c) return null; const r = c.getBoundingClientRect(), ta = c.querySelector('textarea');
  const btns = [...c.querySelectorAll('button')].filter(b => __vis(b) && !b.closest('.chtools, .tvcrec'));
  const send = c.querySelector(':scope > .btn.pri'), plus = c.querySelector(':scope > .chplus');
  return {row: Math.round(r.width), ta: Math.round(ta.getBoundingClientRect().width), ratio: ta.getBoundingClientRect().width / r.width,
    small: btns.filter(b => { const q = b.getBoundingClientRect(); return q.width < 43.5 || q.height < 43.5; }).map(b => (b.dataset.act || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)),
    out: btns.concat(ta).filter(b => { const q = b.getBoundingClientRect(); return q.left < r.left - 1 || q.right > r.right + 1; }).map(b => b.dataset.act || b.className),
    over: c.scrollWidth > c.clientWidth + 1, plus: __vis(plus), send: __vis(send), sendText: send ? send.innerText.trim() : null, sendName: send?.getAttribute('aria-label') || '',
    tools: [...c.querySelectorAll('.chclip, .mtgbtn, .rfins, .tvcmic')].filter(__vis).filter(b => !b.closest('.chtools') || __vis(b.closest('.chtools')) && getComputedStyle(b.closest('.chtools')).display !== 'contents').length,
    rowTools: [...c.querySelectorAll('.chclip, .mtgbtn, .rfins, .tvcmic')].filter(b => __vis(b) && !(c.classList.contains('chmore'))).length};
};
window.__menu = () => { const p = document.querySelector('#pop'), m = p?.querySelector('[role="menu"]'); if (!m || !__vis(p) || p.classList.contains('hidden')) return {open: false};
  const r = p.getBoundingClientRect(), items = [...m.querySelectorAll('[role="menuitem"]')].filter(__vis);
  return {open: true, inside: r.left >= -1 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1, sheet: p.classList.contains('sheet'), title: p.querySelector('.tch-sht')?.textContent || '',
    x: __vis(p.querySelector('.tch-shx')), n: items.length, labels: items.map(b => b.querySelector('.ml')?.firstChild?.textContent || ''), low: matchMedia('(pointer:coarse)').matches ? items.filter(b => b.getBoundingClientRect().height < 43.5).length : 0 /* the shared menu's rows: 44 px for a finger, its own height for a mouse */,
    focus: !!document.activeElement?.closest?.('#pop [role="menuitem"]')};
};
1`;

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Shoot'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Write the brief', list_id: L});
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${L}/agent`, {agent_id: ag.id});  // the agent chat needs a list shared with the agent
  const RID = ((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.list_id === L)?.id;
  check(ag.id && L && RID, 'setup: agent, list, the list channel ' + [ag.id, L, RID].join(','));
  const M1 = await call(CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Call sheet is out'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const setVal = (ev, sel, v) => ev(`(() => { const i = document.querySelector(${JSON.stringify(sel)}); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
  const tap = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');

    // ================= desktop: unchanged
    await nav(B + '#l/' + L);
    await ready(ev, `typeof S !== 'undefined' && !!S.booted`, 80);
    await ev(MEASURE);
    await ev(`(() => { chatOpen(${ag.id}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#chat-in') && !document.querySelector('#chat-in').disabled`, 60), 'desktop: the agent chat box is there');
    let m = await ev(`__row('.chcomp:has(#chat-in)')`);
    // 2.350.0 (#2793): the narrow chat panel: Send is an icon button (its name in aria-label), the tools in the row or behind the plus
    check(m && (m.rowTools >= 1 || m.plus) && m.sendText === '' && m.sendName === 'Send' && m.ratio >= 0.6, 'desktop panel: the tools in the row (or the plus), icon Send, the box >= 60 % ' + JSON.stringify(m));
    await shot('p2213-1280-agent.png');

    for (const [w, h] of [[360, 780], [412, 915]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      // ================= agent chat
      await nav(B + '#l/' + L);
      await ready(ev, `typeof S !== 'undefined' && !!S.booted`, 80);
      await ev(MEASURE);
      await ev(`(() => { chatOpen(${ag.id}); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#chat-in') && !document.querySelector('#chat-in').disabled`, 60), w + ': the agent chat box is there');
      await sleep(400);
      m = await ev(`__row('.chcomp:has(#chat-in)')`);
      check(m && m.ratio >= 0.6, `${w}: agent chat: the box takes >= 60 % of the row ` + JSON.stringify(m));
      check(m && !m.small.length && !m.out.length && !m.over, `${w}: agent chat: buttons >= 44 px, nothing sticks out ` + JSON.stringify(m));
      check(m && m.plus && m.rowTools === 0, `${w}: agent chat: one plus instead of the tools ` + JSON.stringify(m));
      check(m && m.send && m.sendText === '' && m.sendName === 'Send', `${w}: agent chat: Send is an icon button with its name ` + JSON.stringify(m));
      await shot(`p2213-${w}-agent.png`);
      // the menu
      await tap(ev, '.chcomp:has(#chat-in) [data-chmore]');
      await ready(ev, `__menu().open && __menu().focus`, 20);
      let mn = await ev(`__menu()`);
      // 2.1011.0 (#5689): the shared menu: a sheet from below with the title "More", its X, the focus on the first entry
      check(mn.open && mn.inside && mn.sheet && mn.title === 'More' && mn.x && mn.focus && mn.n >= 2 && !mn.low, `${w}: agent chat: the plus opens the sheet "More" ` + JSON.stringify(mn));
      check(mn.labels?.includes('Attach images or files') && mn.labels?.includes('Insert reference'), `${w}: agent chat: the menu rows have their names ` + JSON.stringify(mn.labels));
      await shot(`p2213-${w}-agent-menu.png`);
      await tap(ev, '#scrim');
      check(await ready(ev, `!__menu().open`, 20), `${w}: a tap elsewhere (the scrim) closes the menu`);
      await tap(ev, '.chcomp:has(#chat-in) [data-chmore]');
      await ready(ev, `__menu().open`, 20);
      await tap(ev, '#pop .tch-shx');
      check(await ready(ev, `!__menu().open`, 20), `${w}: the X closes the sheet`);
      await tap(ev, '.chcomp:has(#chat-in) [data-chmore]');
      await ready(ev, `__menu().focus`, 20);
      await ev(`(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
      check(await ready(ev, `!__menu().open`, 20), `${w}: Esc closes the menu`);
      // the attach row still opens the file picker, the menu closes, the focus goes back into the box
      await tap(ev, '.chcomp:has(#chat-in) [data-chmore]');
      await ready(ev, `__menu().open`, 20);
      await ev(`(() => { window.__picked = 0; const f = document.querySelector('#chat-file'); f.click = () => { window.__picked++; }; return 1; })()`);
      await tap(ev, '#pop [data-act="chtool-chclip"]');
      check(await ready(ev, `window.__picked === 1 && !__menu().open`, 20), `${w}: the attach row opens the file picker and closes the menu`);
      check(await ready(ev, `document.activeElement?.id === 'chat-in'`, 20), `${w}: after the tool the focus is back in the box ` + await ev(`document.activeElement?.id || document.activeElement?.className || '-'`));
      // 2.411.0 (#3446): Stop is no button in the box any more (the first entry of the header's ⋯ menu); typed text keeps Send
      check(!(await ev(`!!document.querySelector('#chat-stop, .chcomp .chstop')`)), `${w}: no Stop button in the box (#3446)`);
      await setVal(ev, '#chat-in', 'one more thing');
      m = await ev(`__row('.chcomp:has(#chat-in)')`);
      check(m && m.send && !m.small.length && !m.out.length, `${w}: typed: Send stays, nothing small or outside ` + JSON.stringify(m));
      await setVal(ev, '#chat-in', '');

      // ================= team chat
      await nav(B + '#team/' + RID);
      check(await ready(ev, `typeof S !== 'undefined' && !!S.booted && !!document.querySelector('#tc-in')`, 80), w + ': the team chat box is there');
      await ev(MEASURE);
      await sleep(400);
      m = await ev(`__row('.tccomp:not(.tthcomp)')`);
      check(m && m.ratio >= 0.6 && !m.small.length && !m.out.length && !m.over, `${w}: team chat: box >= 60 %, buttons >= 44 px ` + JSON.stringify(m));
      check(m && m.plus && m.rowTools === 0 && m.sendText === '' && m.sendName === 'Send', `${w}: team chat: plus + icon Send ` + JSON.stringify(m));
      await shot(`p2213-${w}-team.png`);
      await tap(ev, '.tccomp [data-chmore]');
      await ready(ev, `__menu().open`, 20);
      mn = await ev(`__menu()`);
      check(mn.open && mn.inside && mn.sheet && mn.title === 'More' && mn.n >= 2 && !mn.low, `${w}: team chat: the menu ` + JSON.stringify(mn));
      await shot(`p2213-${w}-team-menu.png`);
      await tap(ev, '#scrim');
      await ready(ev, `!__menu().open`, 20);
      // the voice bar over the whole row
      if (await ev(`!!document.querySelector('.tccomp .tvcmic')`)) {
        await ev(`(() => { TVC.st = {rid: ${RID}, phase: 'send', ms: 3000}; tvc_draw(); return 1; })()`);
        const vb = await ev(`(() => { const b = document.querySelector('.tvcrec'), c = b?.closest('.tccomp'); if (!b || !c) return null; return {inMenu: !!b.closest('.chtools'), w: Math.round(b.getBoundingClientRect().width), row: Math.round(c.getBoundingClientRect().width)}; })()`);
        check(vb && !vb.inMenu && Math.abs(vb.w - vb.row) <= 2, `${w}: the voice bar covers the row ` + JSON.stringify(vb));
        await ev(`(() => { TVC.st = null; tvc_draw(); return 1; })()`);
      }
      // ================= thread (only the reference button: no menu needed)
      if (M1?.id) {
        await ev(`(() => { tth_open(${RID}, ${M1.id}, true); return 1; })()`);
        if (await ready(ev, `!!document.querySelector('#tth-in')`, 40)) {
          await sleep(300);
          m = await ev(`__row('.tthcomp')`);
          check(m && m.ratio >= 0.6 && !m.small.length && !m.out.length && m.sendText === '', `${w}: thread: box >= 60 %, buttons >= 44 px, icon Send ` + JSON.stringify(m));
          await shot(`p2213-${w}-thread.png`);
          await ev(`(() => { tth_close(); return 1; })()`);
        } else check(false, `${w}: thread: the box is there`);
      }
    }
  });
  console.log(`p2213_ui: ${ok} passed, ${F.length} failed`);
  if (F.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });
