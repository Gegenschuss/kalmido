/* Kalmido web client: Start-up: loading the state, polling, the service worker. Loaded last.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ boot
// moved here from popovers.js: vvSync() calls chatFit() (dayplan.js), which a classic script cannot call before it loaded
if (window.visualViewport) {
  visualViewport.addEventListener('resize', vvSync);
  visualViewport.addEventListener('scroll', vvSync);
  window.addEventListener('orientationchange', () => { S.vvMax = 0; setTimeout(vvSync, 250); });
  vvSync();
}

// 2.39.1 (#1213): the loading screen of index.html (#boot) fades out once the first state is drawn (or a sign-in / error
// screen took over); later reloads in the same session skip it (icons.js: html.rebooting)
function bootDone() {
  try { sessionStorage.setItem('kalmido.booted', '1'); } catch { /* no storage */ }
  const b = document.getElementById('boot'); if (!b || b.classList.contains('out')) return;
  b.classList.add('out'); setTimeout(() => b.remove(), 250);
}

(async () => {
  const inv = location.hash.match(/^#invite\/([A-Za-z0-9_-]{20,100})$/);  // 2.22.0 (#697): an invitation / reset link
  if (inv) { bootDone(); await inviteScreen(inv[1]); return; }
  const sil = location.hash.match(/^#signin\/([A-Za-z0-9_-]{20,100})$/);  // 2.23.0 (#444): a sign-in link (QR code)
  if (sil) { bootDone(); await i18nLoad(uiLang()); await signinScreen(sil[1]); return; }
  const i18nBoot = i18nLoad(uiLang());  // last used language (localStorage), in parallel with the state
  try { await outOpen(); await load(); if (!S.lists.length) throw new Error('no state'); } catch (e) { bootDone(); if (e.message === 'auth') return; await i18nBoot; $('#view').innerHTML = botEmpty(navigator.onLine === false ? 'offline' : 'schaut', tr('Server not reachable.'), tr('Reload the page once the server is reachable again.')).replace(/<\/div>$/, `<button type="button" class="btn pri" id="boot-retry">${ic('sync', 's')} ${tr('Try again')}</button></div>`); $('#boot-retry')?.addEventListener('click', () => location.reload()); return; }
  await i18nBoot; await i18nLoad(uiLang()); S.booted = true;
  setTimeout(msvvBoot, 0);  // 2.73.0 C (#661): the other servers (msvview.js), after the own state
  setTimeout(chatFabDraw, 0);  // 2.29.0 (#363)
  if (LS.get('after2fa', false)) { LS.set('after2fa', false); setTimeout(() => settingsModal('account'), 400); }  // 2.22.0 (#697)
  setTimeout(() => { if (document && !document.hidden) wpSweep(); }, 2500);
  setTimeout(() => { if (!document.hidden && !S.setupPending && !S.me?.kid) lc_favSuggest(); }, 8000);  /* 2.49.0 (#1537): not for a child */  // 2.46.1 (#1361): a favourite suggestion, once  // 2.19.0 (#668): opening the app tidies the shade  // render in the server-side language
  // 2.13.0 (#453 A16): the first-run step 2 ("What do you want to use?") was not finished (tab reloaded / closed after the
  // admin account was created): it comes back until "Start" is pressed
  if (S.setupPending && !$('.authscreen')) { const el = document.createElement('div'); el.className = 'modal authscreen'; document.body.appendChild(el); $('#app')?.setAttribute('inert', ''); setupChoices(el, `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`); }
  if (new URLSearchParams(location.search).get('share') === 'err') {
    history.replaceState(null, '', '/#inbox'); await route();
    toast(tr('Share: the file could not be received'));
  } else if (new URLSearchParams(location.search).get('share') === 'refused') {  // 2.81.0 (#1856): the server path kept the task, not every file
    history.replaceState(null, '', '/' + (location.hash || ''));
    await route();
    toast(tr('Share: not every file was added (too large, empty or refused by the upload check)'));
  } else if (new URLSearchParams(location.search).get('share') === '1') {  // files shared via the service worker
    let meta = {title: '', text: '', url: '', files: []}, files = [];
    try {
      const c = await caches.open('tasks-share');
      const m = await c.match('/share-inbox/meta');
      if (m) meta = await m.json();
      files = await Promise.all(meta.files.map(async (f, i) => { const r = await c.match(`/share-inbox/${i}`); return r ? new File([await r.blob()], f.name, {type: f.type}) : null; }));
      files = files.filter(Boolean);
      await caches.delete('tasks-share');
    } catch { /* no cache api */ }
    // Chrome on Android currently hands over no files to installed web apps (verified 2026-09-25)
    const refused = Array.isArray(meta.refused) ? meta.refused : [];  // 2.143.0 C2 (#2154): too large / too many, kept out by the service worker
    if (!files.length && !refused.length && !meta.text && !meta.url && !meta.title) toast(tr('Please share images and files via the ntfy app (topic inbox)'));
    if (refused.length) toast(tr('Share: not added: {0} (at most {1} files of {2} MB each)', refused.map(f => f.name).join(', '), meta.max_files || 20, meta.max_mb || 50), null, 8000);
    history.replaceState(null, '', '/#inbox');
    await route();
    // 2.13.1 (#465): "Send to agent": with an agent to chat with, the share sheet asks where it goes (a new task stays the
    // default); the files + text then wait in that agent's chat box, ready to send
    const ags = agentsOn() ? (S.agents || []).filter(a => a.enabled) : [];
    const docs = files.length && typeof dc_shareOk === 'function' && dc_shareOk();  // 2.48.0 (#1111): "File as document"
    const bmU = !files.length && feat('reading') ? shareLink(meta.text, meta.url)[0] : '';  // 2.97.0 A (#1950): a shared link -> "Save as bookmark"
    // 2.143.0 C (#2154): shared contact cards (.vcf) / calendar files (.ics) can go through the existing imports
    const allOf = re => files.length > 0 && files.every(f => re.test(f.name || '') || re.test(f.type || ''));
    const imp = {contacts: feat('contacts') && allOf(/\.vcf$|^text\/(x-)?vcard\b/i), calendar: feat('events') && (S.evcals || []).some(evWrite) && allOf(/\.ics$|^text\/calendar\b/i)};
    const dest = (ags.length || docs || bmU || imp.contacts || imp.calendar) && (files.length || meta.text || meta.url || meta.title) ? await shareDest(ags, docs, !!bmU, imp) : 'task';
    const ext = (f, e) => new RegExp(`\\.${e}$`, 'i').test(f.name || '') ? f : new File([f], (f.name || 'shared') + '.' + e, {type: f.type});  // the imports go by the ending
    // 2.143.0 C2 (#2154): one question per share: the contact cards go in as one file, the calendar files one after another
    if (dest === 'contacts') { await loadModule('contacts'); ctImport(null, 'vcf', files.length > 1 ? new File([(await Promise.all(files.map(f => f.text()))).join('\r\n')], 'shared.vcf', {type: 'text/vcard'}) : ext(files[0], 'vcf')); }
    else if (dest === 'calendar') { const own = (S.evcals || []).find(x => !x.org_id && x.role === 'owner'), c = own || (S.evcals || []).find(evWrite); for (const f of files) await evImport(c, () => load().then(render).catch(() => {}), ext(f, 'ics')); }
    else if (dest === 'doc') await dc_shareFiles(files);
    else if (dest === 'bookmark') await bm_shareSave(bmU, meta.title);
    else if (dest !== 'task') {
      const txt = [meta.title, meta.text, meta.url && !(meta.text || '').includes(meta.url) ? meta.url : ''].map(x => (x || '').trim()).filter(Boolean).join('\n');
      if (txt) S.drafts['chat:' + dest] = txt;
      S.chatFiles[dest] = files.slice(0, 10);
      chatOpen(dest);
    } else {
    // the link goes into the link field; a bare link gets domain + path as title
    const [u, rest] = shareLink(meta.text, meta.url);
    const title = meta.title || rest || (u ? urlTitle(u) : '') || (files[0] ? files[0].name.replace(/\.[^.]+$/, '') : '');
    openQuickSheet(title, {url: u, list_id: inbox().id, files, ...(S.me ? {assignee_id: S.me.id} : {})});  // 2.27.0 (#1001): yours
    }
  } else if (location.pathname === '/share') {  // Android share sheet (text only, old manifest) -> new task
    const q = new URLSearchParams(location.search);
    const text = (q.get('text') || '').trim();
    history.replaceState(null, '', '/#inbox');
    await route();
    const [u, rest] = shareLink(text, (q.get('url') || '').trim());
    // 2.97.0 A (#1950): the bookmark button of the browser (?bm=1) saves a bookmark; a shared link offers "Save as bookmark"
    const bmU = /^https?:\/\//i.test(u) ? u.slice(0, 2000) : '';
    if (bmU && q.get('bm') === '1') bm_confirmSave(bmU, (q.get('title') || '').trim().slice(0, 300));
    else if (bmU && feat('reading') && await shareDest([], false, true) === 'bookmark') await bm_shareSave(bmU, (q.get('title') || '').trim());
    else openQuickSheet((q.get('title') || '').trim() || rest || (u ? urlTitle(u) : ''), {url: u, list_id: inbox().id, ...(S.me ? {assignee_id: S.me.id} : {})});  // 2.27.0 (#1001): yours
  } else if (new URLSearchParams(location.search).get('action') === 'new') {  // app shortcut "New task"
    history.replaceState(null, '', '/' + (location.hash || ''));
    await route();
    openQuickSheet();
  } else if (new URLSearchParams(location.search).get('action') === 'timer') {  // 2.125.0 C (#2121): app shortcut "Start / stop timer"
    history.replaceState(null, '', '/' + (location.hash || ''));  // the parameter goes first: a reload never toggles twice
    if (timeOn()) location.hash = '#time';
    await route();
    if (!timeOn()) toast(tr('Time tracking is turned off in your settings'));
    else if (S.timer) await timerStop();
    else {  // a timer needs a task or list with time tracking on: the one of the latest entry, else the first such list
      let last = null;
      try { last = ((await api('GET', '/api/time/entries?scope=mine&from=' + new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10))).entries || [])[0]; } catch { /* the first list below */ }
      const lst = S.lists.find(l => l.time_tracking && !l.archived);
      const target = last ? (last.task_id ? {task_id: last.task_id} : {list_id: last.list_id}) : lst ? {list_id: lst.id} : null;
      if (target) await timerStart(target); else toast(tr('Switch on time tracking in the list settings to track time'));
    }
  } else if (new URLSearchParams(location.search).get('action') === 'capture') {  // 2.4.0 (#187): app shortcut "Quick add"
    history.replaceState(null, '', '/' + (location.hash || ''));
    await route();
    quickCapture();
  } else if (location.pathname === '/capture') {  // 2.4.0 (#187): the bookmarklet popup (?title&url) or its help page
    const q = new URLSearchParams(location.search), title = (q.get('title') || '').trim().slice(0, 500), u = (q.get('url') || '').trim();
    S.capturePage = true;
    history.replaceState(null, '', '/capture#inbox');
    await route();
    document.body.classList.add('capmode');
    const url = /^https?:\/\//i.test(u) ? u.slice(0, 2000) : '';
    if (title || url) quickCapture(title || (url ? urlTitle(url) : ''), url ? {url} : {});
    else captureHelp();
  } else await route();
  bootDone();  // 2.39.1 (#1213): the first view is drawn
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
    navigator.serviceWorker.addEventListener('message', swMessage);
  }
  setTimeout(wpSync, 3000);
  pwa_boot();  // 2.143.0 C (#2153): the install hint (setcore.js)
  // v1.1: first start of a new account: "Getting started" list (server side, in the user's language), then the tour
  // 2.24.0 (UX-22): not while the first-run setup is still open (its "Start" reloads; then the list, in the chosen language,
  // and the tour follow, one after the other)
  if (S.setupPending) return;
  if (S.settings.onboard === 'pending') {
    try { const j = await api('POST', '/api/onboarding', {touch: isTouch(), mac: IS_MAC}); if (j?.created) { await load(); render(); } } catch { /* offline: next start */ }
  }
  if (S.settings.tour === 'pending' && !new URLSearchParams(location.search).get('share') && !S.capturePage) setTimeout(tourStart, 400);
  setTimeout(quipsLoad, 1500);
})();
