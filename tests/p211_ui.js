// 2.1.1 UI tests (jsdom), own container (start.sh): #326 model usage of the agents
// Settings > AI colleague > Usage (admin: every agent, the limit line, the chart, top tasks, lists, models, tokens / cost,
// one agent, a top task opens the task; a member: only the agents in their lists, no limits), the agent dialog's usage
// limit (saved, soft > hard refused), the card in the Agents view ("Details"), "limit reached" on the agent, the task
// panel's "AI usage" line, the News text + icon of a usage alert, the notification row (admins only), phone, German; SW v61
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(6[1-9]|7[0-4])'/.test(SW), 'service worker cache v61 (2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {username: 'codex', display_name: 'Codex'});
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  const SECRET = (await call('POST', '/api/lists', {name: 'Secret'})).id;
  for (const [lid, uid] of [[TEAM, BOB], [TEAM, ag.id], [SECRET, ag2.id]]) await call('PUT', `/api/lists/${lid}/members`, {user_id: uid, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Write the release notes', list_id: TEAM})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Plan the sprint', list_id: TEAM})).id;
  const TS = (await call('POST', '/api/tasks', {title: 'Secret plan', list_id: SECRET})).id;
  for (const b of [{task_id: T1, input_tokens: 12000, output_tokens: 3000, cache_read_tokens: 90000, cache_write_tokens: 5000, cost_usd: 0.42},
    {task_id: T2, input_tokens: 2000, output_tokens: 500, cost_usd: 0.05}, {task_id: T1, input_tokens: 1000, output_tokens: 1000, model: 'claude-small'}]) {
    const r = await v1(ag.token, 'POST', '/agent/usage', {model: 'claude-big', ...b});
    check(r.status === 201, 'report ' + r.status);
  }
  check((await v1(ag2.token, 'POST', '/agent/usage', {model: 'gpt-x', input_tokens: 700, output_tokens: 300, task_id: TS})).status === 201, 'codex reports');

  // ================= Settings > AI colleague > Usage (admin)
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    const w = await boot({user: 'alice', mobile, hash: 'today'}), d = w.document;
    w.eval(`settingsModal('usage')`); await sleep(1200);
    const box = d.querySelector('#sp-ai #s-aiu');
    check(box && !d.querySelector('#sp-ai').classList.contains('hidden') && !d.querySelector('#aisp-usage').hidden && d.querySelector('[data-aisub="usage"]').getAttribute('aria-selected') === 'true', `${lab}: the sub-tab Usage in AI colleague`);
    // 2.5.1 (#393): one summary card per agent; the charts behind "Details" (closed)
    const rows = [...box.querySelectorAll('.aiusum[data-aiu-agent]')];
    check(box.querySelector('details#aiu-det') && !box.querySelector('details#aiu-det').open, `${lab}: Details closed at first`);
    check(rows.length === 2 && /Claude/.test(rows[0].textContent) && /Codex/.test(rows[1].textContent), `${lab}: every agent (admin) ${rows.length}`);
    check(/24(\.|,)5K|24(\.|,)5k/i.test(rows[0].querySelectorAll('.aiuv')[0].textContent), `${lab}: Claude today 24.5K tokens (${rows[0].querySelectorAll('.aiuv')[0]?.textContent})`);
    check(box.querySelector('svg.chart .ch-bar') && /Tokens per day/.test(box.textContent), `${lab}: the chart per day`);
    const tops = [...box.querySelectorAll('.aiutasks [data-aiu-open]')];
    check(tops.length === 3 && tops.length <= 5 && tops[0].textContent.includes('Write the release notes'), `${lab}: top tasks, biggest first (${tops.map(x => x.textContent).join('|')})`);
    check(/Per list/.test(box.textContent) && /Per model/.test(box.textContent), `${lab}: per list + per model (SVG labels)`);
    check(/claude-small/.test(box.innerHTML) && /Secret/.test(box.innerHTML), `${lab}: model + list names in the charts`);
    if (!mobile) {
      click(w, box.querySelector('[data-aiu-m="cost"]')); await sleep(300);
      check(/\$0\.47/.test(d.querySelector('#s-aiu .aiusum[data-aiu-agent]').textContent) && /Cost per day/.test(d.querySelector('#s-aiu').textContent), 'cost view: $0.47');
      click(w, d.querySelector('#s-aiu [data-aiu-m="tokens"]')); await sleep(300);
      const sel = d.querySelector('#aiu-ag'); sel.value = String(ag2.id); change(w, sel); await sleep(900);
      check([...d.querySelectorAll('#s-aiu .aiutasks [data-aiu-open]')].map(x => x.textContent.trim()).join() === 'Secret plan', 'one agent: its tasks only');
      d.querySelector('#aiu-ag').value = ''; change(w, d.querySelector('#aiu-ag')); await sleep(900);
      click(w, d.querySelector('#s-aiu [data-aiu-open]')); await sleep(700);
      check(!d.querySelector('.smodal') && w.eval('S.sel') === T1, 'a top task closes the dialog and opens the task');
      check(/Agent usage/.test(d.querySelector('#detail').textContent) && /22K tokens/i.test(d.querySelector('#detail .aiuse')?.textContent || '') && /\$0\.42/.test(d.querySelector('#detail .aiuse').textContent) && /2 reports/.test(d.querySelector('#detail .aiuse').textContent),
        'task panel: AI usage line: ' + d.querySelector('#detail .aiuse')?.textContent);
    }
    w.close();
  }
  // a task without usage: no line
  let w = await boot({user: 'alice', hash: 't/' + (await call('POST', '/api/tasks', {title: 'Nothing', list_id: TEAM})).id}), d = w.document; await sleep(400);
  check(d.querySelector('#detail') && !d.querySelector('#detail .aiuse'), 'no AI usage line without usage');
  w.close();

  // ================= the limit in the agent dialog
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('agents')`); await sleep(1200);
  click(w, d.querySelector(`#s-ags [data-agid="${ag.id}"] [data-ag="edit"]`)); await sleep(400);
  let md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('#ag-lper') && md.querySelector('#ag-lmet') && md.querySelector('#ag-lsoft') && md.querySelector('#ag-lhard'), 'agent dialog: limit fields');
  md.querySelector('#ag-lsoft').value = '50000'; md.querySelector('#ag-lhard').value = '10000';
  click(w, md.querySelector('[data-m="ok"]')); await sleep(700);
  check(/soft limit must not be above/.test(md.querySelector('#ag-err').textContent) && !md.querySelector('#ag-err').hidden, 'soft > hard: the error in the dialog');
  md.querySelector('#ag-lsoft').value = '20000'; md.querySelector('#ag-lhard').value = '30000';
  click(w, md.querySelector('[data-m="ok"]')); await sleep(900);
  let adm = (await call('GET', '/api/admin/agents')).agents.find(a => a.id === ag.id);
  check(adm.limits && adm.limits.soft === 20000 && adm.limits.hard === 30000 && adm.limits.period === 'day' && adm.limits.metric === 'tokens', 'limits saved: ' + JSON.stringify(adm.limits));
  await sleep(600);
  // 2.5.1 (#393): the agent card names a limit only once it is reached; the Usage tab shows it as a bar with the line
  const row = d.querySelector(`#s-ags [data-agid="${ag.id}"]`);
  check(row && !/hard limit/i.test(row.textContent), 'agent card: no limit line while under the limit');
  click(w, d.querySelector('.smodal [data-aisub="usage"]')); await sleep(1000);
  const lim = d.querySelector(`#s-aiu .aiusum[data-aiu-agent="${ag.id}"] .aiulim`);
  check(lim && lim.querySelector('.aiub i') && /hard limit 30K tokens/i.test(lim.textContent) && /per day/.test(lim.textContent), 'usage card: the limit bar + line: ' + lim?.textContent.replace(/\s+/g, ' ').slice(0, 200));
  w.close();
  // over the hard limit: "limit reached"
  await v1(ag.token, 'POST', '/agent/usage', {model: 'claude-big', input_tokens: 10000, output_tokens: 0});
  check((await v1(ag.token, 'GET', '/lists')).status === 429, 'the agent is blocked');
  w = await boot({user: 'bob', hash: 'agents'}); d = w.document; await sleep(900);
  const card = [...d.querySelectorAll('.agcard')].find(x => /Claude/.test(x.textContent));
  check(card && /limit reached/.test(card.textContent), 'Agents view: "limit reached" on the agent');
  const uc = d.querySelector('#view .aiucard');
  check(uc && /Agent usage/.test(uc.textContent) && /Claude/.test(uc.textContent) && !/Codex/.test(uc.textContent) && /limit reached/.test(uc.textContent), 'Agents view: the usage card (bob: only Claude)');
  click(w, uc.querySelector('[data-act="aiu-more"]')); await sleep(1200);
  check(d.querySelector('.smodal #sp-ai:not(.hidden) #aisp-usage:not([hidden]) #s-aiu .aiusum[data-aiu-agent]'), '"Details" opens Settings > AI colleague > Usage');
  const bb = d.querySelector('#s-aiu');
  check(bb.querySelectorAll('.aiusum[data-aiu-agent]').length === 1 && !/hard limit/.test(bb.textContent) && !/Secret plan/.test(bb.innerHTML) && !/gpt-x/.test(bb.innerHTML),
    'bob: only Claude, no limits, nothing of the secret list');
  check(/counted in the lists you see/.test(d.querySelector('#sp-ai').textContent), 'bob: the member hint');
  w.close();

  // ================= News + notification row
  w = await boot({user: 'alice', hash: 'news'}); d = w.document; await sleep(1200);
  const it = [...d.querySelectorAll('.nitem.k-usage')];
  check(it.length >= 1 && /Claude reached its usage limit/.test(it[0].textContent) && /calls are blocked/.test(it[0].textContent), 'News: the hard limit item: ' + it[0]?.textContent.replace(/\s+/g, ' ').slice(0, 160));
  check(/used 80 %/.test(w.eval(`newsText({kind: 'usage', data: {name: 'X', level: 'soft80', used: 8, limit: 10, metric: 'cost', period: 'month'}}, {})`)), 'News text 80 %');
  click(w, it[0]); await sleep(600);
  check(w.eval('S.route.mod') === 'agents', 'opening it shows the Agents view');
  w.eval(`settingsModal('notify')`); await sleep(700);
  check(d.querySelector('[data-nm="usage"][data-ch="push"]')?.checked && d.querySelector('[data-nm="usage"][data-ch="news"]')?.checked, 'admin: the notification row "usage"');
  w.close();
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('notify')`); await sleep(700);
  check(!d.querySelector('[data-nm="usage"]') && [...d.querySelectorAll('#sp-notify .nmr')].filter(r => !r.querySelector('[data-nm="proposal"]')).length === 14, 'bob: no usage row (14 rows; 2.3.0: + the proposal row, 2.7.0: + repeated reminders)');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('usage')`); await sleep(1200);
  check(/Verbrauch/.test(d.querySelector('[data-aisub="usage"]')?.textContent || '') && /Tokens pro Tag/.test(d.querySelector('#s-aiu').textContent) && /Limit erreicht/.test(d.querySelector('#s-aiu').textContent), 'German');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  const e = errs.filter(x => !/Could not load|ECONNREFUSED|fetch failed|NetworkError/.test(x));
  check(!e.length, 'no page errors: ' + e.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
