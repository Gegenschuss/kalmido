// @ts-check
/* Kalmido web client: Settings > Account > Support access (2.485.0, #3939). Only on a hosted server: the operator cannot reach
   into a client's account or organisation; here the person opens the door for a limited time (own account, and every
   organisation the person administers), sees until when, ends it at any time and sees what the operator did with it (time,
   who, which kind of request -- never contents). A self-hosted server shows nothing (GET answers hosted=false). */
const SGV_HOURS = {1: N_('1 hour'), 24: N_('1 day'), 72: N_('3 days'), 168: N_('7 days')};
const sgvHtml = () => `<div id="s-sgv" hidden></div>`;
const sgvWhen = x => { const d = new Date(x); return x && !isNaN(+d) ? fmtStamp(d) : ''; };
function sgvVerb(u) {  // reading or changing, and whether the server let it through
  const rd = u.method === 'GET' || u.method === 'HEAD';
  return u.status >= 400 ? tr('refused') : rd ? tr('viewed') : tr('changed');
}
function sgvGrantHtml(gr, key, label) {
  const pick = `<select data-sgv-h="${key}" aria-label="${esc(tr('Duration'))}">${Object.entries(SGV_HOURS).map(([h, n]) => `<option value="${h}"${h === '24' ? ' selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>`;
  const uses = gr?.uses || [];
  return `<div class="mrow sgvrow" data-sgv-k="${key}"><span class="n"><b>${esc(label)}</b>
      <small class="muted">${gr ? esc(tr('Open until {0}', sgvWhen(gr.ends_at))) + (gr.by ? ' · ' + esc(tr('granted by {0}', gr.by)) : '') : esc(tr('Closed|support'))}</small></span>
      ${gr ? `<span class="tfastate on">${tr('Open|support')}</span><button class="btn sm" data-sgv="end" data-gid="${gr.id}">${ic('lock', 's')} ${tr('End now')}</button>`
    : `${pick}<button class="btn sm" data-sgv="grant">${ic('key', 's')} ${tr('Grant')}</button>`}</div>
    ${gr ? `<div class="sgvuses">${uses.length ? `<ul class="slist">${uses.slice(0, 20).map(u => `<li><span class="muted">${esc(sgvWhen(u.at))}</span> ${esc(u.by || tr('Support'))}: ${esc(sgvVerb(u))} <code>${esc(u.method + ' ' + u.route)}</code></li>`).join('')}</ul>` : `<div class="muted mhint">${tr('Support has not used it yet.')}</div>`}</div>` : ''}`;
}
async function sgvDraw(md) {
  const box = $('#s-sgv', md); if (!box) return;
  let j; try { j = await api('GET', '/api/support-access'); } catch { return; }
  if (!j.hosted || !md.isConnected) { box.hidden = true; return; }
  box._j = j; box.hidden = false;
  const past = j.past || [];
  box.innerHTML = `<h4 id="s-sgv-h">${tr('Support access')}</h4>
    <div class="members">${sgvGrantHtml(j.account, 'me', tr('My account'))}${(j.orgs || []).map(o => sgvGrantHtml(o.grant, String(o.org_id), o.name)).join('')}</div>
    <div class="shint">${tr('The operator of this server cannot see into your account or organisation. If you need help, open it here for a limited time: support can then sign you in, reset your password or look at your projects. It closes by itself and you can end it at any time. What support does with it is recorded here: time, method, route and status, never contents. The same reading or refused request within 10 minutes counts once, at most 300 entries are kept (readings go first), the latest 20 are shown, and of earlier access only the number.')}</div>
    ${past.length ? `<details><summary>${tr('Earlier support access')}</summary><ul class="slist">${past.map(p => `<li>${esc(tr('{0} to {1}', sgvWhen(p.created_at), sgvWhen(p.ended_at || p.ends_at)))} · ${esc(trn('{0} access', '{0} accesses', p.uses.length))}</li>`).join('')}</ul></details>` : ''}`;
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-sgv]'); if (!b) return;
  const md = b.closest('.modal') || document, box = $('#s-sgv', md); if (!box?._j) return;
  if (kd_pinNeed()) return kd_pinAsk(() => b.click());  // a child with the parents' PIN: like the other account settings
  const k = b.closest('[data-sgv-k]')?.dataset.sgvK;
  b.disabled = true;
  try {
    if (b.dataset.sgv === 'grant') {
      const hours = +($(`[data-sgv-h="${k}"]`, md)?.value || 24);
      const org = k === 'me' ? null : +k;
      if (!await askConfirm(tr('Open support access?'), tr('Until it ends, the operator\'s support can act in {0} as an administrator could. Every access is listed for you.', org ? (box._j.orgs.find(o => o.org_id === org)?.name || '') : tr('your account')), {ok: tr('Grant')})) return;
      await api('POST', '/api/support-access', {hours, ...(org ? {org_id: org} : {})});
      toast(tr('Support access granted'));
    } else {
      await api('DELETE', '/api/support-access/' + (+b.dataset.gid));
      toast(tr('Support access ended'));
    }
    await sgvDraw(md);
  } catch { /* api() showed it */ } finally { b.disabled = false; }
});
