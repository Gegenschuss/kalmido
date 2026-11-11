// kalmido-suite: fresh
// 2.932.0 (#5603) UI tests: the panel of Files has the row grid of the panel of Projects (Firefox, real layout).
// Own container (start.sh), Firefox only (the sizes need a real layout). Invented names and files only.
// - the group heads Sender / Archive number / a custom field sit in a .sgroup like Projects' heads (Views, Projects, Tags ...):
//   the same height, font size, left edge and the same gap above as there
// - the rows (Files, the tree, All documents, To review, a group's values) are as high as Projects' rows and use the same font
// - "Shared with me" / the trash stand on the left edge of Files / All documents, not stepped in like a sub folder
// - the same in the comfortable density, and on a phone (the drawer) the rows are at least as high as Projects' rows there
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p5603_ui', check, shots: 'P5603_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P5603_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const up = async (ck, name, text) => {
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json().catch(() => ({}));
};

// the panel's rows as the page lays them out: kind (head / row), text, box, font size, left edge of the label
const MEASURE = `(() => {
  const side = document.querySelector('#side'), sr = side.getBoundingClientRect();
  const out = [];
  for (const el of side.querySelectorAll('.shead.sgh, .srow, .fhead.sbbt')) {
    const r = el.getBoundingClientRect(); if (!r.height || r.bottom < sr.top) continue;
    const head = el.matches('.shead');
    const lab = head ? el.querySelector('.sgt > span:not(.c)') : el.querySelector('.n') || el;
    const sym = head ? null : el.querySelector('svg');
    const lr = lab.getBoundingClientRect();
    // the gap above: a head's distance to the element before its group (or the head before), a row's own top
    const grp = head ? el.parentElement : null, prev = grp?.previousElementSibling;
    out.push({k: head ? 'h' : 'r', t: (lab.textContent || '').trim().slice(0, 24), top: Math.round(r.top), h: Math.round(r.height),
      fs: parseFloat(getComputedStyle(lab).fontSize), x: Math.round(lr.left - sr.left), sx: sym ? Math.round(sym.getBoundingClientRect().left - sr.left) : null,
      gap: prev ? Math.round(r.top - prev.getBoundingClientRect().bottom) : null,
      cls: el.className.replace(/\\s+/g, ' ').trim(), grp: grp ? grp.className : ''});
  }
  return JSON.stringify(out);
})()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  // Projects: two projects with tagged tasks (the groups Projects and Tags)
  for (const n of ['Garden shed', 'Boat repair']) {
    const L = (await call(CA, 'POST', '/api/lists', {name: n, kind: 'project'})).id;
    await call(CA, 'POST', '/api/tasks', {list_id: L, title: 'Paint ' + n, tags: ['blue', 'green']});
  }
  // Files: three documents with senders, an archive number and a custom field
  const ids = [];
  for (let i = 1; i <= 3; i++) ids.push(((await up(CA, `heron-${i}.txt`, `Invented heron letter number ${i}`)).ids || [])[0]);
  check(ids.every(Boolean), 'setup: 3 documents');
  check(await until(async () => { for (const id of ids) { const s = (await call(CA, 'GET', `/api/docs/${id}`)).state; if (!['done', 'failed'].includes(s)) return false; } return true; }, 400), 'setup: recognised');
  const fr = await call(CA, 'POST', '/api/docs/fields', {ws: 'private', name: 'Stage', type: 'select', options: [{name: 'Draft'}, {name: 'Final'}]});
  const stage = (fr.fields || []).find(x => x.name === 'Stage'), opt = Object.fromEntries((stage?.options || []).map(o => [o.name, o.id]));
  for (let i = 0; i < 3; i++) await call(CA, 'PATCH', `/api/docs/${ids[i]}`, {sender: i ? 'Heron Post' : 'Owl Bank', asn: 140 + i, custom_fields: {[stage.id]: i ? opt.Draft : opt.Final}});

  // one look: Projects' panel and Files' panel in the same viewport and density
  const look = async (o, label, density, width, touch) => {
    const {cmd, ev, ctx, shot} = o;
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.density', '"${density}"'); localStorage.setItem('tasks.abFacOpen', '["sender"]'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height: 1000}});
    const openSide = async () => { if (width < 768) { await wait(`!!document.querySelector('#top .menu')`, 20); await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`); check(await wait(`!!document.querySelector('#side.open')`, 20), `${label}: the drawer opens`); } };
    // the density as the person picks it (Settings > Appearance): stored per device, applied at once
    const dens = async () => { await wait(`typeof applyDensity === 'function' && !!document.querySelector('#side')`, 40); await ev(`(() => { LS.set('density', '${density}'); applyDensity(); return document.documentElement.dataset.density; })()`); };
    await o.nav(B + '#all');
    await dens();
    await openSide();
    check(await wait(`[...document.querySelectorAll('#side .shead.sgh')].length >= 2`), `${label}: Projects' panel with its groups`);
    await sleep(400);
    const P = JSON.parse(await ev(MEASURE));
    await shot(`p5603-${label}-projects.png`);
    await o.nav(B + '#ablage/docs');
    await dens();
    await openSide();
    check(await wait(`!!document.querySelector('#side [data-dfc="sender"]') && !!document.querySelector('#side [data-dfcfold="asn"]')`), `${label}: Files' panel with the groups below the tree`);
    await sleep(400);
    const D = JSON.parse(await ev(MEASURE));
    await shot(`p5603-${label}-files.png`);
    console.log(`MEASURE ${label} projects`, JSON.stringify(P));
    console.log(`MEASURE ${label} files`, JSON.stringify(D));
    return {P, D};
  };

  await firefox(async o => {
    for (const [label, density, width] of [['1440', 'compact', 1440], ['1440-comfortable', 'comfortable', 1440]]) {
      const {P, D} = await look(o, label, density, width);
      const ph = P.filter(x => x.k === 'h'), dh = D.filter(x => x.k === 'h');
      const pr = P.filter(x => x.k === 'r'), dr = D.filter(x => x.k === 'r');
      check(ph.length >= 2 && dh.length >= 3, `${label}: heads found (${ph.length} / ${dh.length})`);
      const same = (a, b, d = 1) => Math.abs(a - b) <= d;
      const h0 = ph[ph.length - 1];  // a closed or open head of Projects, e.g. Tags
      for (const h of dh) {
        check(same(h.h, h0.h) && h.fs === h0.fs && same(h.x, h0.x), `${label}: head "${h.t}" like Projects' "${h0.t}" (h ${h.h}/${h0.h}, font ${h.fs}/${h0.fs}, x ${h.x}/${h0.x})`);
        check(/\bsgroup\b/.test(h.grp), `${label}: head "${h.t}" sits in a .sgroup (${h.grp})`);
      }
      // the gap above a head: the same as between two of Projects' groups
      const pg = ph.map(x => x.gap).filter(x => x != null), dg = dh.map(x => x.gap).filter(x => x != null);
      check(pg.length && dg.length && dg.every(g => pg.some(p => same(g, p, 2))), `${label}: the gap above the heads like Projects (${JSON.stringify(dg)} vs ${JSON.stringify(pg)})`);
      // rows: one height and one font size, the same as Projects' rows
      const rh = Math.max(...pr.map(x => x.h)), rf = pr[0].fs;
      const off = dr.filter(x => !same(x.h, rh) || x.fs !== rf);
      check(pr.length && dr.length && !off.length, `${label}: every row of Files as high as Projects' (${rh} px, font ${rf}): ${JSON.stringify(off.map(x => [x.t, x.h, x.fs]))}`);
      // "Shared with me" / the trash on the left edge of Files and All documents
      const files = dr.find(x => /^Files$/.test(x.t)), all = dr.find(x => x.t === 'All documents');
      const rest = dr.filter(x => /^(Shared with me|Trash)$/.test(x.t));
      check(files && all && rest.length && rest.every(x => same(x.sx, files.sx) && same(x.sx, all.sx)), `${label}: Shared with me / Trash on the left edge (${JSON.stringify(rest.map(x => [x.t, x.sx]))}, Files ${files?.sx}, All documents ${all?.sx})`);
      // below the last filter group "Shared with me" starts with a group's gap (it is no value of that group)
      const lastH = dh[dh.length - 1], sh = rest.find(x => x.t === 'Shared with me');
      check(sh && lastH && same(sh.top - (lastH.top + lastH.h), Math.max(...pg), 2), `${label}: a group's gap above Shared with me (${sh && lastH ? sh.top - lastH.top - lastH.h : '?'} vs ${Math.max(...pg)})`);
      // a group's values: in the grid of Projects' rows below a head (the same symbol edge as a project below "Lists")
      const val = dr.find(x => x.t === 'Owl Bank'), proj = pr.find(x => x.t === 'Garden shed');
      check(val && proj && same(val.sx, proj.sx) && same(val.h, proj.h), `${label}: a group's values in the grid of Projects' rows (${val?.sx}/${proj?.sx})`);
      check(label !== '1440-comfortable' || rh >= 34, `${label}: the comfortable density is applied (rows ${rh} px)`);
    }
  });

  // a phone: the drawer (touch) - the rows at least as high as Projects' rows there
  await firefox(async o => {
    const {P, D} = await look(o, '390', 'compact', 390, true);
    const pr = P.filter(x => x.k === 'r'), dr = D.filter(x => x.k === 'r'), dh = D.filter(x => x.k === 'h'), ph = P.filter(x => x.k === 'h');
    const rh = Math.min(...pr.map(x => x.h));
    check(pr.length && dr.length && dr.every(x => x.h >= rh - 1), `390: every row of Files at least as high as Projects' (${rh}): ${JSON.stringify(dr.filter(x => x.h < rh - 1).map(x => [x.t, x.h]))}`);
    check(ph.length && dh.length && dh.every(x => x.h >= Math.min(...ph.map(y => y.h)) - 1), `390: the heads at least as high as Projects' heads`);
  }, true);

  console.log(`p5603_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
