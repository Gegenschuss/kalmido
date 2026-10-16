// 2.53.0 UI tests, part E (jsdom): agent tone (#1451) + tags overview (#446). Invented data only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const DATA = process.argv[2] || path.join(__dirname, '.data');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  const post = async (u, b) => (await fetch(B + u.replace(/^\//, ''), {method: 'POST', headers: {...H, Cookie: ck}, body: JSON.stringify(b)})).json().catch(() => ({}));
  const today = new Date().toISOString().slice(0, 10);
  const t1 = await post('/api/tasks', {title: 'Paint the fence', tags: ['garden', 'weekend'], due: today});
  const t2 = await post('/api/tasks', {title: 'Buy seeds', tags: ['garden']});
  const t3 = await post('/api/tasks', {title: 'Old job', tags: ['garden']});
  await post(`/api/tasks/${t3.id}/complete`, {});
  check(t1.id && t2.id && t3.id, 'tasks created');

  // ---- #1451 agent tone: human / agent x new / read
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const html = w.eval(`(() => {
    S.tl = S.tl || {}; S.tl.agents = [901]; S.tl.seen = 100; S.tl.can_write = true; S.sel = null;
    const U = {}; const mk = (id, uid) => commentHtml({id, user_id: uid, body: 'Hello', created_at: new Date().toISOString(), task_id: 1, attachments: []}, U);
    return [mk(101, 901), mk(102, 7), mk(50, 901), mk(51, 7)];
  })()`);
  const has = (h, c) => new RegExp(`class="cm [^"]*\\b${c}\\b`).test(h);
  check(has(html[0], 'agc') && has(html[0], 'new'), 'agent + new: agc and new');
  check(!has(html[1], 'agc') && has(html[1], 'new'), 'human + new: no agc');
  check(has(html[2], 'agc') && !has(html[2], 'new'), 'agent + read: agc only');
  check(!has(html[3], 'agc') && !has(html[3], 'new'), 'human + read: plain');
  check(/class="abadge"/.test(html[0]), 'the agent badge stays');
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  const blk = css.slice(css.indexOf('/* 2.53.0 E'));
  check(!/\.agc[^{]*\{[^}]*var\(--accent\)[^}]*\}/.test(blk.replace(/\.cm\.agc\.new,\.nitem\.agc\.unread\{[^}]*\}/, '')), 'agent tone never uses --accent (except the unread strip)');
  check(/--agent-bg/.test(blk) && /--agent-ink/.test(blk), 'own variables');
  w.close();

  // ---- #446 tags overview
  w = await boot({user: 'alice', hash: 'tags'}); d = w.document;
  check(w.eval('S.route.mod') === 'tags', 'route #tags');
  const cards = [...d.querySelectorAll('#view .tgcard')];
  check(cards.length === 2, 'two cards: ' + cards.length);
  const g = cards.find(c => /#garden/.test(c.textContent));
  check(g && /2\s*open/.test(g.textContent.replace(/\s+/g, ' ')) && /1\s*done/.test(g.textContent.replace(/\s+/g, ' ')), 'garden: 2 open, 1 done: ' + (g && g.textContent.replace(/\s+/g, ' ')));
  check(g && /Next due/.test(g.textContent), 'garden shows the next due date');
  check(!!d.querySelector('#side .sg-tags [data-go="tags"]'), 'sidebar: overview button at the Tags header');
  g?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(400);
  check(w.eval('S.route.key') === 'tag:garden', 'a card opens the tag view');
  w.history.back(); await sleep(400);
  check(w.eval('S.route.mod') === 'tags', 'Back returns to the overview');
  w.close();
  w = await boot({user: 'alice', hash: 'tags', mobile: true}); d = w.document;
  check(d.querySelectorAll('#view .tgcard').length === 2, 'phone: cards shown');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
