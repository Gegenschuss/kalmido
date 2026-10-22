// @ts-check
/* Kalmido web client: 2.126.1 B (#2125) -- table rows as tasks, proposed by an agent. The agent sends a proposal of kind
   "sheet_tasks" (POST /api/v1/agent/proposals/sheet-tasks); the proposal sheet of agents.js (propOpen / propDraw) shows for
   this kind the table, the target list and one row per table row as the person sees it now: tick, title (editable, the
   agent may have suggested one), due date (editable), notes. Rows that are gone, carried over before or without a title are
   greyed out. Applying runs the table's own "rows -> tasks" as the person (server: agents/sheetprop.py, sheets/step2.py);
   one undo step takes the tasks back and the rows lose their mark. Classic script sharing the global scope with the others
   (load order: index.html); it only defines functions, agents.js calls them. */
'use strict';

const sht_is = v => v?.kind === 'sheet_tasks';
const sht_keys = v => (v.sheet_rows || []).filter(x => !x.state).map(x => x.key);
const SHT_STATE = {done: N_('Already carried over into a task'), gone: N_('This row was deleted'), empty: N_('No title in this row')};
function sht_rowHtml(x) {
  if (!x.state) return propItemHtml(x.key, {title: x.title, due: x.due, notes: x.notes}, {orig: x.title !== x.cell_title && x.cell_title ? x.cell_title : '',
    chips: x.n ? `<span class="ppchip">${esc(tr('Row {0}', x.n))}</span>` : ''});
  return `<div class="ppi off shtx" data-k="${x.key}"><label class="ppcl"><input type="checkbox" class="ppc" disabled aria-label="${esc(tr('Row {0}', x.n || '?'))}"></label>
    <div class="ppb"><div class="pprow"><span class="ppt">${esc(x.title || x.cell_title || '–')}</span></div>
      <div class="ppf"><span class="ppchip">${esc(x.n ? tr('Row {0}', x.n) : '–')}</span><small class="muted">${esc(tr(SHT_STATE[x.state] || ''))}</small></div></div></div>`;
}
function sht_draw(v) {
  const p = v.proposal || {}, rows = v.sheet_rows || [], ok = sht_keys(v).length;
  const where = v.sheet ? `<div class="pptask">${ic('sheet', 's')}<a href="#sheets/${+v.sheet.id}">${esc(v.sheet.title || tr('Table'))}</a>
      <span class="muted">→</span>${ic('list', 's')}<b>${esc(v.list?.name || tr('a project you cannot see'))}</b></div>` : `<div class="shint warn keep">${esc(tr('You can no longer open this table.'))}</div>`;
  const main = `${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}${where}
    ${ok ? `<div class="ppbar"><button class="btn sm" data-pp="all">${tr('Select all')}</button><button class="btn sm" data-pp="none">${tr('Select none')}</button></div>` : ''}
    <div class="ppl">${rows.map(sht_rowHtml).join('')}</div>
    <div class="shint keep">${esc(tr('Applying creates one task per selected row in this project, as you (the history names {0}); the rows get the mark "Carried over". One step, undo takes it back.', v.agent.name))}</div>`;
  const foot = `<button class="btn danger" data-pp="discard">${tr('Discard')}</button><span class="spacer"></span><span class="muted ppcount ppfc"></span><button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" ${ok && v.sheet ? '' : 'disabled'}></button>`;
  return {main, foot};
}
