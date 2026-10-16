'use strict';
// 2.50.0 (#329): list dialog > Public link > "What does the customer see?" - the customer view's switches (the server
// filters the page by them; a new or older link starts with sections + due dates, as before)
const cv_flags = () => [['progress', tr('Progress bar')], ['sections', tr('Sections')], ['due', tr('Due dates')], ['assignees', tr('Assignee (name only)')],
  ['tags', tr('Tags')], ['files', tr('Files of the tasks')], ['brand', tr('Name and logo of the organisation')], ['feedback', tr('Comments from the customer')]];
const CV_DEF = {progress: false, sections: true, due: true, assignees: false, tags: false, files: false, brand: false, feedback: false, fields: [], tag: null};
function cv_html(k, opt) {
  const s = {...CV_DEF, ...(k?.show || {})}, o = opt || k?.options || {tags: [], fields: []};
  const box = (id, on, label) => `<label class="chkl"><input type="checkbox" data-cv="${id}" ${on ? 'checked' : ''}> ${esc(label)}</label>`;
  return `<div class="cvsec" id="cv-sec"><div class="cvh">${tr('What does the customer see?')}</div>
    <div class="cvopts">${cv_flags().map(([id, l]) => box(id, s[id], l)).join('')}
    ${(o.fields || []).map(f => `<label class="chkl"><input type="checkbox" data-cvf="${f.id}" ${s.fields.includes(f.id) ? 'checked' : ''}> ${esc(f.name)}</label>`).join('')}</div>
    ${(o.tags || []).length ? `<div class="row"><label for="cv-tag">${tr('Tasks')}</label><select id="cv-tag"><option value="">${tr('All tasks')}</option>${o.tags.map(t => `<option value="${t.id}" ${s.tag === t.id ? 'selected' : ''}>${esc(tr('Only with tag {0}', t.name))}</option>`).join('')}</select></div>` : ''}
    <div class="shint">${tr('Comments within the team are never shown.')} ${tr('Comments from the customer arrive as comments on the task, with the name they typed.')}</div></div>`;
}
function cv_read(md) {
  const sec = $('#cv-sec', md); if (!sec) return null;
  const out = {fields: []};
  $$('[data-cv]', sec).forEach(i => { out[i.dataset.cv] = i.checked; });
  $$('[data-cvf]', sec).forEach(i => { if (i.checked) out.fields.push(+i.dataset.cvf); });
  const t = $('#cv-tag', sec); if (t) out.tag = t.value ? +t.value : null;
  return out;
}
// the author of a comment: a customer's comment through the public link carries the name they typed (collab.js)
const cv_who = (c, U) => c.ext_name ? tr('{0} (customer, via the link)', c.ext_name) : uname(c.user_id, U);
