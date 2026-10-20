// 2.139.0 UI tests, part B (#2128): voice messages in the team chat, own container (start.sh). jsdom at phone width with a
// fake microphone (getUserMedia + MediaRecorder stand-ins: no real recording, a few bytes with the MP4 signature):
// the microphone next to the paperclip only while the text box is empty; tap = the recording bar (running time, discard,
// send, stop = listen first); send = a voice message (voice=1, duration_ms) with the player in the message (play / pause,
// position, remaining time, speed 1x / 1.5x / 2x, download); discard sends nothing and releases the microphone; a blocked
// microphone says how to allow it; no microphone in an end-to-end encrypted DM; voice.js loads on demand (lazy).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2139B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const M4A = Buffer.concat([Buffer.from('0000001c667479704d344120000002004d34412069736f6d6d703432', 'hex'), Buffer.alloc(512, 7)]);

// the fake microphone: getUserMedia gives a stream whose track counts its stop; MediaRecorder records audio/mp4 and
// hands over M4A on stop; w.__deny = the next getUserMedia is refused like a blocked microphone
function fakeMic(w) {
  w.__stops = 0; w.__plays = 0; w.__deny = false;
  Object.defineProperty(w.navigator, 'mediaDevices', {configurable: true, value: {getUserMedia: async () => {
    if (w.__deny) { const e = new Error('blocked'); e.name = 'NotAllowedError'; throw e; }
    return {getTracks: () => [{stop() { w.__stops++; }}]};
  }}});
  w.MediaRecorder = class {
    constructor(stream, o) { this.stream = stream; this.mimeType = (o && o.mimeType) || 'audio/webm'; this.state = 'inactive'; }
    static isTypeSupported(t) { return t === 'audio/mp4'; }
    start() { this.state = 'recording'; }
    stop() {
      if (this.state === 'inactive') return; this.state = 'inactive';
      if (this.ondataavailable) this.ondataavailable({data: new Blob([M4A], {type: 'audio/mp4'})});
      setTimeout(() => this.onstop && this.onstop(), 0);
    }
  };
  w.HTMLMediaElement.prototype.play = function () { w.__plays++; Object.defineProperty(this, 'paused', {configurable: true, value: false}); this.dispatchEvent(new w.Event('play')); return Promise.resolve(); };
  w.HTMLMediaElement.prototype.pause = function () { Object.defineProperty(this, 'paused', {configurable: true, value: true}); this.dispatchEvent(new w.Event('pause')); };
  w.HTMLMediaElement.prototype.load = function () {};
  w.URL.createObjectURL = () => 'blob:fake'; w.URL.revokeObjectURL = () => {};
}

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  const st0 = await call('GET', '/api/state'), feats = new Set(((st0.settings || {}).features || '').split(',').filter(Boolean)); feats.add('collab');
  const FEAT = [...feats].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const L = (await call('POST', '/api/lists', {name: 'Team', org_id: ORG})).id;  // alice and bob work together (direct messages)
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const CH = (await call('POST', '/api/team/channels', {name: 'Studio', org_id: ORG, members: [BOB]})).id;
  check(CH > 0, 'a channel to start with');
  await call('POST', `/api/team/rooms/${CH}/messages`, {body: 'Hello'}, BCK);

  // ================= record, send, play (phone width)
  {
    const w = await boot({user: 'alice', mobile: true, hash: 'team/' + CH, setup: fakeMic}), d = w.document;
    await until(() => d.querySelector('#tc-in'));
    const mic = await until(() => d.querySelector('.tccomp [data-act="tvc-rec"]'));
    const clip = d.querySelector('.tccomp [data-act="tc-attach"]');
    check(mic && clip && clip.parentElement === mic.parentElement && mic.previousElementSibling?.id === 'tc-file' && !mic.classList.contains('hidden') && mic.getAttribute('aria-label') === 'Record a voice message'
      && mic.querySelector('svg'), 'composer: the microphone (app icon) next to the paperclip');
    const ta = d.querySelector('#tc-in');
    ta.value = 'typing'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(mic.classList.contains('hidden'), 'composer: no microphone while text is typed');
    ta.value = ''; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(!mic.classList.contains('hidden'), 'composer: the microphone is back when the box is empty');
    // tap = recording
    click(w, mic);
    const bar = await until(() => d.querySelector('.tccomp .tvcrec.on'));
    check(bar && bar.querySelector('.tvcdot') && bar.querySelector('[data-act="tvc-discard"]') && bar.querySelector('[data-act="tvc-send"]')
      && bar.querySelector('[data-act="tvc-stop"]') && /0:0\d/.test(bar.querySelector('.tvcclock')?.textContent || ''), 'recording: the bar with dot, time, discard, stop, send');
    w.eval('TVC.st.t0 -= 3200'); await sleep(400);
    check(/^0:0[34]$/.test(d.querySelector('.tvcrec .tvcclock')?.textContent || ''), 'recording: the time runs ' + d.querySelector('.tvcrec .tvcclock')?.textContent);
    // discard: nothing sent, the microphone released
    const n0 = (await call('GET', `/api/team/rooms/${CH}/messages`)).messages.length;
    click(w, d.querySelector('.tvcrec [data-act="tvc-discard"]'));
    await sleep(200);
    check(!d.querySelector('.tvcrec') && w.__stops === 1 && !w.eval('TVC.st'), 'discard: the bar goes, the microphone is released');
    check((await call('GET', `/api/team/rooms/${CH}/messages`)).messages.length === n0, 'discard: nothing was sent');
    // record again, stop = listen first, then send
    click(w, d.querySelector('.tccomp [data-act="tvc-rec"]'));
    await until(() => d.querySelector('.tvcrec.on'));
    w.eval('TVC.st.t0 -= 4500');
    click(w, d.querySelector('.tvcrec [data-act="tvc-stop"]'));
    const rv = await until(() => d.querySelector('.tvcrec:not(.on) [data-act="tvc-preview"]'));
    check(rv && /^0:0[45]$/.test(d.querySelector('.tvcrec .tvcclock')?.textContent || '') && w.__stops === 2, 'stop: listen first, the length shown, the microphone released');
    click(w, rv);
    check(w.__plays === 1 && w.eval('TVC.cur') === 'rec', 'stop: the preview plays');
    click(w, d.querySelector('.tvcrec [data-act="tvc-send"]'));
    const sent = await until(async () => (await call('GET', `/api/team/rooms/${CH}/messages`)).messages.find(x => x.attachments?.[0]?.voice));
    const a = sent?.attachments?.[0] || {};
    check(sent && a.mime === 'audio/mp4' && a.duration_ms >= 4400 && a.duration_ms <= 5600 && /^Voice-message-\d{8}-\d{4}\.m4a$/.test(a.name),
      'send: a voice message (m4a, length, name) ' + JSON.stringify(a).slice(0, 200));
    await until(() => !d.querySelector('.tvcrec'));
    check(!d.querySelector('.tvcrec') && !w.eval('TVC.st'), 'send: the bar is gone');
    // the player in the message
    const p = await until(() => d.querySelector(`#tc-msgs .tvcp[data-tvc="${a.id}"]`));
    check(p && p.classList.contains('voice') && p.querySelector('[data-act="tvc-play"]') && p.querySelector('input.tvcseek[type="range"]')
      && /^0:0[45]$/.test(p.querySelector('.tvct')?.textContent || '') && p.querySelector('[data-act="tvc-rate"]')?.textContent === '1×'
      && p.querySelector('a.tvcdl[download]')?.getAttribute('href').includes('dl=1'), 'player: play, position, length, speed, download ' + (p?.textContent || '').trim());
    click(w, p.querySelector('[data-act="tvc-play"]'));
    const p2 = () => d.querySelector(`#tc-msgs .tvcp[data-tvc="${a.id}"]`);
    check(w.__plays === 2 && w.eval('TVC.cur') === a.id && w.eval('TVC.audio.src').includes(`/api/team/files/${a.id}`) && p2().classList.contains('on')
      && p2().querySelector('[data-act="tvc-play"]').getAttribute('aria-label') === 'Pause', 'player: plays the file (the button says Pause)');
    click(w, p2().querySelector('[data-act="tvc-rate"]'));
    check(p2().querySelector('[data-act="tvc-rate"]').textContent === '1.5×' && w.eval('TVC.audio.playbackRate') === 1.5, 'player: 1.5×');
    click(w, p2().querySelector('[data-act="tvc-rate"]'));
    click(w, p2().querySelector('[data-act="tvc-rate"]'));
    check(p2().querySelector('[data-act="tvc-rate"]').textContent === '1×', 'player: 2× and back to 1×');
    click(w, p2().querySelector('[data-act="tvc-play"]'));
    check(!p2().classList.contains('on') && p2().querySelector('[data-act="tvc-play"]').getAttribute('aria-label') === 'Play', 'player: pause');
    // a blocked microphone
    w.__deny = true;
    click(w, d.querySelector('.tccomp [data-act="tvc-rec"]'));
    const t = await until(() => [...d.querySelectorAll('.toast, #toast, [role="status"]')].map(x => x.textContent).find(x => /microphone is blocked/.test(x)));
    check(!!t && !d.querySelector('.tvcrec'), 'blocked microphone: a clear note with the way out ' + (t || ''));
    check(!errs.length, `record: no JS errors ${errs.join(' | ')}`);
    await sleep(300); w.close();
  }

  // ================= bob gets the player; voice.js loads on demand
  {
    const w = await boot({user: 'bob', mobile: true, hash: 'team/' + CH, setup: fakeMic, lazy: true}), d = w.document;
    const p = await until(() => d.querySelector('#tc-msgs .tvcp.voice'), 60);
    check(!!p && !!d.querySelector('.tccomp [data-act="tvc-rec"]'), 'lazy: voice.js loaded on demand, player + microphone drawn');
    check(!errs.length, `lazy: no JS errors ${errs.join(' | ')}`);
    await sleep(300); w.close();
  }

  // ================= no microphone in an end-to-end encrypted DM; none without MediaRecorder
  {
    const rnd = n => Buffer.from(Array.from({length: n}, () => Math.floor(Math.random() * 256))).toString('base64');
    const rndu = n => rnd(n).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    const keys = () => ({pub: {kty: 'EC', crv: 'P-256', x: rndu(32), y: rndu(32), ext: true, key_ops: []},
      bundle_pass: {v: 1, kdf: 'pbkdf2-sha256', iter: 600000, salt: rnd(16), iv: rnd(12), ct: rnd(200)},
      bundle_rec: {v: 1, kdf: 'hkdf-sha256', salt: rnd(16), iv: rnd(12), ct: rnd(200)}});
    await call('PUT', '/api/e2e/keys', keys()); await call('PUT', '/api/e2e/keys', keys(), BCK);
    const DM = (await call('POST', '/api/team/dm', {user_id: BOB})).id;
    const e = await call('POST', `/api/team/rooms/${DM}/e2e`, {on: true});
    check(e.status === 200, 'e2e: the DM is encrypted ' + e.status);
    const w = await boot({user: 'alice', mobile: true, hash: 'team/' + DM, setup: fakeMic}), d = w.document;
    await until(() => d.querySelector('.tccomp'));
    await sleep(300);
    check(d.querySelector('.tccomp') && !d.querySelector('.tccomp [data-act="tvc-rec"]') && !d.querySelector('.tccomp [data-act="tc-attach"]'), 'e2e: no microphone (and no paperclip)');
    w.close();
    const w2 = await boot({user: 'alice', mobile: true, hash: 'team/' + CH}), d2 = w2.document;  // jsdom has no MediaRecorder
    await until(() => d2.querySelector('.tccomp [data-act="tc-attach"]'));
    check(!d2.querySelector('.tccomp [data-act="tvc-rec"]') && d2.querySelector('#tc-msgs .tvcp'), 'no MediaRecorder: no microphone, the player still shows');
    check(!errs.length, `e2e: no JS errors ${errs.join(' | ')}`);
    await sleep(300); w2.close();
  }

  console.log(`p2139_b_ui: ${ok} ok, ${F.length} failed`);
  execFileSync('docker', ['rm', '-f', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test'], {stdio: 'ignore'});
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
