// kalmido-suite: fresh
// 2.883.0 (#5560) UI test: the "More" sheet of the phone's tab bar (decision of 10.11.2026): every entry has its real icon
// (never the three dots), no place stands twice (an overflowing pinned Calendar / Reading only under Areas), and the
// sheet has no empty head line with only the X.
// Own container (start.sh), jsdom, invented data only, a person without an organisation.
// freelancer-matrix: n/a (navigation of the tab bar, no route)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'}, CK);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'cal,wiki,sheets,reading', workspace: 'private'}, CK);

  const w = await boot({user: 'alice', hash: 'today', mobile: true}), d = w.document;
  check(await until(() => d.querySelector('#tabs button')), 'the tab bar is drawn');
  // pinned: more than fit on a phone; Knowledge pages, Calendar and Reading overflow into "More". The area Knowledge is
  // hidden in the drawer (the photo of 10.11.), so Knowledge pages stays a View - with the book, not the three dots
  w.eval(`LS.set('tabbar', ['s:inbox', 's:today', 'search', 'lists', 'wiki', 'm:cal', 'a:reading']); S.settings.nav_menus = '{}'; S.settings.sidebar = JSON.stringify({hidden: ['e:wiki']}); render()`);
  check(!JSON.parse(w.eval(`JSON.stringify(tabAreaItems().map(t => t.id))`)).includes('wiki'), 'the area Knowledge is hidden in the drawer');
  check(await until(() => d.querySelector('#tabs [data-act="tabs-more"]')), 'More is in the tab bar');
  const ov = JSON.parse(w.eval(`JSON.stringify(tabOverflow().rest.map(t => t.id))`));
  check(ov.includes('wiki') && !ov.includes('m:cal') && !ov.includes('a:reading'), '#5560: Views keep Knowledge pages, Calendar and Reading go to Areas only ' + ov.join('|'));
  d.querySelector('#tabs [data-act="tabs-more"]').click();
  check(await until(() => d.querySelector('#pop [role="menuitem"]')), 'More opens');
  const M = JSON.parse(w.eval(`JSON.stringify([...document.querySelectorAll('#pop [role="menuitem"]')].map(b => ({l: b.querySelector('.ml')?.textContent || '', i: b.querySelector('.mlic') ? 'lic' : b.querySelector('svg.i')?.innerHTML || ''})))`));
  const P = JSON.parse(w.eval(`JSON.stringify(Object.fromEntries(['book', 'dots'].map(n => { const t = document.createElement('div'); t.innerHTML = ic(n); return [n, t.firstChild.innerHTML]; })))`)), inner = h => h;  // the same serialisation as the menu's
  const labels = M.map(x => x.l);
  // (1) the real icon: Knowledge pages has the book, no entry falls back to the three dots
  const wk = M.find(x => x.l === 'Knowledge pages');
  check(wk && wk.i === inner(P.book), '#5560: Knowledge pages has the book icon, not the dots: ' + JSON.stringify(wk));
  check(M.every(x => x.i && x.i !== inner(P.dots)), '#5560: every entry has its own icon ' + JSON.stringify(M.filter(x => !x.i || x.i === inner(P.dots)).map(x => x.l)));
  // (2) nothing twice: Calendar and Reading once each, under Areas
  const n = l => labels.filter(x => x === l).length;
  check(n('Calendar') === 1 && n('Reading') === 1, '#5560: Calendar and Reading stand once ' + labels.join('|'));
  const grp = l => [...d.querySelectorAll('#pop .mgrp')].find(g => [...g.querySelectorAll('.ml')].some(s => s.textContent === l))?.querySelector('.mgh')?.textContent;
  check(grp('Calendar') === 'Areas' && grp('Knowledge pages') === 'Views', '#5560: Calendar under Areas, Knowledge pages under Views: ' + grp('Calendar') + ' / ' + grp('Knowledge pages'));
  // (3) no empty head line: the head is the grip's line, the X stays (closes the sheet)
  const hd = d.querySelector('#pop .tch-sh');
  check(hd && hd.classList.contains('tch-sh0') && hd.querySelector('.tch-shx'), '#5560: the head is the slim grip line with the X');
  hd.querySelector('.tch-shx').click();
  check(await until(() => d.getElementById('pop').classList.contains('hidden')), '#5560: the X closes the sheet');
  // a pick still goes there: Calendar from Areas
  d.querySelector('#tabs [data-act="tabs-more"]').click();
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => b.querySelector('.ml')?.textContent === 'Calendar')?.click();
  check(await until(() => w.eval('S.route.mod') === 'cal'), '#5560: Calendar from More opens the calendar ' + w.eval('S.route.mod'));
  // the area Knowledge shown again: the pinned Knowledge pages is the same place -> once, under Areas, no heading Views
  w.eval(`closePop(); S.settings.sidebar = '{}'; render()`);
  const ov2 = JSON.parse(w.eval(`JSON.stringify(tabOverflow().rest.map(t => t.id))`));
  check(ov2.length === 0, '#5560: with the area Knowledge in the drawer nothing stays under Views ' + ov2.join('|'));
  // without overflow the heading Views is gone
  w.eval(`LS.set('tabbar', ['s:inbox', 's:today', 'm:cal', 'a:reading']); render()`);
  w.eval(`tabsMore(document.querySelector('#tabs [data-act="tabs-more"]') || document.querySelector('#top h1'))`);
  check(await until(() => d.querySelector('#pop [role="menuitem"]')), 'More opens again');
  const hs = [...d.querySelectorAll('#pop .mgh')].map(h => h.textContent);
  check(!hs.includes('Views'), '#5560: no heading Views when nothing overflows ' + hs.join('|'));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
