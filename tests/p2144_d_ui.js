// 2.144.0 D UI test (jsdom), fresh DB (#2158): Settings > Help > "Support Kalmido" names the prices of both licences (once,
// VAT included) for an admin and for a member; without a configured payment link there is no buy button (nothing points to
// a shop that is not open yet); the key field stays.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 80});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const about = await call('GET', '/api/about');
  check(about.support_prices && about.support_prices.person === 25 && about.support_prices.server === 100, 'about: the prices ' + JSON.stringify(about.support_prices));
  for (const user of ['alice', 'bob']) {
    if (user === 'bob') { CK = await login('bob'); await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}); }
    const w = await boot({user}), d = w.document;
    await sleep(500);
    w.eval(`settingsModal('help')`);
    check(await until(() => d.querySelector('.smodal #s-sup')), `${user}: the section "Support Kalmido"`);
    const sec = d.querySelector('.smodal #s-sup');
    const pr = k => sec?.querySelector(`.supprices .supprice[data-kind="${k}"]`)?.textContent || '';
    check(/Personal licence/.test(pr('person')) && /25/.test(pr('person')) && /once/.test(pr('person')), `${user}: the personal price: ` + pr('person'));
    check(/Server licence/.test(pr('server')) && /100/.test(pr('server')) && /once/.test(pr('server')), `${user}: the server price: ` + pr('server'));
    check(/[€]|EUR/.test(pr('person') + pr('server')), `${user}: the currency is named`);
    check(/include VAT/.test(sec?.textContent || ''), `${user}: VAT included, no subscription`);
    check(!sec?.querySelector('.suplink a'), `${user}: no buy button without a payment link`);
    check(!!sec?.querySelector('#s-supkey'), `${user}: the key field stays`);
    w.close();
  }
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
