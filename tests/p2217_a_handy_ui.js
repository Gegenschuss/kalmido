// 2.217.0 A UI tests (phone widths from audit A), own container (start.sh), Firefox. A person without an organisation (private office):
// freelancer-matrix: office
// At 360, 412 and 740x360:
// - #2794: the client card name keeps the width (more than 8rem, at most two lines), no sideways page scroll
// - #2795: the offer editor never scrolls sideways, also not while a select has the focus
// - #2796: a search hit shows its title wider than 8rem (not cut to 3-4 letters)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2217_a_handy_ui', check, shots: 'P2217A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2217A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Mustermann Medienproduktion und Verleih GmbH & Co. KG', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE'});
  check(!!cl.id, 'client created');
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: cl.id, items: [{title: 'Dreh', qty: 1, rate: 500}]});
  check(!!offer.id, 'offer created');
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Postproduktion Imagefilm Frühjahr'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Steuerunterlagen zusammenstellen', list_id: L});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const noSide = `(() => { const d = document.scrollingElement || document.documentElement; return d.scrollWidth <= innerWidth + 1 && scrollX === 0; })()`;
  const sideInfo = `JSON.stringify([(document.scrollingElement || document.documentElement).scrollWidth, innerWidth, scrollX])`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    for (const [w, h] of [[360, 740], [412, 915], [740, 360]]) {
      const tag = `${w}x${h}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      // ---- #2794
      await nav(B + `#client/${cl.id}`);
      check(await ready(ev, `!!document.querySelector('.cthead .cthn h3')`, 80), `#2794 ${tag}: the client card shows`);
      await sleep(300);
      const nm = await ev(`(() => { const e = document.querySelector('.cthead .cthn h3'); const r = e.getBoundingClientRect(); const lh = parseFloat(getComputedStyle(e).lineHeight) || 24; return JSON.stringify({w: r.width, lines: Math.round(r.height / lh)}); })()`);
      const n = JSON.parse(nm);
      check(n.w > 128 && n.lines <= 2, `#2794 ${tag}: the name keeps the width, at most two lines ${nm}`);
      check(await ev(noSide), `#2794 ${tag}: no sideways scroll ${await ev(sideInfo)}`);
      await shot(`p2217-a-2794-kunde-${tag}.png`);
      // ---- #2795
      await nav(B + `#office/offers/${offer.id}`);
      check(await ready(ev, `!!document.querySelector('.ofdgrid select')`, 80), `#2795 ${tag}: the offer editor shows`);
      await sleep(300);
      check(await ev(noSide), `#2795 ${tag}: no sideways scroll ${await ev(sideInfo)}`);
      const sel = await ev(`(() => { const out = []; for (const s of document.querySelectorAll('.ofdeditor select')) { s.focus(); s.scrollIntoView({block: 'nearest', inline: 'nearest'}); const d = document.scrollingElement || document.documentElement; if (scrollX !== 0 || d.scrollWidth > innerWidth + 1 || s.getBoundingClientRect().right > innerWidth + 1) out.push((s.id || s.name) + ':' + Math.round(s.getBoundingClientRect().width)); } document.activeElement?.blur(); return JSON.stringify(out); })()`);
      check(sel === '[]', `#2795 ${tag}: a focused select never pushes the page sideways ${sel}`);
      await shot(`p2217-a-2795-angebot-${tag}.png`);
      // ---- #2796
      await nav(B + '#inbox');
      await sleep(800);
      await ev(`(() => { openPalette(); const i = document.querySelector('.palette .pqin'); i.value = 'Steuer'; PAL.q = 'Steuer'; palDraw(); return 1; })()`);
      check(await ready(ev, `[...document.querySelectorAll('.palette .pitem .plt')].some(e => e.textContent.includes('Steuerunterlagen'))`, 40), `#2796 ${tag}: the task is found`);
      const pw = await ev(`(() => { const e = [...document.querySelectorAll('.palette .pitem .plt')].find(e => e.textContent.includes('Steuerunterlagen')); return Math.round(e.getBoundingClientRect().width); })()`);
      check(pw > 128, `#2796 ${tag}: the hit title is wider than 8rem (${pw} px)`);
      await shot(`p2217-a-2796-suche-${tag}.png`);
      await ev(`(() => { closePalette(); return 1; })()`);
    }
  }, false);

  console.log(`p2217_a_handy_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
