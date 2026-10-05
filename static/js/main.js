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

(async () => {
  const i18nBoot = i18nLoad(uiLang());  // last used language (localStorage), in parallel with the state
  try { await load(); if (!S.lists.length) throw new Error('no state'); } catch (e) { if (e.message === 'auth') return; await i18nBoot; $('#view').innerHTML = heronEmpty(navigator.onLine === false ? 'offline' : 'error', tr('Server not reachable.'), tr('Reload the page once the server is reachable again.')).replace(/<\/div>$/, `<button type="button" class="btn pri" id="boot-retry">${ic('sync', 's')} ${tr('Try again')}</button></div>`); $('#boot-retry')?.addEventListener('click', () => location.reload()); return; }
  await i18nBoot; await i18nLoad(uiLang()); S.booted = true;
  setTimeout(() => { if (document && !document.hidden) wpSweep(); }, 2500);  // 2.19.0 (#668): opening the app tidies the shade  // render in the server-side language
  // 2.13.0 (#453 A16): the first-run step 2 ("What do you want to use?") was not finished (tab reloaded / closed after the
  // admin account was created): it comes back until "Start" is pressed
  if (S.setupPending && !$('.authscreen')) { const el = document.createElement('div'); el.className = 'modal authscreen'; document.body.appendChild(el); $('#app')?.setAttribute('inert', ''); setupChoices(el, `<div class="alogo">${logoSvg(40)}<b>${APP_NAME}</b></div>`); }
  if (new URLSearchParams(location.search).get('share') === 'err') {
    history.replaceState(null, '', '/#inbox'); await route();
    toast(tr('Share: the file could not be received'));
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
    if (!files.length && !meta.text && !meta.url && !meta.title) toast(tr('Please share images and files via the ntfy app (topic inbox)'));
    history.replaceState(null, '', '/#inbox');
    await route();
    // 2.13.1 (#465): "Send to agent": with an agent to chat with, the share sheet asks where it goes (a new task stays the
    // default); the files + text then wait in that agent's chat box, ready to send
    const ags = agentsOn() ? (S.agents || []).filter(a => a.enabled) : [];
    const dest = ags.length && (files.length || meta.text || meta.url || meta.title) ? await shareDest(ags) : 'task';
    if (dest !== 'task') {
      const txt = [meta.title, meta.text, meta.url && !(meta.text || '').includes(meta.url) ? meta.url : ''].map(x => (x || '').trim()).filter(Boolean).join('\n');
      if (txt) S.drafts['chat:' + dest] = txt;
      S.chatFiles[dest] = files.slice(0, 10);
      chatOpen(dest);
    } else {
    // the link goes into the link field; a bare link gets domain + path as title
    const [u, rest] = shareLink(meta.text, meta.url);
    const title = meta.title || rest || (u ? urlTitle(u) : '') || (files[0] ? files[0].name.replace(/\.[^.]+$/, '') : '');
    openQuickSheet(title, {url: u, list_id: inbox().id, files});
    }
  } else if (location.pathname === '/share') {  // Android share sheet (text only, old manifest) -> new task
    const q = new URLSearchParams(location.search);
    const text = (q.get('text') || '').trim();
    history.replaceState(null, '', '/#inbox');
    await route();
    const [u, rest] = shareLink(text, (q.get('url') || '').trim());
    openQuickSheet((q.get('title') || '').trim() || rest || (u ? urlTitle(u) : ''), {url: u, list_id: inbox().id});
  } else if (new URLSearchParams(location.search).get('action') === 'new') {  // app shortcut "New task"
    history.replaceState(null, '', '/' + (location.hash || ''));
    await route();
    openQuickSheet();
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
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
    navigator.serviceWorker.addEventListener('message', swMessage);
  }
  setTimeout(wpSync, 3000);
  // v1.1: first start of a new account: "Getting started" list (server side, in the user's language), then the tour
  if (S.settings.onboard === 'pending') {
    try { const j = await api('POST', '/api/onboarding', {touch: isTouch(), mac: IS_MAC}); if (j?.created) { await load(); render(); } } catch { /* offline: next start */ }
  }
  if (S.settings.tour === 'pending' && !new URLSearchParams(location.search).get('share') && !S.capturePage) setTimeout(tourStart, 400);
  setTimeout(quipsLoad, 1500);
})();
