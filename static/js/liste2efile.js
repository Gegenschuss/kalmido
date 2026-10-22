/* Kalmido web client: files of lists with the lock, encrypted with the list key (2.64.2, #1817, stage 2). Classic script
   sharing the global scope (load order: index.html, after liste2eui.js). Server side kalmido/collab/liste2efile.py. */
'use strict';

// format (server kalmido/collab/liste2efile.py): "KENC" 0x02 | gen (u32 big endian) | iv (12) | AES-256-GCM with the list key of gen,
// AAD "kalmido-lfile:v1:<list>:<gen>", over u32 header length | header JSON {name, type, size} | the file bytes.
// The attachment row keeps the name as a list cipher (field "file_name"), so the list shows names without loading files.
const LE2F = {aid: new Map(), tried: new Set(), busy: false};
const LE2F_HEAD = 9, LE2F_MAX = 50 * 1024 * 1024;
const le2fAad = (lid, g) => `kalmido-lfile:v1:${lid}:${g}`;
const le2fBusy = () => le2eErr(tr('This project is being encrypted. Try again in a moment.'), 'list_e2e_busy');

// the list key of generation g (asks for the passphrase when the browser is still locked)
async function le2fKey(lid, g) {
  let k = LE2E.keys[lid]?.[g];
  if (!k && typeof e2eUnlocked === 'function' && !e2eUnlocked() && typeof e2eEnsure === 'function' && !await e2eEnsure()) throw le2eErrLocked();
  if (!k) k = (await le2eKeys(lid))[g] || (await le2eKeys(lid, true))[g];
  if (!k) throw le2eErr(tr('You do not have the key of this project yet.'), 'list_e2e_key');
  return k;
}
// {name, type, data: Uint8Array} (or a File) -> the encrypted bytes of generation gen (default: the list's current one)
async function le2eFileEnc(lid, file, gen) {
  const g = gen || listById(lid)?.e2e_gen, key = await le2fKey(lid, g);
  const data = file.data || new Uint8Array(await file.arrayBuffer());
  const head = e2eTEnc().encode(JSON.stringify({name: file.name || 'file', type: file.type || 'application/octet-stream', size: data.length}));
  const plain = new Uint8Array(4 + head.length + data.length);
  new DataView(plain.buffer).setUint32(0, head.length); plain.set(head, 4); plain.set(data, 4 + head.length);
  const iv = e2eRand(12), ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: e2eTEnc().encode(le2fAad(lid, g))}, key, plain));
  const out = new Uint8Array(LE2F_HEAD + 12 + ct.length);
  out.set([0x4b, 0x45, 0x4e, 0x43, 0x02]); new DataView(out.buffer).setUint32(5, g); out.set(iv, LE2F_HEAD); out.set(ct, LE2F_HEAD + 12);
  return out;
}
// encrypted bytes -> {name, type, size, data, gen}; throws when the format or the key does not fit
async function le2eFileDec(lid, buf) {
  const u = new Uint8Array(buf);
  if (u.length < LE2F_HEAD + 12 + 16 || String.fromCharCode(...u.subarray(0, 4)) !== 'KENC' || u[4] !== 2) throw new Error('format');
  const g = new DataView(u.buffer, u.byteOffset).getUint32(5), key = await le2fKey(lid, g);
  const plain = new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv: u.subarray(LE2F_HEAD, LE2F_HEAD + 12), additionalData: e2eTEnc().encode(le2fAad(lid, g))}, key, u.subarray(LE2F_HEAD + 12)));
  const n = new DataView(plain.buffer).getUint32(0), head = JSON.parse(e2eTDec().decode(plain.subarray(4, 4 + n)));
  const data = plain.subarray(4 + n);
  return {name: String(head.name || 'file'), type: String(head.type || 'application/octet-stream'), size: data.length, data, gen: g};
}
const le2fBlob = u => new Blob([u], {type: 'application/octet-stream'});
// files -> [{blob, name}] for a list with the lock (null: the list is open). The names are list ciphers of the same generation.
async function le2eFileParts(lid, files) {
  if (!le2eOn(lid)) return null;
  if (le2eMode(lid) !== 'on') throw le2fBusy();
  const big = files.find(f => f.size > LE2F_MAX);
  if (big) throw le2eErr(tr('{0} is larger than 50 MB', big.name), 'size');
  const out = [];
  for (const [i, f] of files.entries()) {
    const name = f.name || `${tr('Image')}-${Date.now()}-${i}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`;
    out.push({blob: le2fBlob(await le2eFileEnc(lid, {name, type: f.type, data: new Uint8Array(await f.arrayBuffer())})), name: await le2eFileNameEnc(lid, name)});
  }
  return out;
}
const le2eFileNameEnc = (lid, name) => le2eEnc(lid, 'file_name', String(name || 'file').slice(0, 150), true);
// upload into a task of a list with the lock (commentId: files of an existing comment of mine). quiet: no render / toast, -> the task
async function le2eFileUpload(tid, files, commentId, quiet) {
  files = noEmpty(files); if (!files.length) return null;
  const t = taskById(tid), lid = t?.list_id;
  let parts;
  try {
    if (!quiet) toast(tr('Encrypting…'));
    parts = await le2eFileParts(lid, files);
  } catch (x) { if (quiet) throw x; toast(x.message); return null; }
  if (!parts) return null;
  const fd = new FormData();
  for (const p of parts) { fd.append('file', p.blob, 'encrypted.kenc'); fd.append('name', p.name); }
  if (commentId) fd.append('comment_id', commentId);
  let r;
  try { r = await rawFetch('POST', `/api/tasks/${tid}/list-attachments`, fd); }
  catch (x) { if (quiet) throw x; if (!x.shown) toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); return null; }
  if (quiet) return r;
  putTask(r); render(); if (S.sel === tid) renderDetail();
  toast(files.length === 1 ? tr('Encrypted and attached') : tr('{0} files encrypted and attached', files.length));
  return r;
}

// ------------------------------------------------------------------ names and tiles
// the plain name of a list file known on this page, else '' (decrypted in the background; the tiles are filled in then)
function le2eFileName(a, lid) {
  const c = le2eIs(a?.name) ? a.name : a?._enc?.name;  // the data layer keeps the cipher in _enc (name '' until opened)
  if (!le2eIs(c)) return a?.name || '';
  const s = LE2E.memo.get(c); if (s != null) return s;
  LE2F.aid.set(a.id, [lid, c]); le2fFill();
  return '';
}
let le2fT = null;
function le2fFill() {
  if (le2fT) return;
  le2fT = setTimeout(async () => {
    le2fT = null;
    for (const [aid, [lid, c]] of [...LE2F.aid]) {
      if (LE2F.tried.has(c) || !le2eOn(lid) || (typeof e2eUnlocked === 'function' && !e2eUnlocked())) continue;
      LE2F.tried.add(c);
      let s; try { s = await le2eDec(lid, 'file_name', c); } catch { continue; }
      LE2F.aid.delete(aid);
      $$(`.le2fatt[data-att="${aid}"] .an`).forEach(el => { el.textContent = s; });
      $$(`.le2fatt[data-att="${aid}"] .attx`).forEach(el => { el.title = s; });
    }
  }, 0);
}
document.addEventListener('le2e:change', () => { LE2F.tried.clear(); le2fFill(); });
function le2eFileHtml(a, del, lid) {
  const nm = le2eFileName(a, lid);
  return `<div class="att file e2eatt le2fatt" data-att="${a.id}"><button type="button" class="attx" data-le2f="open" data-att="${a.id}" data-lid="${lid}" title="${esc(nm || tr('Decrypt and download'))}">${ic('lock')}<span class="atxt"><span class="an">${esc(nm || tr('Encrypted file'))}</span><span class="as">${esc(fmtSize(a.size || 0))}</span></span></button>${del}</div>`;
}
async function le2fFetch(aid) {
  let r;
  try { r = await fetch(`/api/attachments/${aid}?dl=1`, {headers: {'X-Requested-With': 'kalmido'}}); } catch { throw new Offline('net'); }
  if (!r.ok) throw le2eErr(tr('File damaged or missing'), 'file');
  return r;
}
// open a list file: decrypt it here; an image in the viewer, everything else as a download
async function le2eFileOpen(aid, lid) {
  let f;
  try { f = await le2eFileDec(lid, await (await le2fFetch(aid)).arrayBuffer()); }
  catch (x) { toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.code === 'file' || x.code === 'list_e2e_key' || x.code === 'list_e2e_locked' ? x.message : tr('Cannot be decrypted')); return; }
  const url = URL.createObjectURL(new Blob([f.data], {type: f.type})), a = {id: aid, name: f.name, size: f.size, mime: f.type};
  if (isImg(a) && typeof attLightbox === 'function') { attLightbox(aid, [a], () => url); setTimeout(() => URL.revokeObjectURL(url), 600000); return; }
  const el = document.createElement('a');
  el.href = url; el.download = f.name; document.body.appendChild(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-le2f="open"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  le2eFileOpen(+b.dataset.att, +b.dataset.lid);
});

// ------------------------------------------------------------------ conversion (part A's switch: on, key change, way back)
// row = {id, task_id, comment_id, enc, gen, size, name, mime} of /e2e/todo "files"; mode = 'encrypting' | 'on' | 'decrypting'.
// Loads the file, decrypts (list file / my per-person file of 2.42) or takes it as it is (plain), encrypts it with the list's
// current generation (or stores it plain on the way back) and uploads it into the same attachment row. -> the server's answer
async function le2eFileConvert(lid, row, mode) {
  const r = await le2fFetch(row.id), buf = await r.arrayBuffer();
  let f;
  if (row.enc === 2) f = await le2eFileDec(lid, buf);
  else if (row.enc === 1) f = await e2eFileDecrypt(buf, row.task_id);
  else {
    const cd = r.headers.get('content-disposition') || '', m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
    f = {name: row.name || (m ? decodeURIComponent(m[1]) : 'file'), type: row.mime || 'application/octet-stream', data: new Uint8Array(buf)};
  }
  const fd = new FormData();
  if (mode === 'decrypting') {
    fd.append('file', new Blob([f.data], {type: 'application/octet-stream'}), 'file'); fd.append('name', f.name); fd.append('type', f.type);
  } else {
    if (row.enc !== 2 && le2eIs(f.name)) throw new Error('name');  // never a cipher as a plain name
    fd.append('file', le2fBlob(await le2eFileEnc(lid, f)), 'encrypted.kenc'); fd.append('name', await le2eFileNameEnc(lid, f.name));
  }
  try { return await rawFetch('POST', `/api/lists/${lid}/e2e/files/${row.id}`, fd); }
  catch (x) { if (x.status === 409 && !x.data?.code) return {ok: true, id: row.id, skipped: true}; throw x; }  // done meanwhile
}
