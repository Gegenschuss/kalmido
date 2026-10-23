// 2.217.0 A (#2794, #2795, #2796): phone-width fixes are CSS rules; static check of the shipped rules (no app start).
const fs = require('fs'), path = require('path');
const rd = f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');
const app = rd('static/app.css'), off = rd('static/css/office.css');
let ok = 0; const F = [];
const check = (c, w) => { if (c) ok++; else { F.push(w); console.log('FAIL:', w); } };
check(/\.cthn h3\{[^}]*overflow-wrap:break-word[^}]*line-clamp:2/.test(app) && !/\.cthn h3\{[^}]*anywhere/.test(app), '#2794: name max two lines, no letter tower');
check(/@media \(max-width:37\.5rem\)\{ \.cthead\{flex-wrap:wrap\} \.cthead \.ctacts\{flex:1 0 100%;justify-content:flex-end\} \}/.test(app), '#2794: actions drop to a second row on phones');
check(/@media \(max-width:599px\) \{\s*\.ofdgrid\{grid-template-columns:minmax\(0,1fr\)\}/.test(off) && /\.ofdgrid \.row select[^{]*\{min-width:0;max-width:100%\}/.test(off), '#2795: editor fields never wider than the screen');
check(/\.pitem \.pl\{display:contents\}/.test(app) && /\.pitem \.pk\{grid-column:3;grid-row:2/.test(app) && /\.pitem \.plt\{grid-column:2\/-1;grid-row:1;white-space:normal/.test(app), '#2796: title first, project + kind below on phones');
check(/\.pitem \.plt\{white-space:nowrap;overflow:hidden;text-overflow:ellipsis/.test(app), '#2796: desktop row unchanged');
console.log(F.length ? `FAILED ${F.length}` : `p2217_a_handy_css: ${ok} checks passed`); process.exit(F.length ? 1 : 0);
