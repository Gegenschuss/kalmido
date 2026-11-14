// @ts-check
/* Kalmido web client: upload progress with Cancel (2.363.3, #3134). Classic script sharing the global scope (load order:
   index.html, right after lazyload.js). rawFetch0 sends every form with at least UP_MIN bytes of files through upSend, so all file
   dialogs get the same bar without code of their own; smaller forms stay plain fetch calls and show nothing. A form may opt
   out with fd.upQuiet = true (pieces of an upload that draws its own progress, paperless.js). */
'use strict';

const UP_MIN = 1024 * 1024, UP_WAIT = 300;  // no bar for what is done before it could be read
const upFiles = fd => [...fd.values()].filter(v => v instanceof Blob);
const upWanted = fd => !/** @type {any} */ (fd).upQuiet && (!!/** @type {any} */ (fd).upBar || upFiles(fd).reduce((n, f) => n + f.size, 0) >= UP_MIN);  // 2.1165.0 (#6114): upBar = the bar for any size (the file store, the documents)
function upLabel(fd) {
  const fs = upFiles(fd), names = fs.map(f => /** @type {any} */ (f).name).filter(n => n && n !== 'encrypted.kenc');  // an encrypted file has no name to show
  return fs.length > 1 ? tr('Uploading {0} files…', fs.length) : names[0] || tr('Uploading…');
}
function upBox() {
  let b = document.getElementById('upbars');
  if (!b) { b = document.createElement('div'); b.id = 'upbars'; document.body.appendChild(b); }
  return b;
}
function upRow(label, cancel) {
  const el = document.createElement('div'); el.className = 'upbar';
  el.innerHTML = `<div class="uphead"><span class="upn"></span><span class="upp"></span><button type="button"></button></div><div class="uptrack" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div>`;
  const q = s => /** @type {HTMLElement} */ (el.querySelector(s)), btn = q('button'), track = q('.uptrack'), bar = q('.uptrack>i');
  q('.upn').textContent = label; q('.upn').title = label; track.setAttribute('aria-label', label);
  btn.textContent = tr('Cancel'); btn.addEventListener('click', cancel);
  const t = setTimeout(() => upBox().appendChild(el), UP_WAIT);
  return {
    set(p) { q('.upp').textContent = `${p} %`; bar.style.width = `${p}%`; track.setAttribute('aria-valuenow', String(p)); },
    // the body is out: the server stores it now, so Cancel could no longer promise that nothing stays behind
    sent() { this.set(100); btn.remove(); q('.upp').textContent = tr('Being processed…'); },
    done() { clearTimeout(t); el.remove(); if (!document.querySelector('.upbar')) document.getElementById('upbars')?.remove(); },
  };
}
// 2.1165.0 (#6114): a form below UP_MIN that asks for the bar (fd.upBar): the plain fetch with its row (no percent, it is done at
// once) and Cancel aborting it
function upFetch(url, opt, fd) {
  const ac = new AbortController(), row = upRow(upLabel(fd), () => { ac.abort(); toast(tr('Upload cancelled')); });
  return fetch(url, {...opt, signal: ac.signal}).then(r => { row.done(); return r; },
    e => { row.done(); throw ac.signal.aborted ? Object.assign(new Error(tr('Upload cancelled')), {cancelled: true, shown: true}) : e; });
}
// what fetch(url, opt) does for a form, by XHR (fetch reports no upload progress). The answer offers what rawFetch0 reads of a Response.
function upSend(url, opt, fd) {
  if (upFiles(fd).reduce((n, f) => n + f.size, 0) < UP_MIN) return upFetch(url, opt, fd);  // 2.1165.0 (#6114)
  return new Promise((ok, no) => {
    const x = new XMLHttpRequest();
    const row = upRow(upLabel(fd), () => { x.abort(); toast(tr('Upload cancelled')); });
    x.open(opt.method, url);
    for (const [k, v] of Object.entries(opt.headers || {})) x.setRequestHeader(k, v);
    x.upload.onprogress = e => { if (e.lengthComputable) row.set(Math.min(99, Math.round(e.loaded / e.total * 100))); };
    x.upload.onload = () => row.sent();
    x.onabort = () => { row.done(); no(Object.assign(new Error(tr('Upload cancelled')), {cancelled: true, shown: true})); };
    x.onload = () => {
      row.done();
      const same = !x.responseURL || x.responseURL === new URL(url, location.href).href;  // opt.redirect 'manual' does not exist here: a redirect shows in the final address
      ok({status: x.status, ok: x.status >= 200 && x.status < 300, type: same ? 'basic' : 'opaqueredirect',
        headers: {get: k => x.getResponseHeader(k)}, json: async () => JSON.parse(x.responseText)});
    };
    // a redirect to a login on another host ends as a network error here: a bodyless look tells it from being offline
    x.onerror = async () => {
      row.done();
      const r = await fetch('/api/state?lz=1&lzl=', {redirect: 'manual', headers: {'X-Requested-With': 'kalmido'}}).catch(() => null);
      if (r?.type === 'opaqueredirect') ok(r); else no(new Error('offline'));
    };
    x.send(fd);
  });
}
// 2.766.0 (#5220): code integrity stage 3 b. The service worker reports other content hashes of the code under the same
// version (static/sw.js swCodeNote): a quiet bar "The app's code changed without a new version" with a way to Settings > Help >
// Check code. Closing it or opening the check confirms it to the worker (code-ack); unconfirmed, the next start shows it again.
// Every start asks the worker once (code-check) when the page is drawn.
function upCodeAck() { navigator.serviceWorker?.ready?.then(r => r.active?.postMessage({type: 'code-ack'})).catch(() => {}); }
function upCodeBar(d) {
  if (document.getElementById('codechg') || typeof tr !== 'function') return;
  const el = document.createElement('div'); el.id = 'codechg'; el.setAttribute('role', 'status');
  el.innerHTML = '<span></span><button type="button" class="btn sm pri" data-ccgo></button><button type="button" class="iconbtn" data-ccx></button>';
  const sp = /** @type {HTMLElement} */ (el.querySelector('span')), go = /** @type {HTMLElement} */ (el.querySelector('[data-ccgo]')), x = /** @type {HTMLElement} */ (el.querySelector('[data-ccx]'));
  sp.textContent = tr("The app's code changed without a new version"); sp.title = tr('Version {0}', d.version || '?');
  go.textContent = tr('Check code');
  x.innerHTML = typeof ic === 'function' ? ic('x', 's') : '×'; x.title = tr('Close'); x.setAttribute('aria-label', tr('Close'));
  go.addEventListener('click', () => { el.remove(); upCodeAck(); loadModule('settings').then(() => settingsModal('codecheck'), () => {}); });
  x.addEventListener('click', () => { el.remove(); upCodeAck(); });
  document.body.appendChild(el);
}
if (globalThis.navigator?.serviceWorker?.addEventListener) {
  navigator.serviceWorker.addEventListener('message', e => { if (e.data?.type === 'code-changed' && typeof e.data.version === 'string') upCodeBar(e.data); });
  addEventListener('load', () => navigator.serviceWorker.ready?.then(r => r.active?.postMessage({type: 'code-check'})).catch(() => {}));  // a stub without ready (jsdom tests): nothing
}
