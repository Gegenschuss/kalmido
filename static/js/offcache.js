// @ts-check
/* Kalmido web client: the offline start state in IndexedDB (2.663.0, #4200), loaded on demand (lazyload.js) by core.js startSave /
   startRead. The last full state (S.lpCache: all tasks of the last load, the delta keeps it current) was a JSON string in
   localStorage: written on the main thread after every load, with a replacer per key while lists are locked, and over the
   quota of about 5 million characters the error was swallowed and an offline start showed an old state. Now:
   - one record in the database "kalmido-start" (store "s", key "state"), written when the browser is idle
     (requestIdleCallback, setTimeout where there is none); the newest state at the time of writing goes, never a queue of them
   - a structured clone of the state ({o}) while no list is locked; with locked lists the JSON of LS.set with le2eRepl ({s}):
     only ciphers leave the memory, as before (liste2e.js H1). A state the browser cannot clone goes as that JSON too.
   - the old localStorage copy "tasks.cache" is taken over once (read first, written here, then removed); after any write
     here that did not work (no IndexedDB, private mode, quota) the state goes to localStorage as before and the reason is
     logged (console.warn, the client error report), never swallowed. Rule: a localStorage copy that exists is the newest
     (every good write here removes it, every write there comes after a failed one here), so startRead takes it first.
   Classic script sharing the global scope with the others. */
'use strict';

const OC_DB = 'kalmido-start', OC_KEY = 'state';
/** @type {{dbp: Promise<IDBDatabase> | null, t: number, off: boolean, warned: boolean, wrote: number, gen: number}} */
const OC = {dbp: null, t: 0, off: false, warned: false, wrote: 0, gen: 0};  // gen: counted up by oc_drop, a write planned before it is void
function oc_req(r) { return new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); }); }
function oc_db() {
  if (OC.dbp) return OC.dbp;
  if (!globalThis.indexedDB) return Promise.reject(new Error('no IndexedDB'));
  OC.dbp = new Promise((ok, no) => {
    const r = indexedDB.open(OC_DB, 1);
    r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains('s')) r.result.createObjectStore('s'); };
    r.onsuccess = () => { const d = r.result; d.onversionchange = () => { d.close(); OC.dbp = null; }; ok(d); };  // another tab deletes it (sign-out): let it
    r.onerror = () => no(r.error); r.onblocked = () => no(new Error('blocked'));
  });
  OC.dbp.catch(() => { OC.dbp = null; });
  return OC.dbp;
}
async function oc_tx(mode, fn) {
  const t = (await oc_db()).transaction('s', mode), out = fn(t.objectStore('s'));
  await new Promise((ok, no) => { t.oncomplete = ok; t.onerror = t.onabort = () => no(t.error || new Error('aborted')); });
  return out instanceof IDBRequest ? out.result : out;
}
function oc_warn(what, e) {
  const m = `Kalmido: offline start state (${what}): ${e?.name || ''} ${e?.message || e}`.trim();
  console.warn(m);
  if (!OC.warned) { OC.warned = true; try { window.dispatchEvent(new ErrorEvent('error', {message: m, error: e instanceof Error ? e : new Error(m)})); } catch { /* old browser */ } }  // clienterr.js reports it once per page
}
// the record of the state c: a structured clone where it may be (no locked list), else the JSON of LS.set
/** @returns {{s?: string, o?: any, at: number}} */
function oc_rec(c) {
  const repl = typeof le2eRepl === 'function' ? le2eRepl() : undefined;
  return repl ? {s: JSON.stringify(c, repl), at: Date.now()} : {o: c, at: Date.now()};
}
async function oc_put(c) {
  let rec = oc_rec(c);
  try { await oc_tx('readwrite', st => st.put(rec, OC_KEY)); }
  catch (e) {
    if (e?.name !== 'DataCloneError' || rec.s !== undefined) throw e;
    rec = {s: JSON.stringify(c), at: rec.at};  // a value the browser cannot clone (a function, a node): the JSON as before
    await oc_tx('readwrite', st => st.put(rec, OC_KEY));
  }
}
// the write itself (idle): the newest S.lpCache; refused -> localStorage as before (LS.set), the reason logged
async function oc_write(gen = OC.gen) {
  OC.t = 0;
  const c = S.lpCache; if (!c || gen !== OC.gen) return;
  if (!OC.off) {
    try {
      await oc_db();
      if (S.lpCache !== c || gen !== OC.gen) return;  // dropped (sign-out, another sign-in) or replaced meanwhile: that one has its own write
      await oc_put(c);
      OC.wrote++;
      try { localStorage.removeItem('tasks.cache'); } catch { /* private mode */ }  // the old copy (taken over) goes
      return;
    } catch (e) { OC.off = true; oc_warn('IndexedDB refused, localStorage from now on', e); oc_del().catch(() => {}); }
  }
  try { localStorage.setItem('tasks.cache', JSON.stringify(c, typeof le2eRepl === 'function' ? le2eRepl() : undefined)); }
  catch (e) { oc_warn('localStorage refused too, the offline start shows an older state', e); }
}
// core.js startSave: a write when the browser is idle (one at a time; it takes the newest state when it runs)
function oc_soon() {
  if (OC.t) return;
  OC.t = 1;
  const g = OC.gen;
  if (typeof requestIdleCallback === 'function') requestIdleCallback(() => { if (g === OC.gen) oc_write(g); }, {timeout: 10000});
  else setTimeout(() => { if (g === OC.gen) oc_write(g); }, 300);
}
// core.js startRead: the old / fallback localStorage copy first (it is the newest, see above; then moved here), else the record
async function oc_get() {
  let raw = null;
  try { raw = localStorage.getItem('tasks.cache'); } catch { /* private mode */ }
  if (raw) {
    let c = null; try { c = JSON.parse(raw); } catch { /* broken: the record below */ }
    if (c) {
      if (!OC.off) oc_tx('readwrite', st => st.put({s: raw, at: Date.now()}, OC_KEY))
        .then(() => { try { if (localStorage.getItem('tasks.cache') === raw) localStorage.removeItem('tasks.cache'); } catch { /* private mode */ } })
        .catch(e => oc_warn('taking over the old copy', e));
      return c;
    }
  }
  let rec;
  try { rec = await oc_tx('readonly', st => st.get(OC_KEY)); } catch (e) { oc_warn('reading', e); return null; }
  if (!rec) return null;
  if (rec.o) return rec.o;
  try { return JSON.parse(rec.s); } catch { return null; }
}
// core.js startDrop / icons.js clearLocal: the record goes (the connection stays open: a clear, not a deleteDatabase)
function oc_del() { return oc_tx('readwrite', st => st.delete(OC_KEY)); }
function oc_drop() { OC.t = 0; OC.gen++; return oc_del().catch(() => {}); }
