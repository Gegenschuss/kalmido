// 2.750.0 (#5307): a module asked for by a start script is inserted only after DOMContentLoaded (all start scripts ran)
// kalmido-suite: nodata
// No server: the loader part of static/js/lazyload.js (LD_RAN .. ld_script) runs in a jsdom page whose later start script
// (here a stand-in for keys.js) must have run before any module's script tag is there. Without the fix the tag came at once and
// the module could run before keys.js ("kb_on is not defined", then broken until a reload).
const fs = require('fs');
const path = require('path');
const {JSDOM, ResourceLoader} = require('jsdom');
// data: URLs load (the start scripts), a module's own file does not (no server): its tag stays, without load or error
class DataOnly extends ResourceLoader { fetch(url, o) { return url.startsWith('data:') ? super.fetch(url, o) : null; } }
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };

(async () => {
  const js = fs.readFileSync(path.join(SRC, 'static', 'js', 'lazyload.js'), 'utf8');
  const a = js.indexOf('const LD_RAN = new Set();'), b = js.indexOf('\nfunction loadModule(');
  check(a > 0 && b > a, 'the loader part of lazyload.js is found');
  const part = js.slice(a, b);
  const core = fs.readFileSync(path.join(SRC, 'static', 'js', 'core.js'), 'utf8');
  const c1 = core.indexOf('let domLoaded'), c2 = core.indexOf('\n}\n', c1);
  check(c1 > 0 && c2 > c1, 'domLoaded / domReady of core.js are found');
  // the real page: classic defer scripts (index.html) - they run with readyState 'interactive', before DOMContentLoaded
  const data = t => 'data:text/javascript,' + encodeURIComponent(t);
  const s1 = `${core.slice(c1, c2 + 3)}\nconst ld_url = f => '/static/js/' + f + '.js';\n${part}\nwindow.LDP = ld_script;`;
  const s2 = `window.__state = document.readyState; window.__pending = LDP('mod1'); window.__early = document.querySelectorAll('script[data-ld]').length;`;
  const s3 = `window.__keys = !document.querySelector('script[data-ld]');`;  // the stand-in for keys.js, the last start script
  const html = `<!doctype html><html><head><script src="${data(s1)}" defer></script><script src="${data(s2)}" defer></script>` +
    `<script src="${data(s3)}" defer></script></head><body><p>text</p></body></html>`;
  const dom = new JSDOM(html, {runScripts: 'dangerously', resources: new DataOnly(), url: 'http://example.test/'});
  const w = dom.window;
  for (let i = 0; i < 200 && (w.__keys === undefined || w.document.readyState === 'loading'); i++) await new Promise(r => setTimeout(r, 25));
  check(w.__state === 'interactive', `the defer script ran with readyState interactive (${w.__state})`);
  check(w.__early === 0, `#5307: no module tag while the page is parsed (${w.__early})`);
  check(w.__keys === true, '#5307: the later start script ran before any module tag');
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
