'use strict';
// 2.99.1 A (#1959): the customer page of a video sign-off (/s/q/<token>, videos/review.py vdr_sig_html); listed as an on-demand
// module (lazyload.js LD_MODS, sw.js LAZY) only for tools/check_layout.py -- the app itself never loads it. Drives the embedded
// player through its postMessage protocol (no script of Vimeo / YouTube is loaded), pauses it while a comment is typed and
// fills the comment's timecode, a tap on a timecode or a mark seeks there, the marks sit at second / duration. Messages are
// taken only from the player's own frame and origin. Without this script the page works as well (timecode typed by hand).
(() => {
  const box = document.querySelector('.vdr-player'); if (!box) return;
  const prov = box.dataset.prov, origin = box.dataset.origin || '', fr = box.querySelector('iframe'), vid = box.querySelector('video');
  let cur = 0, dur = 0;
  const p2 = n => String(n).padStart(2, '0');
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
  } else if (fr && origin) {
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
  }
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
