// kalmido-suite: after=p2602_b_tokens_ui nodata
// 2.993.0 (#5495): office.css rest. No browser, no server: the files are read as they are.
// - one status chip set (.dtp-st-*) for document templates and letters, no .lt-st-* left
// - the flat row buttons share ONE base rule (no fill, no frame, 44 px hit area, left text), no copy of it in the single rules
// - the width/focus bound sr-only places stay (media query / :focus-within), they are not turned into .sr
const fs = require('fs');
const path = require('path');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const rd = f => fs.readFileSync(path.join(SRC, f), 'utf8');
const css = rd('static/css/office.css').replace(/\/\*[\s\S]*?\*\//g, '');
const body = sel => { const m = css.match(new RegExp('(?:^|[}\\n])' + sel.replace(/[.\[\]()]/g, '\\$&') + '\\s*\\{([^}]*)\\}')); return m ? m[1] : ''; };

check(!/\.lt-st-/.test(css) && !/lt-st-/.test(rd('static/js/office_letters.js')), 'no .lt-st-* in css and markup');
check(/dtp-st dtp-st-\$\{esc\(d\.status\)\}/.test(rd('static/js/office_letters.js')), 'letters use the shared chip classes');
const sent = css.match(/\.dtp-st-final,\.dtp-st-sent\{([^}]*)\}/), dlv = css.match(/\.dtp-st-signed,\.dtp-st-delivered\{([^}]*)\}/);
check(sent && /border-color:var\(--accent\)/.test(sent[1]) && /color:var\(--accent\)/.test(sent[1]), 'sent = final look');
check(dlv && /background:var\(--accent\)/.test(dlv[1]) && /color:var\(--on-accent/.test(dlv[1]), 'delivered = signed look');

const base = css.match(/\.ccopen,\.dma-open,\.ltm-pick,\.lt-sugb\{([^}]*)\}/);
check(base && /background:none/.test(base[1]) && /border:0/.test(base[1]) && /min-height:2\.75rem/.test(base[1]) && /text-align:left/.test(base[1]), 'shared base of the flat row buttons');
for (const c of ['.ccopen', '.dma-open', '.ltm-pick', '.lt-sugb']) {
  const b = body(c);
  check(b && !/background:none|border:0|min-height:2\.75rem|text-align:left/.test(b), `${c}: no copy of the base declarations`);
}
check(/@media \(max-width:767px\)\{\s*li>\.ofdrmore/.test(css), 'sr-only of the row buttons stays bound to the phone width');
check(/\.ofcbb:not\(:focus-within\)/.test(css), 'sr-only building blocks stay bound to the focus');
console.log(`${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
