// 2.633.0 D (#4777) UI test, own container (start.sh), Firefox: an audio sign-off in the real browser, on a phone (320 px,
// kalmido-suite: fresh
// touch) and on a desktop (1024 px, mouse). The app: the task's section shows the audio row (music symbol), the review view
// waits behind "Load audio" (the file lies on another host), then plays in the browser's own <audio> element (no 16:9 box, no
// iframe); a small WAV made in the page (a blob - the app's CSP allows blob: media; no foreign URL is loaded) gives the
// player a duration; seeking to 00:42 and typing pauses it and keeps "at 00:42", Send stores the comment at that second, the
// mark sits on the time line at 42.3 / 60 and a tap on the timecode jumps the <audio> there. A second link = v2 (version
// switch). Nothing sticks out sideways at 320 px. The customer page (#4772 link): "Load audio" builds an <audio> element
// (controls, the link as src), a tap on a customer timecode seeks it, no overflow at 320 px.
// Invented names only. freelancer-matrix: videos (the API suite p2633_d_audiorev_test.py runs the person without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2633_d_audiorev_ui', check, shots: 'P2633D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2633D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); if (!r.ok) console.log('call failed', method, url, r.status); return r.json().catch(() => ({})); };
// a silent WAV of 60 s (8 kHz, 8 bit, mono), made in the page -> blob: URL
const WAV = `(() => { const sr = 8000, n = sr * 60, b = new ArrayBuffer(44 + n), d = new DataView(b), w = (o, s) => { for (let i = 0; i < s.length; i++) d.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); d.setUint32(4, 36 + n, true); w(8, 'WAVE'); w(12, 'fmt '); d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true);
  d.setUint32(24, sr, true); d.setUint32(28, sr, true); d.setUint16(32, 1, true); d.setUint16(34, 8, true); w(36, 'data'); d.setUint32(40, n, true);
  new Uint8Array(b, 44).fill(128); return URL.createObjectURL(new Blob([b], {type: 'audio/wav'})); })()`;
const FIT = sel => `(() => { const vw = document.documentElement.clientWidth, e = document.querySelector(${JSON.stringify(sel)}), r = e && e.getBoundingClientRect();
  return JSON.stringify({vw, sx: document.documentElement.scrollWidth, l: r ? Math.round(r.left) : null, r: r ? Math.round(r.right) : null, w: r ? Math.round(r.width) : null}); })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,videos'});
  const L = await call('POST', '/api/lists', {name: 'Podcast', kind: 'project'});

  for (const [wd, ht, touch] of [[320, 640, true], [1024, 800, false]]) {
    const tag = `${wd}:`;
    const T = await call('POST', '/api/tasks', {title: 'Folge ' + wd, list_id: L.id});
    const R = await call('POST', '/api/videos', {task_id: T.id, url: 'https://media.example.com/folge/mix.mp3', title: 'Mischung ' + wd});
    check(R.id && R.versions?.[0]?.provider === 'audio', tag + ' setup: an audio review ' + JSON.stringify(R.versions));
    // the customer link with one customer comment at 00:42 (through the page's own form)
    const so = await call('POST', `/api/videos/${R.id}/signoff`, {});
    const tok = (so.url || '').split('/s/q/')[1] || '';
    const pg = await (await fetch(B + 's/q/' + tok, {headers: {'Accept-Language': 'en'}})).text();
    const fk = (pg.match(/name="f" value="([^"]+)"/) || [])[1] || '', vk = (pg.match(/name="v" value="([^"]+)"/) || [])[1] || '';
    await fetch(B + `s/q/${tok}/comments`, {method: 'POST', redirect: 'manual', body: new URLSearchParams({f: fk, v: vk, name: 'Kundin Example', text: 'Zu laut', at: '00:42'})});

    await firefox(async o => {
      const {cmd, ev, ctx, until, idle, shot} = o;
      await o.nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ' login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});

      // ================= the app: the row, the placeholder, the <audio> player
      await o.nav(B + '#t/' + T.id); await idle();
      check(await until(`!!document.querySelector('#detail #d-vdr [data-vdr="open"]')`), tag + ' the task lists the audio review');
      check(await ev(`(() => { const d = document.createElement('div'); d.innerHTML = ic('music', 's'); return document.querySelector('#detail #d-vdr [data-vdr="open"] svg')?.innerHTML === d.firstChild.innerHTML; })()`),
        tag + ' the row carries the music symbol');
      check(await ev(`/Add video or audio link/.test(document.querySelector('#detail [data-vdr="new"]')?.textContent || '')`), tag + ' the button says "Add video or audio link"');
      await ev(`document.querySelector('#detail #d-vdr [data-vdr="open"]').click(), 1`);
      check(await until(`!!document.querySelector('.vdrdlg .vdrgate[data-prov="audio"] [data-vdr="gate"]')`), tag + ' the audio waits behind the placeholder');
      check(await ev(`/Load audio/.test(document.querySelector('.vdrdlg .vdrgate')?.textContent || '') && /media\\.example\\.com/.test(document.querySelector('.vdrdlg .vdrgate')?.textContent || '') && !document.querySelector('.vdrdlg audio, .vdrdlg video, .vdrdlg iframe')`),
        tag + ' "Load audio" names the host, no player yet');
      await ev(`document.querySelector('.vdrdlg [data-vdr="gate"]').click(), 1`);
      check(await until(`document.querySelector('.vdrdlg .vdrplay[data-prov="audio"] audio')?.getAttribute('src') === 'https://media.example.com/folge/mix.mp3'`), tag + ' the browser\'s <audio> player with the link');
      const g = JSON.parse(await ev(`(() => { const a = document.querySelector('.vdrdlg .vdrplay audio'), p = a.parentNode.getBoundingClientRect(), r = a.getBoundingClientRect();
        return JSON.stringify({controls: a.controls, ph: Math.round(p.height), pw: Math.round(p.width), ah: Math.round(r.height), aw: Math.round(r.width), ar: getComputedStyle(a.parentNode).aspectRatio, iframe: !!document.querySelector('.vdrdlg iframe, .vdrdlg video')}); })()`));
      check(g.controls && !g.iframe && g.ah > 0 && g.aw >= g.pw - 1 && g.ph < g.pw * 9 / 16 - 4, tag + ' a plain audio bar, no 16:9 box ' + JSON.stringify(g));
      // a small WAV of 60 s gives the player its duration (the https link cannot load in the test)
      await ev(`(() => { const a = document.querySelector('.vdrdlg .vdrplay audio'); a.src = ${WAV}; a.load(); return 1; })()`);
      check(await until(`VDR.cur && VDR.cur.ctl && Math.round(VDR.cur.ctl.dur) === 60`), tag + ' the player knows the duration (60 s) ' + await ev(`String(VDR.cur?.ctl?.dur)`));
      await ev(`(() => { document.querySelector('.vdrdlg .vdrplay audio').currentTime = 42.3; return 1; })()`);
      check(await until(`VDR.cur && Math.abs(VDR.cur.ctl.cur - 42.3) < 0.05`), tag + ' the player time follows the <audio> (42.3)');
      await ev(`(() => { const a = document.querySelector('.vdrdlg .vdrplay audio'); window.__p = 0; a.addEventListener('pause', () => { window.__p = 1; }); a.play().catch(() => {}); return 1; })()`);
      await ev(`(() => { const t = document.querySelector('#vdr-in'); t.focus(); return 1; })()`);
      check(await until(`/at 00:42/.test(document.querySelector('.vdrdlg [data-vdr="at"]')?.textContent || '')`), tag + ' typing keeps the time: at 00:42');
      check(await ev(`document.querySelector('.vdrdlg .vdrplay audio').paused`), tag + ' typing pauses the <audio>');
      await ev(`(() => { const t = document.querySelector('#vdr-in'); t.value = 'Rauschen hier ${wd}'; document.querySelector('.vdrdlg [data-vdr="send"]').click(); return 1; })()`);
      const cm = await until(`fetch('/api/videos/${R.id}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => { const c = (j.comments || []).find(x => x.body === 'Rauschen hier ${wd}'); return c ? JSON.stringify(c) : ''; })`);
      check(cm && JSON.parse(cm).at_sec === 42.3, tag + ' the comment stored at 42.3 ' + cm);
      // 2.641.0 (#4769): the customer's mark is there before the send - wait for both, not for any
      check(await until(`document.querySelectorAll('.vdrdlg .vdrtl .vdrmk').length >= 2`), tag + ' a mark on the time line');
      const left = await ev(`[...document.querySelectorAll('.vdrdlg .vdrtl .vdrmk')].map(m => m.style.left).join(' ')`);
      // two marks: the customer's comment at 42.0 (70 %) and this one at 42.3
      check(/\b70\.5%/.test(left) && /\b70%/.test(left), tag + ' the marks at 42.0 and 42.3 / 60 = 70 % and 70.5 % ' + left);
      await ev(`(() => { document.querySelector('.vdrdlg .vdrplay audio').currentTime = 5; return 1; })()`);
      await until(`Math.abs(VDR.cur.ctl.cur - 5) < 0.05`);
      await ev(`(() => { const b = document.querySelector('.vdrdlg .vdrtc[data-vdr="seek"][data-at="42.3"]'); b.click(); return 1; })()`);
      check(await until(`Math.abs(document.querySelector('.vdrdlg .vdrplay audio').currentTime - 42.3) < 0.1`), tag + ' a tap on the timecode jumps the <audio> to 00:42 '
        + await ev(`String(document.querySelector('.vdrdlg .vdrplay audio').currentTime)`));
      if (wd < 768) {
        const f = JSON.parse(await ev(FIT('.vdrdlg .card')));
        const a = JSON.parse(await ev(FIT('.vdrdlg .vdrplay audio')));
        check(f.sx <= f.vw && f.r <= f.vw && f.l >= 0 && a.r <= f.r && a.l >= f.l, `${tag} nothing sticks out sideways (page ${f.sx} / ${f.vw}, card ${JSON.stringify(f)}, audio ${JSON.stringify(a)})`);
      }
      await shot(`p2633d-app-${wd}.png`);
      // a second link = v2, the version switch
      await call('POST', `/api/videos/${R.id}/versions`, {url: 'https://media.example.com/folge/mix_v2.flac'});
      await ev(`(() => { document.querySelector('.vdrdlg [data-m="close"]').click(); vdr_open(${R.id}); return 1; })()`);
      check(await until(`document.querySelectorAll('.vdrdlg #vdr-ver option').length === 2 && !!document.querySelector('.vdrdlg .vdrgate[data-prov="audio"]')`), tag + ' v2: the version switch and the audio placeholder');

      // ================= the customer page
      await o.nav(B + 's/q/' + tok); await idle();
      check(await until(`!!document.querySelector('.vdr-player.vdr-aud[data-prov="audio"] [data-vdr-load]')`), tag + ' customer page: the audio placeholder');
      check(await ev(`/Load audio/.test(document.querySelector('.vdr-player')?.textContent || '') && !document.querySelector('audio, video, iframe')`), tag + ' customer page: "Load audio", no player before the click');
      await ev(`document.querySelector('[data-vdr-load]').click(), 1`);
      check(await until(`document.querySelector('.vdr-player audio')?.getAttribute('src') === 'https://media.example.com/folge/mix_v2.flac' && document.querySelector('.vdr-player audio').controls`), tag + ' customer page: the <audio> player of the newest version');
      // v2 has no comment yet: the customer comments at 00:42 of v1 are not on the page; type one through the page form.
      // The https link cannot load in the test and the page's CSP allows https: media only (no blob:): the element's clock is
      // stood in for (currentTime keeps its value and fires timeupdate, pause() is noted) - pubvideo.js talks to it as to any <audio>
      const STUB = `(() => { const a = document.querySelector('.vdr-player audio'); let t = 0; window.__paused = 0;
        Object.defineProperty(a, 'currentTime', {configurable: true, get: () => t, set: v => { t = +v; a.dispatchEvent(new Event('timeupdate')); }});
        a.pause = () => { window.__paused = 1; }; return 1; })()`;
      await ev(STUB);
      await ev(`(() => { const a = document.querySelector('.vdr-player audio'); a.currentTime = 42; return 1; })()`);
      await ev(`(() => { const t = document.getElementById('vd-text'); t.focus(); t.dispatchEvent(new FocusEvent('focus')); return 1; })()`);
      check(await until(`document.getElementById('vd-at')?.value === '00:42'`), tag + ' customer page: typing fills the timecode 00:42 ' + await ev(`String(document.getElementById('vd-at')?.value)`));
      check(await ev(`window.__paused === 1`), tag + ' customer page: typing pauses the <audio>');
      await ev(`(() => { document.getElementById('vd-name').value = 'Kundin Example'; document.getElementById('vd-text').value = 'Ende zu kurz'; document.getElementById('vdr-f').submit(); return 1; })()`);
      // 2.658.0 (#5102): the page after the form is ready only when pubvideo.js has wired "Load audio" (readyState complete:
      // every script ran); a click before that did nothing, no <audio> came and the stand-in threw on null (CI only, slow runner)
      check(await until(`document.readyState === 'complete' && /Thank you, your comment has arrived/.test(document.body.textContent) && !!document.querySelector('a.vdr-at[data-at="42.0"]')`), tag + ' customer page: the comment at 00:42 arrived');
      await ev(`document.querySelector('[data-vdr-load]').click(), 1`);
      check(await until(`!!document.querySelector('.vdr-player audio')`), tag + ' customer page: "Load audio" again builds the <audio>');
      await ev(STUB);
      await ev(`document.querySelector('a.vdr-at').click(), 1`);
      check(await until(`Math.abs(document.querySelector('.vdr-player audio').currentTime - 42) < 0.1`), tag + ' customer page: a tap on the timecode seeks the <audio> '
        + await ev(`String(document.querySelector('.vdr-player audio')?.currentTime)`));
      if (wd < 768) {
        const f = JSON.parse(await ev(FIT('.vdr-player')));
        check(f.sx <= f.vw && f.r <= f.vw && f.l >= 0, `${tag} customer page: nothing sticks out sideways ${JSON.stringify(f)}`);
      }
      await shot(`p2633d-customer-${wd}.png`);
    }, touch);
  }

  console.log(`p2633_d_audiorev_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
