// kalmido-suite: fresh
// 2.476.0 part B (#3487): the start style files (static/css/start-*.css) arrive with app.css at start - one URL, no own
// <link>, behind the rules of app.css in the same stylesheet, also for a person without an organisation.
// freelancer-matrix: public (the start styles are static files; the app page of a person without an organisation loads them)
const fs = require('fs');
const path = require('path');
const {boot, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await new Promise(r => setTimeout(r, 150)); } return fn(); };
const st = path.join(__dirname, '..', 'static');
const starts = fs.readdirSync(path.join(st, 'css')).filter(f => /^start-.*\.css$/.test(f)).sort();

// the :root rule of the start style files, found in the page's own stylesheets
const startRule = d => {
  for (const sh of d.styleSheets) {
    let rules; try { rules = [...sh.cssRules]; } catch (e) { continue; }
    const i = rules.findIndex(r => r.selectorText === ':root' && /--kd-start-css/.test(r.cssText));
    if (i >= 0) return {sheet: sh, index: i, count: rules.length};
  }
  return null;
};

(async () => {
  check(starts.includes('start-base.css'), 'static/css/start-base.css is there ' + starts);
  const css = await (await fetch(B + 'static/app.css')).text();
  check(/--kd-start-css\s*:\s*1/.test(css), 'GET /static/app.css carries the rule of start-base.css');
  check(css.indexOf('--kd-start-css') > css.length / 2, 'the start styles come behind the rules of app.css');
  check((await fetch(B + 'static/css/start-base.css')).ok, 'the file itself stays reachable');

  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  for (const user of ['alice']) {
    const w = await boot({user}), d = w.document;
    const hit = await until(() => startRule(d));
    check(hit, `${user}: the start rule is in the page's stylesheets at start`);
    const appLink = d.querySelector('link[rel="stylesheet"][href*="/static/app.css"]');
    check(hit && appLink && appLink.sheet === hit.sheet, `${user}: it arrives inside app.css (the sheet of its <link>)`);
    check(hit && hit.index > hit.count / 2, `${user}: behind the rules of app.css (${hit && hit.index} of ${hit && hit.count})`);
    check(![...d.querySelectorAll('link[rel="stylesheet"]')].some(l => /start-/.test(l.href)), `${user}: no own <link> for a start style file`);
    w.close();
  }
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
