/* Kalmido web client: the list channel of a list with the lock (2.64.2, #1817, stage 2). Classic script sharing the global
   scope (load order: index.html, after liste2efile.js). Server side kalmido/collab/liste2echan.py. */
'use strict';

// A message of a list channel with the lock: tchat_msgs.enc = {v: 1|2, g, iv, ct}, AES-256-GCM with the list key of generation g,
// AAD "kalmido-chan:v1:<room>:<gen>:<sender>" (v 1) or, since 2.640.0 (#3388), "kalmido-chan:v2:<room>:<gen>:<sender>:<message id>"
// (v 2: a cipher the server put under another message does not open there), padded like the list texts (le2ePad).
// Written is always v 2: a new message under an id the server reserved first (le2eChanEnc, le2eChanPost); read by the version
// in the cipher - v 1 only for a cipher that says v 1 (a v 2 cipher relabelled as v 1 does not open under the v 1 AAD). The plain text holds the mention tokens
// (<@id>) like a plain message; the browser names the mentioned members to the server (mentions) so their push still comes.
// Decrypted texts live in E2E.dec (this session only, like the DMs of 2.42); nothing decrypted goes to localStorage (H1).
const le2eChanAad = (rid, g, sender, mid, v) => v === 2 ? `kalmido-chan:v2:${rid}:${g}:${sender}:${mid}` : `kalmido-chan:v1:${rid}:${g}:${sender}`;
// one message's cipher opened with the AAD of its version (m: {id, user_id, enc})
const le2eChanOpenWith = async (key, rid, m) => e2eTDec().decode(le2eUnpad(await e2eOpen(key, {v: 1, iv: m.enc.iv, ct: m.enc.ct}, le2eChanAad(rid, m.enc.g, m.user_id, m.id, m.enc.v === 2 ? 2 : 1))));
// the room is the channel of a list with the lock (the list in the state, else what the room answer said)
function le2eChanOn(room) {
  if (!room || room.kind !== 'list' || !room.list_id) return false;
  const l = typeof listById === 'function' ? listById(room.list_id) : null;
  return !!(l ? l.e2e : room.list_e2e);
}
async function le2eChanKey(lid, g) {
  let ks = LE2E.keys[lid] || {};
  if (!ks[g]) ks = await le2eKeys(lid, true);
  return ks[g] || null;
}
// text (with <@id> tokens) -> {v: 2, g, iv, ct} with the current generation; throws a clear error while the list is locked here.
// mid = the message (an edit); without it a new message: its id is reserved first and travels along in the (non-enumerable)
// fields mid / resv, which le2eChanPost sends next to the cipher (2.640.0, #3388)
async function le2eChanEnc(room, text, mid) {
  if (!await e2eEnsure()) return null;
  const lid = room.list_id, l = listById(lid), g = l?.e2e_gen || room.gen;
  if (l && l.e2e !== 'on') throw le2eErr(tr('This project is being encrypted. Try again in a moment.'), 'list_e2e_busy');
  const key = g && await le2eChanKey(lid, g);
  if (!key) throw le2eErr(tr('You do not have the key of this project yet.'), 'list_e2e_key');
  let resv = null;
  if (!mid) { const r = await rawFetch('POST', `/api/team/rooms/${room.id}/msgid`); mid = r.id; resv = r.resv; }
  const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(text)), le2eChanAad(room.id, g, S.me.id, mid, 2));
  const o = {v: 2, g, iv: b.iv, ct: b.ct};
  if (resv) Object.defineProperties(o, {mid: {value: mid}, resv: {value: resv}});
  return o;
}
// chat.js: the POST of a new message of a list channel with the lock - msg_id / resv of the cipher go along; when another
// message came in after the reservation (409 chan_resv_stale) the text is encrypted again with a new id (the room keeps its order)
const le2eChanPost = (room, text) => async (method, url, body) => {
  for (let i = 0; ; i++) {
    const enc = body.enc;
    try { return await rawFetch(method, url, enc?.resv ? {...body, msg_id: enc.mid, resv: enc.resv} : body); }
    catch (e) {
      if (e?.data?.code !== 'chan_resv_stale' || i >= 3) throw e;
      body = {...body, enc: await le2eChanEnc(room, text)};
    }
  }
};
// the ids of the members named in a text with tokens (tcMentions output)
const le2eChanMentions = text => [...String(text).matchAll(/<@(\d+)>/g)].map(x => +x[1]).filter((v, i, a) => a.indexOf(v) === i);
async function le2eChanOpen(room, m) {
  const g = m.enc?.g; if (!Number.isInteger(g)) throw new Error('enc');
  const key = await le2eChanKey(room.list_id, g);
  if (!key) return undefined;
  return le2eChanOpenWith(key, room.id, m);
}
// the messages of the open list channel: from this session's memory first, the rest decrypted (when unlocked)
async function le2eChanDecrypt(rid) {
  const room = S.tc.room; if (!room || room.id !== rid || !le2eChanOn(room)) return;
  const need = (S.tc.msgs || []).filter(m => m.enc && !m.enc.sys && !m._dec && !m.deleted);
  if (!need.length) { e2eQuotes(S.tc.msgs); return; }
  await e2eLoad();
  if (!e2eUnlocked()) { if (S.tc.rid === rid) tcPatch(); return; }
  for (const m of need) {
    try {
      const s = await le2eChanOpen(room, m);
      if (s === undefined) { m._nokey = true; continue; }
      m.body = s; m._dec = true; delete m._nokey; E2E.dec[m.id + ':' + (m.edited_at || '')] = s;
    } catch { m._fail = true; }
  }
  e2eQuotes(S.tc.msgs);
  if (S.tc.rid === rid) tcPatch();
}
// the body of a message in a list channel with the lock that is not decrypted (yet); null = show the text
function le2eChanMsgBody(m) {
  if (!m.enc || m.enc.sys || m._dec) return null;
  if (m._fail) return `<div class="cbub e2emsg"><span class="muted">${ic('lock', 's')} ${esc(tr('Cannot be decrypted'))}</span></div>`;
  if (m._nokey) return `<div class="cbub e2emsg"><span class="muted">${ic('lock', 's')} ${esc(tr('You do not have the key of this project yet.'))}</span></div>`;
  return `<div class="cbub e2emsg"><button type="button" class="linkbtn" data-le2c="unlock">${ic('lock', 's')} ${esc(tr('Encrypted – unlock'))}</button></div>`;
}
// the line under the head of a list channel with the lock (part D draws it: lock, safety numbers, key changes)
function le2eChanNotice(room) {
  if (!le2eChanOn(room)) return '';
  const l = listById(room.list_id);
  const busy = l && l.e2e !== 'on' ? `<div class="e2ehint">${ic('lock', 's')}<span>${esc(l.e2e === 'decrypting' ? tr('Being decrypted') : tr('Being encrypted'))}</span></div>` : '';
  return (typeof le2uChanHead === 'function' ? le2uChanHead(room) : '') + busy;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-le2c="unlock"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const room = S.tc.room; if (!room) return;
  if (typeof le2eUnlock === 'function') { try { await le2eUnlock(room.list_id); } catch (x) { if (x?.message) toast(x.message); } }
  (S.tc.msgs || []).forEach(m => { delete m._nokey; delete m._fail; });
  le2eChanDecrypt(room.id);
}, true);
// one message for the conversion of part A (switching on / off, re-encryption after a key change): {id, enc} or {id, body}
async function le2eChanConvert(lid, msg, mode) {
  const room = {id: msg.room_id, kind: 'list', list_id: lid};
  let text = msg.body || '';
  if (msg.enc) {
    const g = msg.enc.g, key = await le2eChanKey(lid, g);
    if (!key) throw le2eErr(tr('You do not have the key of this project yet.'), 'list_e2e_key');
    text = await le2eChanOpenWith(key, room.id, msg);
  }
  if (mode === 'decrypting') return {id: msg.id, body: text};
  const g = listById(lid)?.e2e_gen;  // the server's target generation is always the current one (le2c_bulk)
  const key = g && await le2eChanKey(lid, g);
  if (!key) throw le2eErr(tr('You do not have the key of this project yet.'), 'list_e2e_key');
  // the original sender stays in the AAD: re-encrypting by the owner / an admin does not make the message theirs;
  // 2.640.0 (#3388): written as v 2 with the message id (a key change lifts the v 1 messages)
  const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(text)), le2eChanAad(room.id, g, msg.user_id, msg.id, 2));
  return {id: msg.id, enc: {v: 2, g, iv: b.iv, ct: b.ct}};
}
