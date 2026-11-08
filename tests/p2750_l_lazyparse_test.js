// 2.750.0 (#5307): a module asked for while the page is still parsed is inserted only after DOMContentLoaded
// kalmido-suite: nodata
// No server: the loader part of static/js/lazyload.js (LD_RAN .. ld_script) runs in a jsdom page whose later start script
// (here a stand-in for keys.js) must have run before any module's script tag is there. Without the fix the tag came at once and
// the module could run before keys.js ("kb_on is not defined", then broken until a reload).
const fs = require('fs');
const path = require('path');
const {JSDOM} = require('jsdom');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };

(async () => {
  const js = fs.readFileSync(path.join(SRC, 'static', 'js', 'lazyload.js'), 'utf8');
  const a = js.indexOf('const LD_RAN = new Set();'), b = js.indexOf('\nfunction loadModule(');
  check(a > 0 && b > a, 'the loader part of lazyload.js is found');
  const part = js.slice(a, b);
  const html = `<!doctype html><html><head><script>
const ld_url = f => '/static/js/' + f + '.js';
${part}
window.LDP = ld_script;
window.__early = null;
</script><script>
window.__pending = window.LDP('mod1');
window.__early = document.querySelectorAll('script[data-ld]').length;
</script></head><body><p>text</p><script>window.__keys = !document.querySelector('script[data-ld]');</script></body></html>`;
  const dom = new JSDOM(html, {runScripts: 'dangerously', url: 'http://example.test/'});
  const w = dom.window;
  check(w.__early === 0, `#5307: no module tag while the page is parsed (${w.__early})`);
  check(w.__keys === true, '#5307: the later start script ran before any module tag');
  await new Promise(r => w.document.readyState === 'loading' ? w.document.addEventListener('DOMContentLoaded', r) : r());
  await new Promise(r => setTimeout(r, 20));
  const tags = [...w.document.querySelectorAll('script[data-ld]')];
  check(tags.length === 1 && tags[0].getAttribute('src') === '/static/js/mod1.js', `after DOMContentLoaded the module's tag is there (${tags.length})`);
  check(w.eval("LDP('mod1')") === w.__pending, 'a second ask while it loads gets the same promise (no second tag)');
  // a page already parsed: the tag comes at once (no wait)
  w.eval("LDP('mod2')");
  await new Promise(r => setTimeout(r, 0));
  check(!!w.document.querySelector('script[data-ld="mod2"]'), 'after the parse a module is inserted without waiting for an event');
  w.close();
  console.log(F.length ? `FAILED ${F.length} of ${ok + F.length}` : `OK ${ok}`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
