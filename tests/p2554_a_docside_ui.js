// kalmido-suite:
// 2.554.0 UI test, part A (#4469: the document sidebar in order): the box "To review" is one compact line (text left, "Checked"
// right; phone: the buttons below at full width); with a stack the stack question is the box's own buttons and "Checked" comes
// only after "No stack"; due date + new task + link = one line with one button "Task…" and its menu; the action row is one line
// with the red trash icon button at the end (tooltip + aria-label). Own container (start.sh), Firefox, 1280 px and 390 px.
// Invented data only. A person without organisation (the freelancer case).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2554_a_docside_ui', check, shots: 'P2554A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2554A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const STACK = `
import base64, io, json, sys, segno
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=44)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    lines = spec.split('\\n')
    if lines[0].startswith('qr:'):
        b = io.BytesIO()
        segno.make(lines.pop(0)[3:], micro=False).save(b, kind='png', scale=8, border=4)
        im.paste(Image.open(b).convert('L'), (1200, 100))
    for i, ln in enumerate(lines):
        d.text((150, 400 + i * 90), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
`;
const stackPdf = pages => Buffer.from(execFileSync('docker', ['exec', CT, 'python', '-c', STACK, JSON.stringify(pages)]).toString().trim(), 'base64');
const up = async (ck, name, data) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([data], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
};
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  // 2.627.0 (#4981): a cover page without a code in front - since 2.580.0 (#4401) a stack whose every part starts with a fresh
  // archive number code is "clear" and split by the queue without a person (the desktop stack was gone before its sheet
  // opened: no box, the phone one only stayed because its numbers were taken by then); this one waits for a person
  const STK = ['Deckblatt ohne Code\nBeispiel Poststelle', 'qr:ASN00201\nRechnung Eins\nBeispiel Strom GmbH', 'Seite zwei der Rechnung\nSumme 12,00 EUR', 'qr:ASN00202\nVertrag Zwei\nBeispiel Versicherung AG', 'Anlage zum Vertrag\nSeite vier'];
  const wait = async id => { let x; for (let i = 0; i < 240 && !['done', 'failed'].includes((x = await call(CF, 'GET', `/api/docs/${id}`)).state); i++) await sleep(500); return x; };
  const IDS = {};  // one stack and one letter per viewport (the steps change them)
  for (const t of ['desktop', 'phone']) {
    const sid = await up(CF, `stapel-${t}.pdf`, stackPdf(STK)), one = await up(CF, `brief-${t}.pdf`, stackPdf(['Ein Brief ' + t + '\nBeispiel Verein e.V.']));
    const x = await wait(sid), y = await wait(one);
    check(x.split?.stack === true && x.review === true, t + ': the stack is marked and to review ' + JSON.stringify([x.state, x.http, x.split, x.review]));
    check(y.review === true, t + ': the letter is to review');
    IDS[t] = {sid, one};
  }
  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const R = `const r = e => e.getBoundingClientRect(), q = s => document.querySelector('.dc-md ' + s);`;
  // the review box: text, buttons, the box itself
  const BOX = `(() => { ${R} const b = q('.dc-rev'), t = q('.dc-rev .dc-revt'), a = q('.dc-rev .dc-revact'); if (!b || !t || !a) return 'null';
    return JSON.stringify({bh: Math.round(r(b).height), bw: Math.round(r(b).width), aw: Math.round(r(a).width), sameLine: r(a).top < r(t).bottom - 2, right: r(a).left > r(t).left + 40,
      below: r(a).top >= r(t).bottom - 1, checked: !!q('[data-dc="checked"]'), no: !!q('.dc-rev [data-dsp="dismiss"]'), split: !!q('.dc-rev [data-dsp="open"]'), alone: !!q('.dc-due.dsp-hint')}); })()`;
  const ACTS = `(() => { ${R} const a = [...document.querySelectorAll('.dc-md .dv-hacts > .btn, .dc-md .dv-hacts > .iconbtn, .dc-md .dv-hacts > a, .dc-md .dv-actw > .btn')].filter(e => e.getClientRects().length);  // 2.583.0 (#4835): the head of the view
    const del = a[a.length - 1];
    return JSON.stringify({n: a.length, tops: [...new Set(a.map(e => Math.round(r(e).top)))], lastDel: del.dataset.dc === 'del' && del.classList.contains('danger'),
      aria: del.getAttribute('aria-label'), title: del.getAttribute('title'), noText: del.textContent.trim() === '', atEnd: Math.abs(r(del).right - r(del.parentElement).right) <= 1}); })()`;
  const open = async (nav, ev, id, sel) => { await nav(B + 'static/icon.svg'); await nav(B + `#docs/${id}`); return ready(ev, `!!document.querySelector('.dc-md ${sel}')`); };
  const click = (ev, sel) => ev(`(() => { document.querySelector(${JSON.stringify(sel)}).click(); return 1; })()`);
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    for (const [W, tag] of [[1280, 'desktop'], [390, 'phone']]) {
      const ph = W < 600, {sid: SID, one: ONE} = IDS[tag];
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: ph ? 844 : 900}});
      // ---- a stack to review: the box carries the stack question, no "Checked" yet
      check(await open(nav, ev, SID, '.dc-rev'), tag + ': the box "To review" of the stack');
      let b = JSON.parse(await ev(BOX));
      check(b.no && b.split && !b.checked && !b.alone, tag + ': the stack question is the box\'s, no "Checked" yet ' + JSON.stringify(b));
      check(ph ? b.below && b.aw >= b.bw - 40 : b.bw < 480 ? b.below /* 2.583.0 (#4835): a narrow fields column */ : b.sameLine && b.right, tag + ': buttons ' + (ph ? 'below at full width' : 'right of the text') + ' ' + JSON.stringify(b));
      check(await ev(`(() => { ${R} const s = q('.dc-rev .dc-ht svg'), t = q('.dc-rev .dc-ht > span'); return !!s && !!t && Math.abs(r(s).top - r(t).top) < 12 && r(s).right <= r(t).left + 2; })()`), tag + ': the symbol stays with its text');
      let a = JSON.parse(await ev(ACTS));
      // 2.583.0 (#4835): the head of the view (sketch): a red "Delete" with the trash icon at the end, the text hidden on phones
      check(Math.max(...a.tops) - Math.min(...a.tops) <= 1 && a.lastDel && a.atEnd && a.aria === 'Delete' && a.title === 'Delete', tag + ': one action line, red Delete at the end ' + JSON.stringify(a));
      await shot(`p2554-a-stack-${tag}.png`);
      await click(ev, '.dc-md .dc-rev [data-dsp="dismiss"]');
      check(await ready(ev, `!!document.querySelector('.dc-md [data-dc="checked"]') && !document.querySelector('.dc-md [data-dsp="dismiss"]')`), tag + ': after "No stack" the box offers "Checked"');
      b = JSON.parse(await ev(BOX));
      check(ph ? b.below : b.bw < 480 ? b.below || (b.sameLine && b.right) /* 2.583.0 (#4835): the narrow fields column: right when it fits, else below */ : b.sameLine && b.right, tag + ': "Checked" ' + (ph ? 'below' : 'right') + ' ' + JSON.stringify(b));
      check(b.bh <= 130 || ph, tag + ': the box is a compact line ' + b.bh);
      await shot(`p2554-a-checked-${tag}.png`);
      // ---- a letter with a due date: one line "Due on …" + the button "Task…"
      await call(CF, 'PATCH', `/api/docs/${ONE}`, {due: '2026-12-01'});
      check(await open(nav, ev, ONE, '.dc-due [data-dsp="taskmenu"]'), tag + ': due date + "Task…"');
      check(await ev(`(() => { ${R} const l = q('.dc-due'), bs = l.querySelectorAll('button'), t = l.querySelector('.dc-ht'); return bs.length === 1 && bs[0].dataset.dsp === 'taskmenu' && !q('[data-dc="task"]') && !q('[data-dsp="link"]') && /Due on/.test(t.textContent) && (Math.abs(r(bs[0]).top + r(bs[0]).height / 2 - r(t).top - r(t).height / 2) < 20 || (r(l).width < 480 && r(bs[0]).top >= r(t).bottom - 2)); })()`), tag + ': one line, one button "Task…" (2.583.0, #4835: in the narrow fields column it may wrap below the text)');
      await click(ev, '.dc-md [data-dsp="taskmenu"]');
      check(await ready(ev, `(() => { const m = [...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()); return m.length === 2 && /New task/.test(m[0]) && /Link with a task/.test(m[1]); })()`, 20), tag + ': the menu has New task and Link with a task…');
      await shot(`p2554-a-taskmenu-${tag}.png`);
      await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})) && 1`);
      // no due date: only the button
      await call(CF, 'PATCH', `/api/docs/${ONE}`, {due: ''});
      check(await open(nav, ev, ONE, '.dc-due.dsp-link [data-dsp="taskmenu"]') && await ev(`document.querySelectorAll('.dc-md .dsp-link button').length === 1 && !document.querySelector('.dc-md .dsp-link .dc-ht')`), tag + ': without a due date only the button');
      // the letter's box (no stack): "Checked" in the line
      b = JSON.parse(await ev(BOX));
      check(b.checked && !b.no && (ph ? b.below : b.bw < 480 ? b.below || (b.sameLine && b.right) : b.sameLine && b.right), tag + ': plain review box ' + JSON.stringify(b));
      a = JSON.parse(await ev(ACTS));
      check(Math.max(...a.tops) - Math.min(...a.tops) <= 1 && a.lastDel, tag + ': the letter\'s action line ' + JSON.stringify(a));
      // "New task" really creates the task and shows its link
      if (!ph) {
        await call(CF, 'PATCH', `/api/docs/${ONE}`, {due: '2026-12-01'});
        check(await open(nav, ev, ONE, '[data-dsp="taskmenu"]'), 'desktop: again with a due date');
        await click(ev, '.dc-md [data-dsp="taskmenu"]');
        await ready(ev, `!!document.querySelector('#pop [role="menuitem"]')`, 20);
        await ev(`(() => { document.querySelector('#pop [role="menuitem"]').click(); return 1; })()`);
        check(await ready(ev, `!!document.querySelector('.dc-md .dc-due a[href^="#t/"]')`, 40), 'New task creates the task');
      }
    }
  }, undefined);
  console.log(F.length ? `p2554_a_docside_ui: ${F.length} failed, ${ok} ok` : `p2554_a_docside_ui: all ${ok} checks ok`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
