// kalmido-suite: fresh
// 2.497.0 (#4056): a title in the list is edited where and as it stands: same wrapping over several lines, the row keeps its
// height, the start stays visible, the caret at the double-click, Enter saves without a line break, pasted breaks become
// spaces, Esc cancels, a click beside saves. Computer and phone. Screenshots into $P2497C_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2497_c_ttledit_ui', check, shots: 'P2497C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const LONG = 'Start of a really long task title that wraps over several lines in the list because it just keeps going with more and more words about the colour grading of the kitchen scene and the sound mix that follows afterwards and then some more words to be sure about the wrapping End';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', show_done_default: '1', show_done_new: '0'});
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(x => x.status)`);
  };
  for (const [wd, ht, tag] of [[1200, 800, '1200'], [390, 844, '390']]) {
    const T = (await call('POST', '/api/tasks', {title: LONG})).id, T2 = (await call('POST', '/api/tasks', {title: 'Short one ' + tag})).id;
    await firefox(async o => {
      const {cmd, ev, ctx} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      check(await ffLogin(o) === 200, `${tag}: login`);
      await o.nav(B + '#inbox');
      check(await o.until(`!!document.querySelector('#view .trow[data-id="${T}"] .ttl')`, {timeout: 20000}), `${tag}: the row is there`);
      const row = `document.querySelector('#view .trow[data-id="${T}"]')`;
      // a computer's row with columns shows one line with an ellipsis (the whole title only while editing); a phone's row wraps
      const wraps = wd < 768;
      const before = await ev(`(() => { const r = ${row}, t = r.querySelector('.ttl'); return {row: r.getBoundingClientRect().height, ttl: t.getBoundingClientRect().height, top: t.getBoundingClientRect().top}; })()`);
      if (wraps) check(before.ttl > 40, `${tag}: the long title wraps ` + JSON.stringify(before));
      await ev(`(() => { inlineEditStart(${T}); return 1; })()`);
      const geo = `(() => { const r = ${row}, i = r.querySelector('.ttlin'), b = i.getBoundingClientRect(), cs = getComputedStyle(i); return {tag: i.tagName, row: r.getBoundingClientRect().height, h: b.height, w: b.width, top: b.top, sh: i.scrollHeight, ch: i.clientHeight, sl: i.scrollLeft, v: i.value, bw: cs.borderTopWidth}; })()`;
      // the height follows the width the row's layout settles on: a real state, no fixed time
      await o.until(`(g => g.sh <= g.ch + 1 && g.h < 400 && g.h > 10)(${geo})`, {timeout: 5000});
      const g = await ev(geo);
      check(g.tag === 'TEXTAREA' && g.v === LONG, `${tag}: a wrapping field with the raw title ` + JSON.stringify(g));
      check(g.sh <= g.ch + 1 && g.sl === 0, `${tag}: the whole text is visible, the start not pushed away ` + JSON.stringify(g));
      check(g.h < 400 && g.w > 120, `${tag}: a field of sensible size (it measured itself at its real width) ` + JSON.stringify(g));
      if (wraps) {
        check(Math.abs(g.row - before.row) <= 2, `${tag}: the row keeps its height ` + JSON.stringify([before, g]));
        check(Math.abs(g.h - before.ttl) <= 2 && Math.abs(g.top - before.top) <= 2, `${tag}: the field lies where the title stood, as many lines ` + JSON.stringify([before, g]));
      } else check(g.h > before.ttl + 10, `${tag}: the one-line row opens to the whole title ` + JSON.stringify([before, g]));
      check(g.bw === '0px', `${tag}: no frame over the text ` + JSON.stringify(g));
      await o.shot(`p2497c-${tag}-edit.png`);
      // it grows with the text
      const grown = await ev(`(() => { const i = ${row}.querySelector('.ttlin'), h = i.getBoundingClientRect().height; i.value += ' and more words'.repeat(40); i.dispatchEvent(new Event('input', {bubbles: true})); return {was: h, now: i.getBoundingClientRect().height, sh: i.scrollHeight, ch: i.clientHeight}; })()`);
      check(grown.now > grown.was && grown.sh <= grown.ch + 1, `${tag}: the field grows with the text ` + JSON.stringify(grown));
      // pasted line breaks become spaces, Esc cancels
      const pasted = await ev(`(() => { const i = ${row}.querySelector('.ttlin'); i.value = 'One\\nTwo\\r\\nThree'; i.dispatchEvent(new Event('input', {bubbles: true})); return i.value; })()`);
      check(pasted === 'One Two Three', `${tag}: pasted line breaks become spaces: ` + JSON.stringify(pasted));
      await ev(`(() => { ${row}.querySelector('.ttlin').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); return 1; })()`);
      check(await o.until(`!document.querySelector('.ttlin')`, {timeout: 5000}) && (await call('GET', `/api/tasks/${T}`)).title === LONG, `${tag}: Esc cancels`);
      // Enter saves, no line break in the title
      await ev(`(() => { inlineEditStart(${T2}); return 1; })()`);
      await ev(`(() => { const i = document.querySelector('#view .ttlin'); i.value = 'Renamed ${tag}'; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
      let tt = ''; for (let n = 0; n < 60 && tt !== 'Renamed ' + tag; n++) { tt = (await call('GET', `/api/tasks/${T2}`)).title; if (tt !== 'Renamed ' + tag) await sleep(150); }
      check(tt === 'Renamed ' + tag && await ev(`!document.querySelector('.ttlin')`), `${tag}: Enter saves without a line break: ` + JSON.stringify(tt));
      // leaving the field saves
      await ev(`(() => { inlineEditStart(${T2}); return 1; })()`);
      await ev(`(() => { const i = document.querySelector('#view .ttlin'); i.value = 'Blurred ${tag}'; i.dispatchEvent(new Event('input', {bubbles: true})); i.blur(); i.dispatchEvent(new FocusEvent('blur')); return 1; })()`);  // (a headless window without focus fires no blur of its own)
      tt = ''; for (let n = 0; n < 60 && tt !== 'Blurred ' + tag; n++) { tt = (await call('GET', `/api/tasks/${T2}`)).title; if (tt !== 'Blurred ' + tag) await sleep(150); }
      check(tt === 'Blurred ' + tag, `${tag}: a click beside saves: ` + JSON.stringify(tt));
      if (wd === 1200) {
        // a real double click on a word inside the title: the caret lands there, not at the end
        await o.until(`!document.querySelector('.ttlin') && !!${row}`, {timeout: 5000});
        const pt = await ev(`(() => { const t = ${row}.querySelector('.ttl'), n = [...t.childNodes].find(x => x.nodeType === 3) || t.firstChild, rg = document.createRange(); const at = ${JSON.stringify(LONG)}.indexOf('really'); rg.setStart(n, at + 2); rg.setEnd(n, at + 3); const b = rg.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, at}; })()`);
        // the "Renamed" note of the step before may still lie over the row: the title itself under the pointer
        check(await o.until(`!!document.elementFromPoint(${pt.x}, ${pt.y})?.closest('.ttl')`, {timeout: 15000}), `${tag}: the title is free to click`);
        const click = [{type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}];
        await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(pt.x), y: Math.round(pt.y)}, ...click, ...click]}]});
        await cmd('input.releaseActions', {context: ctx});
        check(await o.until(`!!document.querySelector('#view .ttlin')`, {timeout: 5000}), `${tag}: a double click opens the field`);
        const c = await ev(`(() => { const i = document.querySelector('#view .ttlin'); return {s: i.selectionStart, e: i.selectionEnd, f: document.activeElement === i}; })()`);
        check(c.f && c.s === c.e && Math.abs(c.s - pt.at) <= 8, `${tag}: the caret stands at the double-click ` + JSON.stringify([pt, c]));
        await ev(`(() => { inlineEditCancel(); return 1; })()`);
      }
    }, false);
  }
  console.log(`p2497_c_ttledit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
