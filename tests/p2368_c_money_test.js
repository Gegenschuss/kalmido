// kalmido-suite: after=p2368_c_api nodata
// 2.368.0 C (#2983): one money format in the web client, no browser and no server: the helper curMoney of static/i18n.js and
// the money lines of the modules (taken from the source files as they are) run in node with an English and a German locale:
// - curMoney: "€1,234.50" / "1.234,50 €", USD "$1,234.50" (not "US$"), a typed sign ("€", "$") as its code, other text
//   behind the number, empty = the bare number, nothing for no amount; no break inside the number, plain spaces
// - time tracking (time.js money): "€1,234.50", was "1,234.50 EUR"; the office (ofcMoney: home currency), the per diem
//   (rk_vmaEur, rk_vmaN "€28"), documents (dc_money), custom currency fields (cfk_money), the time-tracking amount of the
//   settings (fmtMoney) and a quotation's money in the DOCUMENT's language and currency (ofdMoney)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const read = f => fs.readFileSync(path.join(SRC, 'static', f), 'utf8');
// one top-level declaration of a source file: from `start` to the end of its line (one-liners) or its closing "}" line
function piece(f, start) {
  const s = read(f), i = s.indexOf('\n' + start);
  if (i < 0) throw new Error(`${f}: ${start} not found`);
  const one = s.indexOf('\n', i + 1), end = /\{\s*$/.test(s.slice(i + 1, one)) ? s.indexOf('\n}', i + 1) + 2 : one;
  return s.slice(i + 1, end);
}
const code = [
  piece('i18n.js', 'const CUR_SIGNS'), piece('i18n.js', 'function curMoney'),
  piece('js/time.js', 'const money ='), piece('js/office.js', 'const ofcHome ='), piece('js/office.js', 'const ofcMoney ='),
  piece('js/office_travel.js', 'const rk_vmaEur ='), piece('js/office_travel.js', 'const rk_vmaN ='),
  piece('js/docs.js', 'const dc_money ='), piece('js/render.js', 'function cfk_money'), piece('js/lazyload.js', 'const fmtMoney ='),
  piece('js/office_docs.js', 'const OFD_LOCS'), piece('js/office_docs.js', 'function ofdMoney'),
].join('\n');
const run = (loc, expr, ctx = {}) => vm.runInNewContext(`${code}\n${expr}`, {LOCALE: () => loc, numFmt: String, OFC: {info: {settings: {}}}, OFD: {doc: null}, S: {settings: {}}, ...ctx});
const eq = (loc, expr, want, ctx) => { const got = run(loc, expr, ctx); check(got === want, `${loc}: ${expr} = ${JSON.stringify(want)} (${JSON.stringify(got)})`); };

// ---- the helper
eq('en-GB', 'curMoney(1234.5, "EUR")', '€1,234.50');
eq('de-DE', 'curMoney(1234.5, "EUR")', '1.234,50 €');
eq('en-GB', 'curMoney(1234.5, "USD")', '$1,234.50');
eq('de-DE', 'curMoney(-5, "$")', '-5,00 $');
eq('en-GB', 'curMoney(1234.5, "€")', '€1,234.50');
eq('en-GB', 'curMoney(12, "gbp")', '£12.00');
eq('de-DE', 'curMoney(1234.5, "Fr.")', '1.234,50 Fr.');
eq('de-DE', 'curMoney(1234.5, "")', '1.234,50');
eq('de-DE', 'curMoney(null, "EUR") + curMoney("", "EUR") + curMoney("x", "EUR")', '');
eq('fr-FR', 'curMoney(1234.5, "EUR")', '1 234,50 €');  // no break inside the number, a plain space before the sign
eq('nl-NL', 'curMoney(1234.5, "EUR")', '€ 1.234,50');

// ---- the modules: English places the sign in front, German behind (as before)
eq('en-GB', 'money(1234.5, "EUR")', '€1,234.50');
eq('de-DE', 'money(1234.5, "EUR")', '1.234,50 €');
eq('en-GB', 'money(80, "")', '80.00');
eq('en-GB', 'ofcMoney(1234.5)', '€1,234.50');
eq('en-GB', 'ofcMoney(1234.5)', '$1,234.50', {OFC: {info: {settings: {home_currency: 'USD'}}}});
eq('de-DE', 'ofcMoney(1234.5)', '1.234,50 €');
eq('en-GB', 'ofcMoney(null) + ofcMoney("")', '');
eq('en-GB', 'rk_vmaEur(56) + " " + rk_vmaN(28) + " " + rk_vmaN(5.6)', '€56.00 €28 €5.60');
eq('de-DE', 'rk_vmaEur(56) + " " + rk_vmaN(28)', '56,00 € 28 €');
eq('en-GB', 'dc_money(1234.5, "GBP") + " " + dc_money("", "EUR")', '£1,234.50 ');
eq('en-GB', 'cfk_money("1234.5", "USD") + " " + cfk_money("x", "USD")', '$1,234.50 x');
eq('en-GB', 'fmtMoney(1234.5)', '€1,234.50', {S: {settings: {time_currency: '€'}}});
eq('en-GB', 'fmtMoney(1234.5)', '1,234.50 CHF.', {S: {settings: {time_currency: 'CHF.'}}});
// a quotation: the document's language and currency, not the person's (like calc.fmt_money on its PDF)
eq('de-DE', 'ofdMoney(1234.5, {lang: "en", currency: "USD"})', '$1,234.50');
eq('en-GB', 'ofdMoney(1234.5, {lang: "de", currency: "EUR"})', '1.234,50 €');
eq('en-GB', 'ofdMoney(1234.5, {lang: "fr", currency: "EUR"})', '1 234,50 €');
eq('en-GB', 'ofdMoney(1234.5, {lang: "", currency: ""})', '1.234,50 €');

console.log(`p2368_c_money: ${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
