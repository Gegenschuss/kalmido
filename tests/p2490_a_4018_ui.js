// kalmido-suite: fresh
// 2.490.0 A (#4018) UI test (jsdom), own container: the comment head's time is one short line (today "21:14", this year
// "26.10. 15:21" without weekday, another year "26.10.2025"), it cannot wrap (white-space:nowrap), and in a narrow column
// (container query, not device) the action icons leave the row until hover / focus / a tap on the comment.
const {boot, sleep, B, login, allCssSync, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: ck}, body: JSON.stringify({lang: 'de', tour: 'done'})});
  const w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#view'));
  const iso = ms => new Date(w.Date.now() + ms).toISOString();
  const head = ms => {
    const h = w.eval(`commentHtml({id: 987654, user_id: S.me.id, created_at: ${JSON.stringify(iso(ms))}, body: 'Hallo', attachments: []}, {[S.me.id]: 'Kalmido-Dev'})`);
    const t = d.createElement('div'); t.innerHTML = h;
    return t.querySelector('.chead .cwhen');
  };
  const DAY = 86400000;
  let el = head(-60000);
  check(el && /^\d\d:\d\d$/.test(el.textContent.trim()), 'today: only the time: ' + (el && el.textContent));
  const wk = new Date(w.Date.now() - 7 * DAY);
  el = head(-7 * DAY);
  if (wk.getFullYear() === new Date(w.Date.now()).getFullYear()) check(el && /^\d\d\.\d\d\. \d\d:\d\d$/.test(el.textContent.trim()), 'a week ago: short form without weekday: ' + (el && el.textContent));
  el = head(-400 * DAY);
  check(el && /^\d\d\.\d\d\.\d{4}$/.test(el.textContent.trim()), 'another year: day and year: ' + (el && el.textContent));
  check(el && !/Mo|Di|Mi|Do|Fr|Sa|So/.test(el.textContent), 'no weekday');
  const css = allCssSync();
  check(/\.chead \.cwhen\{[^}]*white-space:nowrap/.test(css), 'the time cannot wrap (nowrap)');
  check(/\.chead\{[^}]*flex-wrap:wrap/.test(css), 'the head wraps so the time moves under the name when tight');
  check(/@container cmain \(max-width:[\d.]+rem\)\{[^}]*\.cacts\{[^}]*display:none/.test(css.replace(/\n/g, '')), 'narrow container: the action icons are hidden');
  check(/\.cm\.cacton \.cacts/.test(css), 'a tap (class cacton) shows them again');
  // tap toggles the class (no real layout in jsdom)
  const cm = d.createElement('div'); cm.className = 'cm'; cm.innerHTML = '<div class="cmain"><div class="cbody">x</div></div>'; d.body.appendChild(cm);
  cm.querySelector('.cbody').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(cm.classList.contains('cacton'), 'a tap on the comment shows the icons');
  cm.querySelector('.cbody').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(!cm.classList.contains('cacton'), 'a second tap hides them');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
