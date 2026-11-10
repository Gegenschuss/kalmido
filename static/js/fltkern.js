// @ts-check
/* Kalmido web client: 2.846.0 (#5520) the filter of the shared core, the part a start needs (docs/dev/kern.md "Filter").
   A filter is rules = {op: 'and' | 'or', conds: [{f, op, v, ...}]}: f = what (a key of the area's catalog), op = the comparison,
   v = the values (a list) or a text / number. "is none of" (nin) and "is not" (isnot) always hold on top, also with OR (#4478);
   the other conditions are combined by op. A condition without values (an empty list, an empty text) is off.
   An area describes its fields once in a catalog (an object):
     has:   {f: (item, x) => true when the item has the one value x}           the value lists (op in / nin / is / isnot / empty)
     empty: {f: x}                                                              the value op "empty" stands for (only these f)
     text:  item => [strings]                                                   f 'text', op has / nhas (contains: any of them)
     cond:  c => test | null | undefined                                        own kinds: a test, null = off, undefined = the core's
     old:   rules => conds                                                      older stored rules converted (optional)
     hard:  [op]                                                                the comparisons that hold on top (default KFLT_HARD)
   kflt_match(item, rules, cat) checks one item, kflt_conds the conditions, kflt_cond one condition. The dialog (rows, value menu,
   the dialog of a saved filter) loads on demand: fltdlg.js kflt_rows / kflt_dialog. The server has the same rules in
   kalmido/core/filters.py. Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const KFLT_HARD = ['nin', 'isnot'];  // hold always, also with OR
const KFLT_OLD = new WeakMap();  // old rules -> their conditions, per catalog (cat.old)
function kflt_conds(/** @type {any} */ r, /** @type {any} */ cat) {
  if (!r || typeof r !== 'object') return [];
  if (Array.isArray(r.conds)) return r.conds;
  if (!cat?.old) return [];
  let m = KFLT_OLD.get(cat.old); if (!m) KFLT_OLD.set(cat.old, m = new WeakMap());
  let c = m.get(r); if (!c) m.set(r, c = cat.old(r));
  return c;
}
// one condition -> null (off: no values, an empty text, an unknown what) or its test item => bool
function kflt_cond(/** @type {any} */ c, /** @type {any} */ cat) {
  if (!c || typeof c !== 'object') return null;
  const own = cat.cond ? cat.cond(c) : undefined; if (own !== undefined) return own;
  if (c.f === 'text' && cat.text) {  // nhas = does not contain, every other comparison = contains
    const q = String(c.v || '').trim().toLowerCase(); if (!q) return null;
    const has = x => cat.text(x).some(s => String(s || '').toLowerCase().includes(q));
    return c.op === 'nhas' ? x => !has(x) : has;
  }
  const has = cat.has?.[c.f]; if (!has) return null;
  if (c.op === 'empty') return cat.empty && c.f in cat.empty ? x => has(x, cat.empty[c.f]) : null;
  if (!Array.isArray(c.v) || !c.v.length) return null;
  if (KFLT_HARD.includes(c.op)) return x => !c.v.some(y => has(x, y));
  return ['in', 'is'].includes(c.op) ? x => c.v.some(y => has(x, y)) : null;
}
function kflt_match(/** @type {any} */ item, /** @type {any} */ r, /** @type {any} */ cat) {
  const soft = [];
  const hard = cat.hard || KFLT_HARD;
  for (const c of kflt_conds(r, cat)) { const fn = kflt_cond(c, cat); if (!fn) continue; if (hard.includes(c.op)) { if (!fn(item)) return false; } else soft.push(fn); }
  if (!soft.length) return true;
  return r?.op === 'or' ? soft.some(fn => fn(item)) : soft.every(fn => fn(item));
}
