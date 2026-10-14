// 2.41.0 UI tests, part E (chat), own container (start.sh), jsdom:
// - #1374 "Copy" in the menu of a chat message puts text/html (the rendered message: heading, bold, list, table, link,
//   code block; plain tags with inline styles, no app classes / buttons, dark text) AND readable text/plain on the
//   clipboard (ClipboardItem, stubbed here); closing blocks (```suggest) and host notes stay out; an answer in parts
//   (also the reference launcher's "_(1/3)_") as one piece; without ClipboardItem a hidden rendered copy +
//   execCommand('copy'); "Copy as Markdown" = the raw text; the team chat the same
// - #1206 a notice of the agent (kind notice) is a small grey line in the middle (no bubble, no menu); with a file the
//   line opens it; it is no answer to my waiting message (the typing dots stay)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const v1 = async (method, url, body) => { const x = await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined}); return {...(await x.json().catch(() => ({}))), http: x.status}; };
  const say = (body, extra = {}) => v1('POST', `/agent/chats/${ME.id}`, {body, ...extra});

  // ================= #1374 copy with formatting
  const MD = '# Plan\n\nThe **whole** plan with a [link](https://example.com/doc):\n\n- one\n- `two`\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```bash\necho hi\n```';
  const one = await say(MD + '\n\n```suggest\nStart the build\n```');
  const noted = await say('Shall I start?\n\n_Note from the launcher: this answer makes a proposal or asks you to decide, but has no approval card. Nothing of it happens without your explicit yes._');
  const P = ['Part one.\n\n_(1/3)_', 'Part *two*.\n\n_(2/3)_', 'Part three.\n\n_(3/3)_'];
  const parts = []; for (const b of P) parts.push(await say(b));
  // #1206: my question, then two notices of the agent (the second with the summary as a file)
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Status?'});
  const nt1 = await say('New session, summary taken over (22:10)', {kind: 'notice'});
  const fd = new FormData(); fd.append('body', 'Conversation compacted (22:12)'); fd.append('kind', 'notice');
  fd.append('file', new Blob(['# Summary\n\n- done\n'], {type: 'text/markdown'}), 'summary.md');
  const nt2 = await (await fetch(V + `/agent/chats/${ME.id}`, {method: 'POST', headers: {Authorization: 'Bearer ' + ag.token}, body: fd})).json();
  check(nt1.kind === 'notice' && nt2.kind === 'notice' && nt2.attachments?.length === 1, '#1206: set-up: two notices ' + JSON.stringify([nt1, nt2]).slice(0, 300));
  let w = await boot({hash: 'today'}), d = w.document;
  w.eval(`window.__toasts = []; { const __t = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return __t(m, ...a); }; }`);
  const stub = () => {
    w.__items = []; w.__clip = [];
    w.ClipboardItem = class { constructor(o) { this.o = o; } };
    Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {
      write: items => { w.__items.push(items[0].o); return Promise.resolve(); },
      writeText: t => { w.__clip.push(t); return Promise.resolve(); }}});
  };
  stub();
  w.eval(`chatOpen(${AG})`);
  const cm = id => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  await until(() => cm(one.id) && cm(parts[2].id));
  // ================= #1206 notices
  await until(() => d.querySelectorAll('#chat-msgs .cnotice').length === 2);
  const nts = [...d.querySelectorAll('#chat-msgs .cnotice')];
  check(nts.length === 2 && nts[0].textContent === 'New session, summary taken over (22:10)' && !nts[0].closest('.cmsg') && !nts[0].querySelector('.cbub, [data-act="chat-msg-menu"], a'),
    '#1206: a notice is a grey line without bubble or menu ' + (nts[0]?.outerHTML || ''));
  const na = nts[1]?.querySelector('a');
  check(na && na.textContent === 'Conversation compacted (22:12)' && /\/api\/chat-files\/\d+/.test(na.getAttribute('href')) && na.hasAttribute('data-tview'),
    '#1206: a notice with the summary opens the file ' + (nts[1]?.outerHTML || ''));
  check(!cm(nt1.id) && !cm(nt2.id), '#1206: no message row for a notice');
  check(w.eval('chatPending()?.body') === 'Status?', '#1206: a notice is no answer: my question still waits ' + w.eval('JSON.stringify(chatPending())'));
  const pick = async (sel, label) => {
    d.querySelector(sel).click();
    await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].length);
    const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
    const it = items.find(b => b.querySelector('.ml')?.textContent === label);
    if (it) it.click();
    return items.map(b => b.querySelector('.ml')?.textContent);
  };
  const types = async o => ({html: await o['text/html'].text(), plain: await o['text/plain'].text(), keys: Object.keys(o).sort().join(',')});
  let labels = await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy');
  check(labels.includes('Copy') && labels.includes('Copy as Markdown'), '#1374: "Copy" and "Copy as Markdown" in the message menu ' + JSON.stringify(labels));
  await until(() => w.__items.length);
  let c = w.__items.length ? await types(w.__items[0]) : {html: '', plain: '', keys: ''};
  check(c.keys === 'text/html,text/plain', '#1374: one ClipboardItem with text/html and text/plain ' + c.keys);
  check(/<h2[^>]*>Plan<\/h2>/.test(c.html) && /<b>whole<\/b>/.test(c.html) && /<li[^>]*>one<\/li>/.test(c.html) && /<code[^>]*>two<\/code>/.test(c.html),
    '#1374: html: heading, bold, list, inline code ' + c.html.slice(0, 400));
  check(/<table[^>]*>/.test(c.html) && /<th[^>]*>A<\/th>/.test(c.html) && /<td[^>]*>2<\/td>/.test(c.html), '#1374: html: the table ' + c.html);
  check(/<a href="https:\/\/example\.com\/doc"[^>]*>link<\/a>/.test(c.html) && !/target=|rel=/.test(c.html), '#1374: html: the link (only its address) ' + c.html);
  check(/<pre[^>]*>echo hi<\/pre>/.test(c.html), '#1374: html: the code block as plain text ' + c.html);
  check(!/class=|<button|data-|<svg|<img|<input|aria-/.test(c.html), '#1374: html: no app classes, buttons, pictures, data attributes ' + c.html);
  check(/^<div style="[^"]*color:#1f2328/.test(c.html) && !/#fff\b|#ffffff|(?:color|background):\s*white\b/i.test(c.html), '#1374: html: dark text, never white ' + c.html.slice(0, 200));
  check(!/suggest|Start the build/.test(c.html) && !/Start the build/.test(c.plain), '#1374: the ```suggest block is not copied');
  check(c.plain === 'Plan\n\nThe whole plan with a link (https://example.com/doc):\n\n- one\n- two\n\nA\tB\n1\t2\n\necho hi', '#1374: text/plain is the readable text ' + JSON.stringify(c.plain));
  await until(() => w.__toasts.includes('Copied'));
  check(w.__toasts.includes('Copied'), '#1374: "Copied" ' + JSON.stringify(w.__toasts));
  check(!w.__clip.length, '#1374: "Copy" does not write the plain text alone');
  // Copy as Markdown: the raw text, without the closing block
  await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy as Markdown');
  await until(() => w.__clip.length);
  check(w.__clip[0] === MD, '#1374: "Copy as Markdown" copies the Markdown text without the closing block ' + JSON.stringify(w.__clip));
  // a host's note stays out
  await pick(`#chat-msgs .cmsg[data-mid="a:${noted.id}"] [data-act="chat-msg-menu"]`, 'Copy');
  await until(() => w.__items.length > 1);
  c = await types(w.__items[1]);
  check(c.plain === 'Shall I start?' && !/Note from the launcher/.test(c.html), '#1374: the host note is not copied ' + JSON.stringify(c.plain));
  // an answer in three parts (the reference launcher's "_(i/n)_"), from its last part
  w.__toasts.length = 0;
  await pick(`#chat-msgs .cmsg[data-mid="a:${parts[2].id}"] [data-act="chat-msg-menu"]`, 'Copy');
  await until(() => w.__items.length > 2);
  c = await types(w.__items[2]);
  check(c.plain === 'Part one.\n\nPart two.\n\nPart three.' && /<i>two<\/i>/.test(c.html) && !/\(\d\/3\)/.test(c.html), '#1374: an answer in parts as one piece ' + JSON.stringify(c));
  await until(() => w.__toasts.includes('Copied (3 parts)'));
  check(w.__toasts.includes('Copied (3 parts)'), '#1374: the toast names the parts ' + JSON.stringify(w.__toasts));
  // without ClipboardItem: a hidden rendered copy is selected and execCommand('copy') takes it
  w.ClipboardItem = undefined;
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: undefined});
  w.__exec = null; d.execCommand = k => { const h = d.querySelector('.rcptmp'); w.__exec = k === 'copy' && h ? {html: h.innerHTML, hidden: h.getAttribute('aria-hidden'), sel: String(w.getSelection())} : null; return k === 'copy'; };
  w.__toasts.length = 0;
  await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy');
  await until(() => w.__exec);
  check(w.__exec && /<h2[^>]*>Plan<\/h2>/.test(w.__exec.html) && w.__exec.hidden === 'true' && /Plan/.test(w.__exec.sel), '#1374: without ClipboardItem the rendered copy is selected ' + JSON.stringify(w.__exec));
  check(!d.querySelector('.rcptmp'), '#1374: the hidden copy is gone afterwards');
  await until(() => w.__toasts.includes('Copied'));
  check(w.__toasts.includes('Copied'), '#1374: the old way says "Copied" ' + JSON.stringify(w.__toasts));
  // blocked everywhere
  w.__toasts.length = 0; d.execCommand = () => false;
  await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy');
  await until(() => w.__toasts.length);
  check(w.__toasts.includes('Copy failed, select the text by hand'), '#1374: blocked: "Copy failed, select the text by hand" ' + JSON.stringify(w.__toasts));
  w.close();

  // ---- team chat: Bob's message with a mention of Alice
  const RID = ((await call('GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L)?.id;
  const tm = await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Hi <@${ME.id}>, the **minutes**:\n\n- decided A`}, CKB);
  w = await boot({hash: 'team/' + RID}); d = w.document;
  w.eval(`window.__toasts = []; { const __t = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return __t(m, ...a); }; }`);
  stub();
  await until(() => d.querySelector(`#tc-msgs [data-mid="t:${tm.id}"] [data-act="tc-msg-menu"]`));
  labels = await pick(`#tc-msgs [data-mid="t:${tm.id}"] [data-act="tc-msg-menu"]`, 'Copy');
  check(labels.includes('Copy as Markdown'), '#1374: team chat: "Copy as Markdown" in the menu ' + JSON.stringify(labels));
  await until(() => w.__items.length);
  c = w.__items.length ? await types(w.__items[0]) : {html: '', plain: ''};
  check(/<b>minutes<\/b>/.test(c.html) && /@Alice/.test(c.html) && !/<button/.test(c.html), '#1374: team chat: html with bold and @Name ' + c.html);
  check(c.plain === 'Hi @Alice, the minutes:\n\n- decided A', '#1374: team chat: text/plain ' + JSON.stringify(c.plain));
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
