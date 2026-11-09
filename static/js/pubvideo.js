'use strict';
// 2.99.1 A (#1959): the customer page of a video sign-off (/s/q/<token>, videos/review.py vdr_sig_html); listed as an on-demand
// module (lazyload.js LD_MODS, sw.js LAZY) only for tools/check_layout.py -- the app itself never loads it. Drives the embedded
// player through its postMessage protocol (no script of Vimeo / YouTube is loaded), pauses it while a comment is typed and
// fills the comment's timecode, a tap on a timecode or a mark seeks there, the marks sit at second / duration. Messages are
// taken only from the player's own frame and origin. Without this script the page works as well (timecode typed by hand).
(() => {
  const box = document.querySelector('.vdr-player'); if (!box) return;
  const prov = box.dataset.prov, origin = box.dataset.origin || '';
  let fr = box.querySelector('iframe'), vid = box.querySelector('video, audio');  // 2.633.0 (#4777): audio plays in <audio>
  let cur = 0, dur = 0;
  const p2 =n => String(n).padStart(2, '0');
  const tc = s => { s = Math.floor(s || 0); const h = Math.floor(s / 3600); return h ? `${h}:${p2(Math.floor(s / 60) % 60)}:${p2(s % 60)}` : `${p2(Math.floor(s / 60))}:${p2(s % 60)}`; };
  const send = o => { try { fr.contentWindow.postMessage(JSON.stringify(o), origin); } catch { /* the frame is gone */ } };
  const pause = () => { if (vid) vid.pause(); else if (prov === 'vimeo') send({method: 'pause'}); else send({event: 'command', func: 'pauseVideo', args: []}); };
  const seek = s => { if (vid) vid.currentTime = s; else if (prov === 'vimeo') send({method: 'setCurrentTime', value: s}); else send({event: 'command', func: 'seekTo', args: [s, true]}); };
  const marks = () => {
    if (!(dur > 0)) return;
    document.querySelectorAll('.vdr-mk').forEach(m => { m.style.left = Math.min(100, Math.max(0, +m.dataset.at / dur * 100)) + '%'; });
    document.querySelector('.vdr-tl')?.classList.add('on');
  };
  const setDur = d => { if (+d > 0 && !dur) { dur = +d; marks(); } };
  if (vid) {
    vid.addEventListener('timeupdate', () => { cur = vid.currentTime; });
    vid.addEventListener('loadedmetadata', () => setDur(vid.duration));
  }
  const wireFrame = () => {
    if (!(fr && origin)) return;
    window.addEventListener('message', e => {
      if (e.origin !== origin || e.source !== fr.contentWindow) return;
      let d; try { d = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch { return; }
      if (!d || typeof d !== 'object') return;
      if (prov === 'vimeo') {
        if (d.event === 'ready') hello();
        if (d.event === 'timeupdate' && d.data) { cur = +d.data.seconds || 0; setDur(d.data.duration); }
        if (d.method === 'getDuration') setDur(d.value);
      } else if ((d.event === 'infoDelivery' || d.event === 'initialDelivery') && d.info) {
        if (typeof d.info.currentTime === 'number') cur = d.info.currentTime;
        setDur(d.info.duration);
      }
    });
    const hello = () => prov === 'vimeo' ? (send({method: 'addEventListener', value: 'timeupdate'}), send({method: 'getDuration'}))
      : send({event: 'listening', id: 'vdr', channel: 'widget'});
    fr.addEventListener('load', () => { hello(); setTimeout(hello, 1000); });
  };
  wireFrame();
  // 2.240.0 D (#2886): two clicks -- the placeholder first, the player (and the request to its host) only after "Load video"
  const gate = box.querySelector('[data-vdr-load]');
  if (gate) gate.addEventListener('click', () => {
    const media = prov === 'file' || prov === 'audio', el = document.createElement(prov === 'audio' ? 'audio' : prov === 'file' ? 'video' : 'iframe');
    let src = box.dataset.src || '';
    // 2.122.4 A (#2215 L7): the page opened under another host than the configured address: YouTube talks only to the origin
    // named in the player URL, so name this page's own (never a host header of the request)
    if (prov === 'youtube') { try { const u = new URL(src); u.searchParams.set('origin', location.origin); src = u.href; } catch { /* keep the URL */ } }
    el.setAttribute('src', src);
    if (media) { el.controls = true; el.setAttribute('playsinline', ''); el.preload = prov === 'audio' ? 'metadata' : 'none'; vid = el; }
    else { el.title = box.dataset.title || ''; el.allowFullscreen = true; el.allow = 'fullscreen; picture-in-picture'; el.referrerPolicy = 'strict-origin-when-cross-origin'; fr = el; }
    box.textContent = ''; box.appendChild(el);
    if (vid) {
      vid.addEventListener('timeupdate', () => { cur = vid.currentTime; });
      vid.addEventListener('loadedmetadata', () => setDur(vid.duration));
    } else wireFrame();
  });
  const at = document.getElementById('vd-at'), text = document.getElementById('vd-text'), name = document.getElementById('vd-name');
  if (text && at) text.addEventListener('focus', () => { pause(); if (!at.dataset.manual) at.value = tc(cur); });
  if (at) at.addEventListener('input', () => { at.dataset.manual = at.value ? '1' : ''; });
  const calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a.vdr-at, .vdr-mk'); if (!a) return;
    e.preventDefault(); seek(+a.dataset.at || 0); box.scrollIntoView({block: 'nearest', behavior: calm ? 'auto' : 'smooth'});
  });
  try {  // the name stays on this device for the next comment
    if (name && !name.value) name.value = localStorage.getItem('vdr-name') || '';
    if (name && name.form) name.form.addEventListener('submit', () => localStorage.setItem('vdr-name', name.value.trim()));
  } catch { /* no storage */ }
})();
// 2.764.0 (#5040): the customer page of an image / PDF sign-off (videos/vdmedia.py vdm_pub_stage): the numbered points of the
// comments placed on the image / the PDF page (CSSOM: the page's CSP allows no inline style), a tap on the image / page sets the
// point of the next comment (the form's px / py / pg, 0..1 as in the app), a tap on a comment's point shows it (its page). PDF
// pages come from the bundled pdf.js of the app's PDF preview (pdfview.js: pv_load, pv_timed, PV_OPEN, pv_cv), fetched from the
// link's own media route; nothing in the PDF runs. Without this script the image shows and comments go without a point.
(() => {
  const md = document.querySelector('.vdr-media'); if (!md) return;
  const stage = md.querySelector('.vdr-stage'), pins = md.querySelector('.vdr-pins'), pdf = md.dataset.kind === 'pdf', T = md.dataset;
  const fx = /** @type {HTMLInputElement|null} */ (document.getElementById('vd-px')), fy = /** @type {HTMLInputElement|null} */ (document.getElementById('vd-py'));
  const fp = /** @type {HTMLInputElement|null} */ (document.getElementById('vd-pg')), pst = document.getElementById('vd-pt'), text = document.getElementById('vd-text');
  const calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let page = 1, doc = null, gen = 0, pt = null;
  const fill = (s, ...a) => a.reduce((t, v, i) => t.replace(`{${i}}`, String(v)), s || '');
  const put = (el, x, y) => { el.style.left = (x * 100).toFixed(2) + '%'; el.style.top = (y * 100).toFixed(2) + '%'; };
  const draw = () => {
    if (!pins) return;
    for (const p of /** @type {NodeListOf<HTMLElement>} */ (pins.querySelectorAll('.vdr-pin:not(.new)'))) {
      const on = !pdf || +p.dataset.page === page;
      p.hidden = !on; if (on) put(p, +(p.dataset.x || 0), +(p.dataset.y || 0));
    }
    let n = /** @type {HTMLElement|null} */ (pins.querySelector('.vdr-pin.new'));
    if (pt && (!pdf || pt.page === page)) {
      if (!n) { n = document.createElement('span'); n.className = 'vdr-pin new'; n.setAttribute('aria-hidden', 'true'); n.textContent = T.next || ''; pins.appendChild(n); }
      put(n, pt.x, pt.y);
    } else if (n) n.remove();
  };
  const setPt = p => {
    pt = p;
    if (fx && fy && fp) { fx.value = p ? String(p.x) : ''; fy.value = p ? String(p.y) : ''; fp.value = p && pdf ? String(p.page) : ''; }
    if (pst) { pst.hidden = !p; const sp = pst.querySelector('span'); if (sp) sp.textContent = p ? fill(T.tAt, T.next) : ''; }
    draw();
  };
  const ready = () => !!stage && (!pdf || !!stage.querySelector('canvas')) && (pdf || !!stage.querySelector('img')?.complete);
  if (stage && fx) stage.addEventListener('click', e => {
    const t = /** @type {HTMLElement} */ (e.target); if (t.closest('.vdr-pin') || !ready()) return;
    const r = stage.getBoundingClientRect(); if (!r.width || !r.height) return;
    const cl = v => Math.round(Math.max(0, Math.min(1, v)) * 10000) / 10000;
    setPt({x: cl((e.clientX - r.left) / r.width), y: cl((e.clientY - r.top) / r.height), page});
    text?.focus({preventScroll: true});
  });
  document.querySelector('[data-pt-clear]')?.addEventListener('click', () => setPt(null));
  const hl = el => { if (!el) return; el.classList.remove('hl'); void el.offsetWidth; el.classList.add('hl'); };
  // a tap on a point: its comment; a tap on a comment's point: its page, the point marked
  document.addEventListener('click', async e => {
    const t = /** @type {HTMLElement} */ (e.target), pin = t.closest && t.closest('.vdr-pin[data-id]'), a = t.closest && t.closest('a.vdr-pt');
    if (pin) { const li = document.querySelector(`a.vdr-pt[data-id="${/** @type {HTMLElement} */ (pin).dataset.id}"]`)?.closest('li'); li?.scrollIntoView({block: 'nearest', behavior: calm ? 'auto' : 'smooth'}); hl(li); return; }
    if (!a) return;
    e.preventDefault();
    const d = /** @type {HTMLElement} */ (a).dataset;
    if (pdf && d.page && +d.page !== page) await go(+d.page);
    md.scrollIntoView({block: 'nearest', behavior: calm ? 'auto' : 'smooth'});
    hl(/** @type {HTMLElement|null} */ (pins?.querySelector(`.vdr-pin[data-id="${d.id}"]`)));
  });
  const msg = /** @type {HTMLElement|null} */ (md.querySelector('.vdr-pgmsg')), bar = /** @type {HTMLElement|null} */ (md.querySelector('.vdr-pgbar'));
  // one PDF page at the width of the page; the document is fetched once
  const go = async n => {
    const my = ++gen;
    try {
      if (!doc) {
        const res = await fetch(T.src || '', {credentials: 'same-origin'}); if (!res.ok) throw new Error('http');
        const data = new Uint8Array(await res.arrayBuffer()), lib = await pv_timed(pv_load());
        const task = lib.getDocument({data, ...PV_OPEN});
        doc = await pv_timed(task.promise, task);
      }
      page = Math.max(1, Math.min(doc.numPages, n || 1));
      const pg = await doc.getPage(page), w = Math.max(200, md.clientWidth || 600);
      const cv = await pv_cv(pg, w / pg.getViewport({scale: 1}).width);
      if (my !== gen) return;
      cv.setAttribute('aria-label', fill(T.tPg, page));
      md.querySelector('.vdr-cv')?.replaceChildren(cv);
      if (msg) msg.hidden = true;
      if (bar) {
        bar.hidden = doc.numPages < 2;
        const no = bar.querySelector('.vdr-pgno'); if (no) no.textContent = fill(T.tPage, page, doc.numPages);
        /** @type {HTMLButtonElement} */ (bar.querySelector('[data-pg="-1"]')).disabled = page <= 1;
        /** @type {HTMLButtonElement} */ (bar.querySelector('[data-pg="1"]')).disabled = page >= doc.numPages;
      }
      if (pt && pt.page !== page) setPt(null); else draw();
    } catch (e) {
      if (my !== gen) return;
      if (msg) { msg.hidden = false; msg.textContent = e && /** @type {Error} */ (e).name === 'PasswordException' ? T.tPw || '' : T.tFail || ''; }
    }
  };
  bar?.addEventListener('click', e => { const b = /** @type {HTMLElement} */ (e.target).closest('[data-pg]'); if (b) go(page + +(/** @type {HTMLElement} */ (b).dataset.pg || 0)); });
  if (pdf) go(1);
  else { const img = stage?.querySelector('img'); if (img && !img.complete) img.addEventListener('load', draw, {once: true}); draw(); }
})();
