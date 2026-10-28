// 2.371.2 (#3151): knowledge pages -- embedding pages, daily notes, template placeholders. Own container (start.sh), jsdom,
// frida = a person WITHOUT an organisation (freelancer-matrix: knowledge), invented texts only:
// - ![[Page]] shows the page framed and read only (its boxes cannot be ticked, the own ones still can), ![[Page#Heading]]
//   only the part to the next heading of the same level, a missing page / a section not there = a grey note, a page that
//   would show itself (directly or through another one) = "already shown", at most three levels, ![[…]] in code stays text,
//   a page deleted after the index came = "Page not available" (its own route decides)
// - "Today" makes journal/YYYY-MM-DD from Templates/Tagesnotiz (placeholders filled) and opens it for writing; again = the
//   same page; a daily note's arrows go to the nearest days with a note, its date field opens / makes any day
// - {{datum}} {{titel}} {{ich}} {{cursor}} (+ English names) filled in the browser, other {{…}} stay; "/" offers "Embed a page"
// - Firefox (the real layout): the frame inside the screen on a computer and a phone, the day switch in one row
// Screenshots: P23712_SHOTS.
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return c; };
const firefox = require('./ff')({tag: 'p2371_2_wiki_embed_ui', check, shots: 'P23712_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23712_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Test', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const id = {};
  const BASIS = '# Eins\n\nText eins\n\n## Unter\n\nunter text\n\n# Zwei\n\nText zwei\n\n- [ ] Kasten Basis';
  for (const [k, p, b] of [['basis', 'Basis', BASIS],
    ['haupt', 'Haupt', '- [ ] Eigener Kasten\n\n![[Basis]]\n\n![[Basis#Eins|Nur eins]]\n\n![[Fehlt]]\n\n![[Haupt]]\n\n![[Basis#Nirgends]]\n\nCode: `![[Basis]]`\n\n![[Weg]]'],
    ['k1', 'Kette1', 'K1\n\n![[Kette2]]'], ['k2', 'Kette2', 'K2\n\n![[Kette1]]'],
    ['d1', 'D1', 'Ebene1\n\n![[D2]]'], ['d2', 'D2', 'Ebene2\n\n![[D3]]'], ['d3', 'D3', 'Ebene3\n\n![[D4]]'], ['d4', 'D4', 'Ebene4\n\n![[D5]]'], ['d5', 'D5', 'Ebene5'],
    ['weg', 'Weg', 'bald weg'],
    ['tday', 'Templates/Tagesnotiz', '# {{titel}}\n\nvon {{ich}}\n\n{{cursor}}\n\nEnde'],
    ['tmeet', 'Templates/Besprechung', '# {{ Titel }} am {{datum}}\n\n{{me}} / {{title}} / {{date}}\n\n{{cursor}}x{{cursor}}\n\n{{andere}}']]) {
    id[k] = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  }
  check(Object.values(id).every(Boolean), 'setup: frida\'s private pages');

  // ================= embeds
  const w = await boot({user: 'frida', hash: 'wiki/' + id.haupt}), d = w.document;
  const md = () => d.querySelector('#view #wk-md');
  check(await until(() => md() && md().querySelectorAll('.wempg').length === 6 && !md().textContent.includes('Loading…')), 'Haupt: six frames, all loaded ' + (md()?.textContent || '').slice(0, 300));
  await call(CF, 'POST', '/api/wiki/trash', {ids: [id.weg]});  // deleted after the index came: the page's own route answers
  w.eval('S.v++; renderView()');
  const fr = () => [...md().querySelectorAll(':scope > .wempg, :scope > p > .wempg, .wempg')].filter(x => !x.parentElement.closest('.wempg'));
  check(await until(() => fr()[5]?.textContent.includes('Page not available')), 'a page deleted after the index came: "Page not available" ' + fr()[5]?.textContent);
  const [whole, part, miss, self, nosec] = fr();
  check(whole && whole.querySelector('.wempgh a')?.getAttribute('href') === '#wiki/' + id.basis && whole.textContent.includes('Text zwei') && whole.textContent.includes('unter text'), 'the whole page, its name a link ' + whole?.textContent);
  check(part && part.textContent.includes('Text eins') && part.textContent.includes('unter text') && !part.textContent.includes('Text zwei') && part.querySelector('.wempgh')?.textContent === 'Nur eins', 'Basis#Eins: to the next heading of the same level, the label as name ' + part?.textContent);
  check(miss && miss.classList.contains('wempgna') && miss.textContent.includes('Page not available'), 'a missing page: a grey note ' + miss?.textContent);
  check(self && self.textContent.includes('This page is already shown here.'), 'the page in itself: "already shown"');
  check(nosec && nosec.textContent.includes('Section not found: Nirgends'), 'a heading not there: named ' + nosec?.textContent);
  check([...md().querySelectorAll('code')].some(c => c.textContent === '![[Basis]]'), '![[…]] in code stays text');
  check(md().querySelectorAll('input[data-wkcb]').length === 1 && whole?.querySelector('input[type=checkbox]')?.disabled && !whole?.querySelector('[data-wkcb], .wemcb'), 'the own box ticks, the embedded one is read only');
  w.location.hash = '#wiki/' + id.k1;
  check(await until(() => md()?.querySelector('.wempg .wempg')?.textContent.includes('This page is already shown here.') && md().textContent.includes('K2')), 'a loop through another page: "already shown" ' + md()?.textContent);
  w.location.hash = '#wiki/' + id.d1;
  check(await until(() => md()?.textContent.includes('Ebene4')), 'setup: the levels load ' + md()?.textContent);
  const lv = md().querySelectorAll('.wempgb').length, deep = md().querySelector('.wempg.wempgl');
  check(lv === 3 && deep && !md().textContent.includes('Ebene5') && deep.querySelector('a')?.getAttribute('href') === '#wiki/' + id.d5, 'three levels shown, the fourth a link ' + lv);

  // ================= placeholders
  const today = w.eval('today()'), dd = w.eval('fmtDate(today())');
  const f = JSON.parse(w.eval(`JSON.stringify(wk_tplFill('# {{ Titel }} am {{datum}}\\n{{me}} / {{title}} / {{date}}\\n{{cursor}}x{{cursor}}\\n{{andere}}', 'Ordner/Treffen'))`));
  check(f.text === `# Treffen am ${dd}\nFrida Test / Treffen / ${dd}\nx\n{{andere}}` && f.at === f.text.indexOf('x'), 'filled: date, name, me, the first {{cursor}} = the place, others stay ' + JSON.stringify(f));
  const mk = await w.eval(`wk_mk('private', 'Treffen', ${id.tmeet}).then(r => JSON.stringify({id: r.id, at: WK.caretNext && WK.caretNext.at}))`);
  const mj = JSON.parse(mk || '{}'), mb = (await call(CF, 'GET', '/api/wiki/pages/' + mj.id)).body;
  check(mb === `# Treffen am ${dd}\n\nFrida Test / Treffen / ${dd}\n\nx\n\n{{andere}}` && mj.at === mb.indexOf('x'), 'a page from a template: saved filled, writing starts at {{cursor}} ' + JSON.stringify([mb, mj]));
  check(w.eval(`wklv_cmds('private').some(c => c.k === 'embp' && c.ins === '![[')`), '"/" offers "Embed a page"');

  // ================= daily notes
  w.location.hash = '#wiki';
  const tb = await until(() => d.querySelector('#view [data-wk="today"]'));
  check(tb, 'the bar has "Today" next to "New page"');
  tb?.click();
  const jp = await until(async () => ((await call(CF, 'GET', '/api/wiki?space=private')).pages || []).find(p => p.path === 'journal/' + today));
  check(jp, 'Today made journal/' + today);
  const jb = jp && (await call(CF, 'GET', '/api/wiki/pages/' + jp.id)).body;
  check(jb === `# ${today}\n\nvon Frida Test\n\n\n\nEnde`, 'from Templates/Tagesnotiz, placeholders filled ' + JSON.stringify(jb));
  check(await until(() => w.location.hash === '#wiki/' + jp?.id && w.eval('WK.edit') && w.eval('WK.pg && WK.pg.id') === jp?.id), 'the note opens for writing ' + w.location.hash);
  w.eval('WK.edit = false; renderView()');
  d.querySelector('#view [data-wk="today"]')?.click();
  await sleep(800);
  const js = ((await call(CF, 'GET', '/api/wiki?space=private')).pages || []).filter(p => p.path.startsWith('journal/'));
  check(js.length === 1 && w.location.hash === '#wiki/' + jp?.id, 'Today again: the same page, no second one ' + js.length);
  const old = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'journal/2020-01-02', body: 'alt'})).id;
  w.eval('WK.idx.private.v = -1; WK.pg._v = -1; renderView()');
  const bar = await until(() => d.querySelector(`#view .wkday [data-wkday="2020-01-02"]`) && d.querySelector('#view .wkday'));
  check(bar && bar.querySelector('input[type=date]')?.value === today && bar.querySelectorAll('button[disabled]').length === 1, 'the day switch: the earlier note, no later one, the date field on this day');
  bar?.querySelector('[data-wkday="2020-01-02"]').click();
  check(await until(() => w.location.hash === '#wiki/' + old), 'the arrow opens the earlier note');
  const back = await until(() => d.querySelector(`#view .wkday [data-wkday="${today}"].btn`));
  check(back, 'an older note offers "Today"');
  const di = d.querySelector('#view .wkday input[type=date]');
  if (di) { di.value = '2020-03-04'; di.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const np = await until(async () => ((await call(CF, 'GET', '/api/wiki?space=private')).pages || []).find(p => p.path === 'journal/2020-03-04'));
  check(np && await until(() => w.location.hash === '#wiki/' + np.id), 'the date field makes and opens that day\'s note');

  // ================= Firefox: the real layout
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    for (const [vw, vh, tag] of [[1280, 900, 'desk'], [390, 844, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '#wiki/' + id.haupt);
      if (!check(await ready(ev, `document.querySelectorAll('#wk-md .wempg').length === 6 && !document.querySelector('#wk-md').textContent.includes('Loading…')`), `Firefox ${tag}: the frames draw`)) continue;
      const g = JSON.parse(await ev(`(() => { const s = document.querySelector('#wk-md .wempg'), a = s.getBoundingClientRect(), m = document.querySelector('#wk-md').getBoundingClientRect(), cs = getComputedStyle(s);
        return JSON.stringify({inside: a.left >= m.left - 1 && a.right <= Math.min(m.right, document.documentElement.clientWidth) + 1, line: parseFloat(cs.borderLeftWidth) >= 2, bg: cs.backgroundColor !== getComputedStyle(document.querySelector('#wk-md')).backgroundColor}); })()`) || '{}');
      check(g.inside && g.line && g.bg, `Firefox ${tag}: the frame inside the text, a line on the left, its own background ` + JSON.stringify(g));
      await shot(`p23712-embed-${tag}.png`);
      await nav(B + '#wiki/' + old);
      if (!check(await ready(ev, `!!document.querySelector('.wkday input[type=date]')`), `Firefox ${tag}: the day switch shows`)) continue;
      const r = JSON.parse(await ev(`(() => { const xs = [...document.querySelectorAll('.wkday > *')].map(x => x.getBoundingClientRect()); return JSON.stringify({row: xs.every(x => Math.abs(x.top - xs[0].top) < 12), inside: xs.every(x => x.right <= document.documentElement.clientWidth)}); })()`) || '{}');
      check(r.row && r.inside, `Firefox ${tag}: the day switch in one row, inside the screen ` + JSON.stringify(r));
      await shot(`p23712-day-${tag}.png`);
    }
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
