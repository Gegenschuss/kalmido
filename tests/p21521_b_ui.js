// 2.161.2 part B UI tests (#2609 #2610 #2611): bot moments, own container (start.sh), jsdom, a person without an organisation.
// - #2609: only the LAST open task of a list ticked off makes the figure of the now empty view nod (class bnod), the first
//   one not; also with the celebration switched off; with reduced motion nothing
// - #2610: the agent chat's line under the messages shows the bot at work (svg.bot.b-arbeitet) instead of the dots, the
//   robot icon and the text stay; the task panel's typing line keeps the dots
// - #2611: the bot at work beside the progress of the move import (bar stays), the contacts import panel (gone at the end),
//   the bank statement being read, the organisation export being created, the task import reading its file
// - the CSS: every new motion only inside prefers-reduced-motion: no-preference
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21521B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const css = f => { for (const base of [path.join(__dirname, '..', 'static'), path.join(__dirname, '..', 'app', 'static')]) { try { return fs.readFileSync(path.join(base, f), 'utf8'); } catch (e) { /* next */ } } return ''; };
const RM = '(prefers-reduced-motion: reduce)';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,contacts,office'});

  // ================= #2609: the nod only for the last open task of a list
  const lastTick = async (name, media, celebrate) => {
    await call('PATCH', '/api/settings', {celebrate});
    const L = (await call('POST', '/api/lists', {name})).id;
    const a = (await call('POST', '/api/tasks', {title: 'First', list_id: L})).id, b = (await call('POST', '/api/tasks', {title: 'Second', list_id: L})).id;
    const w = await boot({hash: 'l/' + L, media}); const d = w.document;
    await until(() => d.querySelector(`#view .trow[data-id="${a}"]`), 60);
    await w.eval(`toggleTask(${a})`); await sleep(400);
    const first = !!d.querySelector('#view .bot.bnod');
    await w.eval(`toggleTask(${b})`);
    await until(() => d.querySelector('#view .o3c-empty svg.bot'), 40);
    const res = {first, nod: !!d.querySelector('#view .o3c-empty svg.bot.bnod'), cele: !!d.querySelector('.cele,.cele-quip')};
    w.eval('celeEnd()'); w.close();
    return res;
  };
  let x = await lastTick('Errands', {}, '1');
  check(!x.first, '#2609: the first of two ticked off: no nod');
  check(x.nod, '#2609: the last one ticked off: the figure of the empty list nods ' + JSON.stringify(x));
  check(x.cele, '#2609: the celebration still comes along');
  x = await lastTick('Chores', {}, '0');
  check(x.nod && !x.cele, '#2609: celebration off: the nod alone ' + JSON.stringify(x));
  x = await lastTick('Quiet', {[RM]: true}, '1');
  check(!x.nod, '#2609: reduced motion: no nod ' + JSON.stringify(x));
  await call('PATCH', '/api/settings', {celebrate: '1'});

  // ================= #2610: the agent chat's working line
  let w = await boot({hash: 'today'}); let d = w.document;
  const P = new w.DOMParser();
  const chat = P.parseFromString(w.typingHtml([{name: 'Claude', typing: 0, busy: false}], 'chat-typing'), 'text/html');
  check(chat.querySelector('#chat-typing > svg.bot.b-arbeitet.bchat[aria-hidden="true"]') && !chat.querySelector('.atdots') && !chat.querySelector('.hdot'), '#2610: agent chat: the bot at work instead of the dots');
  // 2.290.0 B (#3160): the agent chat shows ONE bot (the figure), no second small one before the name; the task panel keeps its small one
  check(chat.querySelector('#chat-typing[role="status"][aria-live="polite"] .ttx') && /Claude is writing/.test(chat.querySelector('.ttx').textContent) && !chat.querySelector('.ttx svg.lbot') && chat.querySelectorAll('#chat-typing svg').length === 1, '#3160: the agent chat has exactly one bot, the text for screen readers stays');
  check(P.parseFromString(w.typingHtml([{name: 'Claude', typing: Infinity}], 'd-typing'), 'text/html').querySelector('.ttx svg.lbot'), '#3160: the task panel keeps the small robot before the name');
  const busy = P.parseFromString(w.typingHtml([{name: 'Claude', typing: 0, busy: true}], 'chat-typing'), 'text/html');
  check(busy.querySelector('svg.bot.b-arbeitet') && /working on it/.test(busy.querySelector('.ttx').textContent), '#2610: "working on it": the bot too');
  const task = P.parseFromString(w.typingHtml([{name: 'Bob', typing: Infinity}], 'd-typing'), 'text/html');
  check(task.querySelector('.atdots') && !task.querySelector('svg.bot'), '#2610: the task panel (people) keeps the dots');
  check(P.parseFromString(w.typingHtml([], 'chat-typing'), 'text/html').querySelector('#chat-typing.hidden') && !P.parseFromString(w.typingHtml([], 'chat-typing'), 'text/html').querySelector('svg.bot'), '#2610: nobody working: no figure');

  // ================= #2611: long jobs
  const mv = P.parseFromString(w.umzImpHtml({state: 'running', progress: {done: 3, total: 10}}), 'text/html');
  check(mv.querySelector('.umzbar .botbusy > svg.bot.b-arbeitet.bbusy') && mv.querySelector('.umzbar .bbusy-c progress[value="3"][max="10"]') && /Importing/.test(mv.body.textContent), '#2611: move import: the bot beside the bar, the bar stays');
  const up = P.parseFromString(w.umzImpHtml({state: 'upload', received: 5, size: 10}), 'text/html');
  check(up.querySelector('.botbusy svg.bot') && up.querySelector('progress') && up.querySelector('[data-umz="cancel"]'), '#2611: move upload: the bot, the bar and Cancel');
  check(!P.parseFromString(w.umzImpHtml({state: 'done', result: {}}), 'text/html').querySelector('svg.bot.bbusy'), '#2611: finished: no bot at work');
  const ox = P.parseFromString(w.oxStateHtml({enabled: true, state: 'running'}), 'text/html');
  check(ox.querySelector('.botbusy svg.bot.bbusy') && /being created/.test(ox.body.textContent), '#2611: organisation export being created: the bot');
  const p = w.ctImpPanel();
  check(d.querySelector('#ctimp > svg.bot.bbusy') && d.querySelector('#ctimp .pbar'), '#2611: contacts import: the bot beside the bar');
  p.set('Imported', null, true);
  check(d.querySelector('#ctimp.done') && /\.ctimp\.done>\.bot\.bbusy\{display:none\}/.test(css('app.css')), '#2611: contacts import ended: the bot goes');
  p.el.remove();
  const md = w.bnkImpModal('Date;Amount\n', 'a.csv');
  check(md.querySelector('.card .botbusy svg.bot.bbusy') && /Loading/.test(md.querySelector('.card').textContent), '#2611: bank statement being read: the bot');
  md.remove();
  check(w.eval('botBusy()').startsWith('<svg class="bot b-arbeitet bbusy"') && w.eval("botBusy('x', 'k')").includes('class="botbusy k"'), '#2611: one helper botBusy (figure alone / beside its content)');
  w.close();

  // ================= the CSS: the new motion only without reduced motion
  const a = css('app.css'), blk = a.slice(a.indexOf('/* 2.161.2 (#2609-#2611)'));
  check(blk.length > 50 && /@media \(prefers-reduced-motion: no-preference\)\{\s*\.bot\.bnod \.b-hop\{animation:b-nod[^}]*\}\s*\.bot\.bnod \.b-ant\{animation:b-wave/.test(blk), 'CSS: the nod only with motion allowed');
  // 2.165.0 CI (#2612-#2614): the later bot blocks have their own no-preference block, so every one is taken out
  check(!/animation:/.test(blk.replace(/@media \(prefers-reduced-motion: no-preference\)\{[\s\S]*?\n\}/g, '')), 'CSS: no animation outside the no-preference block');
  check(/@media \(prefers-reduced-motion: no-preference\)\{[^@]*\.bot\.b-arbeitet \.b-ant\{animation:b-sway/.test(a), 'CSS: the bot at work sways only with motion allowed (2.136.0 block)');

  console.log(F.length ? 'FAILED ' + F.length : 'ok ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
