// 2.223.0 C (#2820): fixed emoji became app icons (svg) in the packing templates, the health dialog + card, the family card
// and an organisation without its own picture; own container (start.sh, isolated test database).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const EMO = /[🏖🏊🎒⛺💼🩺📋💉💊🎂💍🏢🎁]/u;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: "cal,comments,collab,contacts,events,family,contracts,home,care,health,review,travel,reading"});
  await call('POST', '/api/family/occasions', {title: 'Birthday Mia', kind: 'birthday', due: new Date(Date.now() + 3 * 864e5).toISOString().slice(0, 10), name: 'Mia'}).catch(() => {});
  for (const width of [1280, 390]) {
    let w = await boot({user: 'alice', hash: 'family', mobile: width < 500}), d = w.document;
    await until(() => d.querySelector('#view .fc-pack'));
    const pk = [...d.querySelectorAll('#view .fc-pack [data-act="fam-pack"]')];
    check(pk.length === 5 && pk.every(b => b.querySelector('svg') && !EMO.test(b.textContent)), `packing templates: svg, no emoji (${width})`);
    w.eval('healthModal()'); await sleep(200);
    const md = d.querySelector('.modal.lifedlg');
    const cards = [...md.querySelectorAll('[data-ht]')];
    check(cards.length === 4 && cards.every(b => b.querySelector('svg') && !EMO.test(b.textContent)), `health types: svg, no emoji (${width})`);
    md.remove();
    const fam = d.querySelector('#view');
    check(!EMO.test(fam.textContent), `family view: no fixed emoji (${width})`);
    w.close();
  }
  // org without a picture + reward without a picture: the helper output
  const w = await boot({user: 'alice', hash: 'family'});
  check(/<svg/.test(w.eval(`ic('building')`)) && /<svg/.test(w.eval(`ic('gift')`)) && /<svg/.test(w.eval(`ic('syringe')`)) && w.eval(`P.syringe`).length > 20, 'icons building, gift, syringe exist');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
