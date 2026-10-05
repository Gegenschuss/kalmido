// markdown renderer (static/js/attachments.js mdInline) against the audit payloads: no attribute breakout, only safe hrefs
const fs = require('fs');
const {JSDOM} = require('jsdom');
// 2.20.0 (#646): the client modules in the order of index.html (APPJS: one file instead)
const ST = require('path').join(__dirname, '..', 'static');
const src = process.env.APPJS ? fs.readFileSync(process.env.APPJS, 'utf8')
  : [...fs.readFileSync(require('path').join(ST, 'index.html'), 'utf8').matchAll(/<script src="\/static\/js\/([\w-]+\.js)"/g)]
    .map(m => fs.readFileSync(require('path').join(ST, 'js', m[1]), 'utf8')).join('\n');
const pick = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error('marker ' + a); return src.slice(i, j); };
const code = pick('const esc = s =>', '\n', 0) + '\n' + pick('const MD_URL', 'function renderMd(');
const mdInline = new Function(code + '\nreturn mdInline;')();
let ok = 0, fail = 0;
const check = (c, what) => { if (c) ok++; else { fail++; console.log('FAIL:', what); } };
const dom = new JSDOM('<!doctype html><body></body>');
const D = dom.window.document;
function parse(h) { const d = D.createElement('div'); d.innerHTML = h; return d; }
const payloads = [
  '[a](https://x.com/(https://e/x/style=position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:9999;background:red/)',
  '[click](https://x.com/(https://evil.example/)',
  '[label](https://a/(https://b"onmouseover="alert(1)")',
  '[x](https://a/"onmouseover=alert(1)//)',
  "[x](https://a/'onmouseover=alert(1)//)",
  '[x](javascript:alert(1))',
  '[x](JaVaScRiPt:alert(1))',
  '[x](data:text/html,<script>alert(1)</script>)',
  'https://a/**b**/"x',
  'see `https://a/"<img src=x onerror=alert(1)>` there',
  '[**b**](https://a/~~s~~)',
  '<img src=x onerror=alert(1)> https://a.b/c?d=1&e=2',
  '[a](https://ok.example/p?q=1&r=2) and https://x.y/z.',
  '[mail](mailto:a@b.c)',
  '[[x](https://a/)](https://b/)',
  '*i* **b** ~~s~~ `c`',
];
for (const p of payloads) {
  const h = mdInline(p), d = parse(h);
  const bad = [...d.querySelectorAll('*')].filter(e => !['A', 'B', 'I', 'S', 'CODE'].includes(e.tagName));
  check(!bad.length, 'only whitelisted tags: ' + p + ' -> ' + h);
  for (const e of d.querySelectorAll('*')) {
    const attrs = [...e.attributes].map(a => a.name);
    const allowed = e.tagName === 'A' ? ['href', 'target', 'rel'] : [];
    check(attrs.every(a => allowed.includes(a)), 'no extra attributes: ' + p + ' -> ' + h);
    if (e.tagName === 'A') check(/^(https?:\/\/|mailto:)[^\s"'<>()]+$/i.test(e.getAttribute('href')), 'safe href: ' + e.getAttribute('href'));
  }
  check(!d.querySelector('a a'), 'no nested links: ' + p);
}
// behaviour kept
const t1 = parse(mdInline('[a](https://ok.example/p?q=1&r=2) and https://x.y/z.'));
check(t1.querySelectorAll('a').length === 2 && t1.querySelector('a').getAttribute('href') === 'https://ok.example/p?q=1&r=2', 'link + bare link');
check(t1.querySelectorAll('a')[1].getAttribute('href') === 'https://x.y/z' && t1.textContent.endsWith('.'), 'trailing dot not in the link');
const t2 = parse(mdInline('*i* **b** ~~s~~ `c`'));
check(t2.querySelector('i') && t2.querySelector('b') && t2.querySelector('s') && t2.querySelector('code'), 'inline formatting');
const t3 = parse(mdInline('[x](javascript:alert(1))'));
check(!t3.querySelector('a') && t3.textContent.includes('javascript:alert(1)'), 'javascript: stays text');
const t4 = parse(mdInline('see `https://a/"<img>` there'));
check(!t4.querySelector('a') && t4.querySelector('code').textContent === 'https://a/"<img>', 'no link inside code');
const t5 = parse(mdInline('(https://a.example/x) end'));
check(t5.querySelector('a')?.getAttribute('href') === 'https://a.example/x', 'bare link in parentheses');
const t6 = parse(mdInline('[mail](mailto:a@b.c)'));
check(t6.querySelector('a')?.getAttribute('href') === 'mailto:a@b.c', 'mailto link');
check(mdInline('a <@5> b').includes('&lt;@5&gt;'), 'mention token stays escaped for commentBody');
// colors reach style attributes only as plain hex values (MEDIUM-4)
const cssColor = new Function(pick('const cssColor =', '\n') + '\nreturn cssColor;')();
for (const bad of ['red;background:url(https://e/x)', '"><img src=x onerror=alert(1)>', '#12345', 'var(--x)', 'expression(alert(1))', null, 7])
  check(cssColor(bad) === '', 'cssColor rejects ' + bad);
for (const good of ['#abc', '#a1b2c3', '#A1B2C3D4']) check(cssColor(good) === good, 'cssColor keeps ' + good);
check(!/style="[^"]*\$\{(?![^}]*cssColor)[^}]*\.color\b/.test(src), 'every .color in a style attribute goes through cssColor');
console.log(`${ok} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
