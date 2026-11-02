// kalmido-suite: fresh nodata
// 2.450.0 B (#3770): numbers, sizes and sort order follow the app language, no browser and no server: the helpers of the
// client (taken from the source files as they are) run in node per language:
// - fmtSize / fmtBytes: "1.5 MB" in English, "1,5 MB" in German (was the other way round), "1,5 Go" / "Mo" / "Ko" in French
// - fmtNum with fixed decimals (the placeholders), numField (the text of an input, read back by parseNum)
// - moneyParse: amounts from 1000 on with separators (was NaN), a wrong order is no amount, never another one; qtyParse:
//   the "1.500" the German field shows for 1500 stays 1500 (was 1.5)
// - cmpText: Spanish ñ after n (German: with n), no fixed language
// - sgDay: the Dutch 15-10-2026; month first in en-US
// - the client has no fixed language left: no localeCompare(…, 'de'), no .replace('.', ','), no placeholder "0,00"
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
  const one = s.indexOf('\n', i + 1), end = /\{\s*(\/\/.*)?$/.test(s.slice(i + 1, one)) ? s.indexOf('\n}', i + 1) + 2 : one;
  return s.slice(i + 1, end);
}
const code = [
  piece('js/core.js', 'const numDec ='), piece('js/core.js', 'function parseNum'), piece('js/core.js', 'const numField ='),
  piece('js/core.js', 'const cmpColl ='), piece('js/core.js', 'const cmpText ='), piece('js/quickadd.js', 'const fmtNum ='),
  piece('js/attachments.js', 'const fmtSize ='), piece('js/account.js', 'const fmtBytes ='),
  piece('js/family.js', 'const SHOP_FRAC ='), piece('js/family.js', 'function qtyParse'), piece('js/family.js', 'const moneyParse ='),
  piece('js/budget.js', 'const bg_numStr ='), piece('js/sheetgrid.js', 'function sgDay'),
].join('\n');
const run = (loc, expr, ctx = {}) => vm.runInNewContext(`${code}\n${expr}`, {LOCALE: () => loc, pad: n => String(n).padStart(2, '0'), mdFirst: () => false, ...ctx});
const eq = (loc, expr, want, ctx) => { const got = run(loc, expr, ctx); check(Object.is(got, want), `${loc}: ${expr} = ${JSON.stringify(want)} (${JSON.stringify(got)})`); };

// ---- sizes in every language
const MB = '1572864', GB = '1610612736';
for (const [loc, mb, gb] of [['en-GB', '1.5 MB', '1.5 GB'], ['de-DE', '1,5 MB', '1,5 GB'], ['fr-FR', '1,5 Mo', '1,5 Go'], ['es-ES', '1,5 MB', '1,5 GB'], ['it-IT', '1,5 MB', '1,5 GB'], ['nl-NL', '1,5 MB', '1,5 GB']]) {
  eq(loc, `fmtSize(${MB})`, mb); eq(loc, `fmtSize(${GB})`, gb); eq(loc, `fmtBytes(${GB})`, gb);
}
eq('en-GB', 'fmtSize(512) + " " + fmtSize(2048)', '512 B 2 KB');
eq('fr-FR', 'fmtSize(512) + " " + fmtSize(2048)', '512 o 2 Ko');
eq('de-DE', 'fmtSize(1073741824)', '1 GB');
eq('de-DE', 'fmtBytes(0)', '1 KB');

// ---- placeholders and input texts
eq('en-GB', 'fmtNum(0, 2, 2)', '0.00');
eq('de-DE', 'fmtNum(0, 2, 2)', '0,00');
eq('fr-FR', 'fmtNum(7.5, 2)', '7,5');
eq('en-GB', 'fmtNum(7.5, 2)', '7.5');
eq('de-DE', 'fmtNum(1234.5)', '1.234,5');  // no change without fixed decimals
for (const [loc, want] of [['en-GB', '1234.5'], ['de-DE', '1234,5'], ['nl-NL', '1234,5'], ['fr-FR', '1234,5']]) {
  eq(loc, 'numField(1234.5)', want); eq(loc, 'bg_numStr(1234.5)', want); eq(loc, 'parseNum(numField(1234.5))', 1234.5);
}
eq('de-DE', 'numField(null) + numField("")', '');
eq('de-DE', 'numField("x")', 'x');  // text that is no number stays as it is
eq('de-DE', 'numField("12.5", 2, 2)', '12,50');

// ---- amounts are never read silently wrong
for (const [loc, cases] of [
  ['de-DE', [['1.234,56', 1234.56], ['1234,5', 1234.5], ['1234.5', 1234.5], ['1.000', 1000], ['12,50 €', 12.5], ['1 234,56', 1234.56], ['', null], ['1,234.56', NaN], ['1,234', NaN], ['-5', NaN], ['abc', NaN], ['12345678', NaN]]],
  ['en-GB', [['1,234.56', 1234.56], ['1234,5', 1234.5], ['1234.5', 1234.5], ['1,000', 1000], ['€12.50', 12.5], ['1.234,56', NaN], ['1.234', NaN]]],
  ['fr-FR', [['1 234,56', 1234.56], ['1 234,56', 1234.56], ['1234,5', 1234.5]]],
  ['nl-NL', [['1.234,56', 1234.56]]],
]) for (const [s, want] of cases) eq(loc, `moneyParse(${JSON.stringify(s)})`, want);
eq('de-DE', 'qtyParse(fmtNum(1500, 3))', 1500);
eq('de-DE', 'qtyParse("1,5") + qtyParse("1½") + qtyParse("1/2")', 3.5);
eq('en-GB', 'qtyParse(fmtNum(1500, 3))', 1500);
eq('de-DE', 'qtyParse("x")', null);

// ---- the sort order of the language
const names = '["o", "ñu", "nz", "na"].sort(cmpText).join(" ")';
eq('es-ES', names, 'na nz ñu o');
eq('de-DE', names, 'na ñu nz o');
eq('sv-SE', '["ä", "z", "a"].sort(cmpText).join(" ")', 'a z ä');
eq('de-DE', '["ä", "z", "a"].sort(cmpText).join(" ")', 'a ä z');
eq('en-GB', '[null, "a"].sort(cmpText).join("|")', '|a');
check(run('es-ES', names) !== run('de-DE', names), 'two languages in one page context keep their own order');

// ---- dates of the table
eq('nl-NL', 'sgDay("15-10-2026")', '2026-10-15');
eq('nl-NL', 'sgDay("31-02-2026")', null);
eq('de-DE', 'sgDay("15.10.2026") + sgDay("15/10/2026")', '2026-10-152026-10-15');
eq('en-US', 'sgDay("10-15-2026") + sgDay("10/15/2026")', '2026-10-152026-10-15', {mdFirst: () => true});
eq('en-GB', 'sgDay("2026-10-15")', '2026-10-15');

// ---- nothing fixed is left in the client
const dir = path.join(SRC, 'static', 'js');
for (const f of fs.readdirSync(dir).filter(x => x.endsWith('.js'))) {
  const s = fs.readFileSync(path.join(dir, f), 'utf8');
  check(!/localeCompare\([^;\n]*?,\s*'de'/.test(s), `${f}: a fixed German order`);
  check(!/\.replace\('\.', ','\)/.test(s), `${f}: a fixed decimal comma`);
  check(!/placeholder="0,00/.test(s), `${f}: a fixed placeholder`);
  check(!/startsWith\('(de|en)'\) \? ('[.,]')/.test(s), `${f}: a decimal sign by language name`);
}

console.log(`p2450_x_num: ${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
