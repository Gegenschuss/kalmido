// kalmido-suite: fresh
// 2.331.0 D (#3308): every dialog footer (.modal .card>.foot) sticks to the bottom of the card. Firefox 390 touch + 1440 mouse:
// a long dialog (many text fields, like the office texts / contracts) shows Save without scrolling, inside the card and clickable
// (elementFromPoint = the button); a short dialog keeps its footer where it was (right below the content, no sticky offset).
// freelancer-matrix: dialogs (client-only, no route, same for a person without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2331_d_ui', check, shots: 'P2331D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview')`).catch(() => false)); i++) await sleep(300); await sleep(500); };
  // opens a dialog with `n` text rows and a normal footer; returns the geometry of the footer against the card
  const probe = (n) => `(async () => {
    document.querySelectorAll('.modal').forEach(m => m.remove());
    const rows = Array.from({length: ${n}}, (_, i) => '<div class="row"><label for="t' + i + '">Text ' + i + '</label><textarea id="t' + i + '" rows="3"></textarea></div>').join('');
    const md = modal('<h3>Probe</h3>' + rows + '<div class="foot"><button class="btn" data-m="close">Cancel</button><button class="btn pri" data-m="save">Save</button></div>');
    const card = md.querySelector('.card'), b = md.querySelector('[data-m="save"]'), foot = md.querySelector('.foot');
    card.scrollTop = 0;
    let prev = ''; for (let i = 0; i < 40; i++) { const q = JSON.stringify(b.getBoundingClientRect()); if (q === prev) break; prev = q; await new Promise(r => setTimeout(r, 100)); }
    const c = card.getBoundingClientRect(), r = b.getBoundingClientRect(), f = foot.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    // the old footer rule (no sticky): the button must sit where it sat before
    const was = {t: r.top, b: r.bottom}; foot.style.cssText = 'position:static;margin:1.125rem 0 0;padding:0';
    const o = b.getBoundingClientRect(); foot.style.cssText = '';
    return {scrolls: card.scrollHeight > card.clientHeight + 2, cardOverflow: getComputedStyle(card).overflowY, pos: getComputedStyle(foot).position,
      inside: r.top >= c.top && r.bottom <= c.bottom + 1, hit: !!hit && (hit === b || b.contains(hit)), h: Math.round(r.height), moved: Math.round(Math.abs(o.top - was.t) + Math.abs(o.bottom - was.b))};
  })()`;
  for (const [tag, w, hgt, touch] of [['390', 390, 844, true], ['1440', 1440, 900, false]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o;
      await o.nav(B + 'static/icon.svg');
      await ev(`localStorage.clear(), localStorage.setItem('tasks.theme', '"light"'), 1`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: hgt}});
      await o.nav(B + '#today'); await ready(ev);
      const long = await ev(probe(12));
      check(long.scrolls && (long.cardOverflow === "auto" || long.cardOverflow === "scroll"), `${tag}: the card is the scroll container and the long dialog scrolls ` + JSON.stringify(long));
      check(long.pos === 'sticky' && long.inside && long.hit && long.h >= 28, `${tag}: long dialog, Save visible without scrolling and takes the click ` + JSON.stringify(long));
      await shot(`p2331d-${tag}-long.png`);
      const short = await ev(probe(1));
      check(!short.scrolls && short.inside && short.hit, `${tag}: short dialog, Save in the card ` + JSON.stringify(short));
      check(short.moved <= 1, `${tag}: short dialog, the button sits where it sat before the change ` + JSON.stringify(short));
      await shot(`p2331d-${tag}-short.png`);
    }, touch);
  }
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
