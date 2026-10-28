// 2.382.0 (#3153): formulas (KaTeX) and Mermaid diagrams on knowledge pages (Firefox, the app loads its modules itself),
// computer 1280x800 (alice) and tablet 820x1180 (frida, a person WITHOUT an organisation: freelancer-matrix: knowledge):
// - a page without such blocks loads neither library nor diagram.js (resource timing); "$5" stays text
// - a page with "$$" lines, ```math, an inline \( \), a ```mermaid block draws KaTeX / an SVG; a broken diagram keeps its
//   source as a code block with a hint; the SVG has nothing that runs
// - the live preview draws them too; "/formula" writes a ```math block (2.382.0 #3128 bar button "Source" / "Preview" in p2350_b)
// - a public link of the page (server wiki/wkshare.py wsh_md) marks the blocks with their language (data-lang)
// Invented texts only. Screenshots: P2382_SHOTS.
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2382_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2382_wiki_diagram_ui', check, shots: 'P2382_SHOTS', lazy: true});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const PLAIN = '# Plain\n\nCosts $5 and $10 today.\n\n```js\nconst a = "$$"\n```';
const DIAG = '# Sums\n\n$$\n\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\n$$\n\nInline \\(a^2 + b^2\\) here, it costs $5.\n\n'
  + '```mermaid\nflowchart LR\n  A[Start] --> B[End]\n```\n\n```mermaid\nthis is not a diagram ((\n```\n\n```math\nx^2\n```\n\n`\\(code\\)` stays';
const K = {Enter: '\uE007', Escape: '\uE00C'};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const runs = [];
  for (const [who, ck] of [['alice', CA], ['frida', CF]]) {
    const plain = (await call(ck, 'POST', '/api/wiki/pages', {space: 'private', path: 'Plain', body: PLAIN})).id;
    const diag = (await call(ck, 'POST', '/api/wiki/pages', {space: 'private', path: 'Sums', body: DIAG})).id;
    check(plain && diag, `setup: ${who}'s private pages`); runs.push({who, ck, plain, diag});
  }
  // the public link: the server's page marks the blocks by their language (no script there: they stay as code)
  for (const run of runs) {
    const sh = await call(run.ck, 'POST', '/api/wiki/shares', {page_id: run.diag, kind: 'link'});
    check(sh.url, `${run.who}: a public link of the page (${JSON.stringify(sh).slice(0, 200)})`);
    if (!sh.url) continue;
    const html = await (await fetch(B + String(sh.url).replace(/^https?:\/\/[^/]+\//, '').replace(/^\//, ''))).text();
    check((html.match(/<pre data-lang="math">/g) || []).length === 2 && (html.match(/<pre data-lang="mermaid">/g) || []).length === 2,
      `${run.who}: the public page marks 2 formula blocks ("$$" lines and \`\`\`math) and 2 diagrams (${(html.match(/<pre[^>]*>/g) || []).join(' ')})`);
    check(html.includes('\\sum_{i=1}^{n}') && !/<script/i.test(html), `${run.who}: the formula's source is there, no script`);
  }

  for (const [[vw, vh], run] of [[[1280, 800], runs[0]], [[820, 1180], runs[1]]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const tag = `${vw} ${run.who}`;
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { const x = await ev(expr).catch(() => null); if (x) return x; await sleep(250); } return ev(expr).catch(() => null); };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const type = s => act([{type: 'key', id: 'k', actions: [...s].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const press = key => act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: K[key] || key}, {type: 'keyUp', value: K[key] || key}]}]);
    const loaded = `performance.getEntriesByType('resource').map(r => r.name).filter(n => /vendor\\/(katex|mermaid)|\\/diagram\\.js/.test(n)).map(n => n.replace(/^.*\\/static\\//, '').replace(/\\?.*$/, ''))`;
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${run.who}', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${tag}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    // a page without formulas / diagrams: nothing of them is loaded
    await nav(B + `#wiki/${run.plain}`);
    const p0 = await until(`(() => { const m = document.querySelector('#wk-md'); return m && m.querySelector('h4') ? m.textContent : null; })()`);
    check(p0 && p0.includes('Costs $5 and $10 today.'), `${tag}: the plain page is drawn, the amounts stay text (${JSON.stringify(p0)})`);
    await sleep(1500);  // the idle loader of the app runs meanwhile; nothing may ask for the libraries
    const l0 = await ev(loaded);
    check(Array.isArray(l0) && l0.length === 0 && await ev(`typeof dg_draw === 'undefined'`), `${tag}: no formula / diagram file loaded for a page without them (${JSON.stringify(l0)})`);
    // the page with them
    await ev(`(() => { location.hash = '#wiki/${run.diag}'; return 1; })()`);
    const d1 = await until(`(() => { const m = document.querySelector('#wk-md'); if (!m || !m.querySelector('.wkdgmm svg') || m.querySelectorAll('.wkdgmath .katex').length < 2 || !m.querySelector('.wkimath .katex') || !m.querySelector('.wkdgerr')) return null;
      const svg = m.querySelector('.wkdgmm svg');
      return {math: m.querySelectorAll('.wkdgmath .katex').length, inl: m.querySelectorAll('.wkimath .katex').length, svgs: m.querySelectorAll('.wkdgmm svg').length,
        label: svg.textContent.includes('Start') && svg.textContent.includes('End'), runs: !!svg.querySelector('script') || [svg, ...svg.querySelectorAll('*')].some(x => [...x.attributes].some(a => /^on/i.test(a.name))),
        err: m.querySelector('.wkdgerr').textContent, broken: [...m.querySelectorAll('pre[data-lang="mermaid"]')].map(p => p.textContent),
        text: m.textContent.includes('it costs $5.'), code: [...m.querySelectorAll('code')].find(c => !c.closest('pre'))?.textContent}; })()`, 160);
    check(d1 && d1.math === 2 && d1.inl === 1, `${tag}: "$$" lines and the \`\`\`math block are drawn as formulas, the inline \\( \\) too: ${JSON.stringify(d1)}`);
    check(d1 && d1.svgs === 1 && d1.label && !d1.runs, `${tag}: the Mermaid block is an SVG with its labels, nothing in it runs`);
    check(d1 && /could not be drawn/.test(d1.err) && d1.broken.length === 1 && d1.broken[0].includes('this is not a diagram'), `${tag}: a broken diagram keeps its source with a hint`);
    check(d1 && d1.text && d1.code === '\\(code\\)', `${tag}: a single $ stays text, \\( \\) in a code span stays code (${JSON.stringify(d1 && [d1.text, d1.code])})`);
    const l1 = await ev(loaded);
    check(l1 && ['js/diagram.js', 'vendor/katex/katex.min.js', 'vendor/katex/katex.min.css', 'vendor/mermaid/mermaid.min.js'].every(f => l1.includes(f)), `${tag}: the libraries came from the server itself, only now (${JSON.stringify(l1)})`);
    if (vw > 1000) await shot(`p2382_${vw}_read.png`);
    // the live preview draws them as well; "/formula" writes a math block
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    const e1 = await until(`(() => { const l = document.querySelector('#wk-live'); return l && l.querySelector('.wkdgmm svg') && l.querySelectorAll('.wkdgmath .katex').length === 2 ? 1 : null; })()`, 80);
    check(e1, `${tag}: the live preview shows the formulas and the diagram drawn`);
    const lv = await ev(`(() => { const l = document.querySelector('#wk-live'); l.scrollIntoView({block: 'end'}); const r = l.getBoundingClientRect(); return {x: r.left + 20, y: r.bottom - 8}; })()`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(lv.x), y: Math.round(lv.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    const open = await until(`document.querySelector('#wk-blk')?.value ?? null`);
    check(open === '`\\(code\\)` stays', `${tag}: a click below the last block opens it (${JSON.stringify(open)})`);
    await ev(`(() => { const t = document.querySelector('#wk-blk'); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await press('Enter'); await press('Enter'); await type('/formu');
    const m1 = await until(`(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? a.querySelector('button').textContent.trim() : null; })()`);
    check(m1 === 'Formula', `${tag}: "/formu" offers the command Formula (${m1})`);
    await press('Enter');
    const v1 = await ev(`(() => { const t = document.querySelector('#wk-blk'); return t ? {v: t.value, sel: t.value.slice(t.selectionStart, t.selectionEnd)} : null; })()`);
    check(v1 && v1.v.endsWith('```math\nE = mc^2\n```') && v1.sel === 'E = mc^2', `${tag}: Enter writes a math block with the example selected (${JSON.stringify(v1)})`);
    await press('Escape');
    check(await until(`document.querySelectorAll('#wk-live .wkdgmath .katex').length === 3`, 80), `${tag}: drawn after Esc (three formula blocks)`);
    if (vw > 1000) await shot(`p2382_${vw}_live.png`);
  });
  console.log(`p2382_wiki_diagram_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
