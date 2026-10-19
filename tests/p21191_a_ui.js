// 2.119.1 part A UI tests, own container (start.sh), Firefox. Invented people, example.com addresses only.
// #2081 the contacts list loads 500 at first and the next page while scrolling near its end ("Show more" too); "All" in the
// selection mode ticks every match, also those not loaded yet (and then offers "Select none").
// #2080 the More menu offers "Import a CSV file…" and the CSV export per address book; a CSV file opens the mapping step (the
// suggested field per column with an example, changeable), the import then runs with its progress panel.
// #2084 a new contact with the e-mail of one already there: a quiet note in the editor names it ("same e-mail"), Save turns
// into "Create anyway" (the second Save creates it), the name opens the one there; an import with a look-alike says
// "1 possible duplicate" and "Check" lists it with "Merge" (the merge view opens).
// #2085 "Manage groups…" (in the group filter): the groups with their counts, rename (one undo step: Ctrl+Z puts it back),
// delete (the contacts stay). A person without an organisation (her own admin, P4) is the main person here.
// P21191A_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21191_a_ui', check, shots: 'P21191A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21191A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients';
const card = (i, fn, extra = '') => `BEGIN:VCARD\r\nVERSION:3.0\r\nUID:ui${i}\r\nFN:${fn}\r\nN:${fn.split(' ')[1] || ''};${fn.split(' ')[0]};;;\r\n${extra}END:VCARD\r\n`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const bk = await call(CC, 'POST', '/api/books', {name: 'Office'});
  check(bk.id > 0, 'an address book of carol');
  // 650 contacts (#2081), two of them in the group "Customers", one with a known e-mail (#2084)
  let vcf = '';
  for (let i = 0; i < 650; i++) vcf += card(i, `Person${String(i).padStart(4, '0')} Many`, i < 2 ? 'CATEGORIES:Customers\r\n' : i === 2 ? 'EMAIL:known@example.com\r\n' : '');
  const fd = new FormData(); fd.append('file', new Blob([vcf], {type: 'text/vcard'}), 'many.vcf');
  const im = await (await fetch(B + `api/books/${bk.id}/import`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CC}, body: fd})).json();
  check(im.created === 650, '650 contacts imported ' + JSON.stringify(im));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const popText = ev => ev(`[...document.querySelectorAll('#pop:not(.hidden) button')].map(b => b.textContent.trim()).join('|')`);

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    await nav(B + '#contacts');
    check(await ready(ev, `typeof CT === 'object' && Array.isArray(CT.items) && CT.items.length > 0`, 80), 'the contacts view loads');
    // ================= #2081
    check(await ev(`CT.items.length === 500 && CT.total === 650`), '#2081: page one = 500 of 650 ' + await ev(`CT.items.length + '/' + CT.total`));
    check(await ev(`/500 of 650 loaded/.test(document.querySelector('#view .ctmore')?.textContent || '') && !!document.querySelector('#view .ctmore [data-ctxmore]')`), '#2081: "500 of 650 loaded" + Show more');
    // "All" in the selection mode: every match, also the 150 not loaded yet
    await click(ev, '#view [data-ct="pick"]');
    check(await ready(ev, `!!document.querySelector('#ct-sbar [data-ctb="all"]')`), '#2081: the selection bar');
    await click(ev, '#ct-sbar [data-ctb="all"]');
    check(await ready(ev, `CT.pick && CT.pick.size === 650`), '#2081: "All" ticks all 650 ' + await ev(`CT.pick?.size`));
    check(await ready(ev, `/Select none/.test(document.querySelector('#ct-sbar [data-ctb="all"]')?.textContent || '')`), '#2081: ... and then offers "Select none"');
    await click(ev, '#ct-sbar [data-ctb="all"]');
    check(await ready(ev, `CT.pick && CT.pick.size === 0`), '#2081: "Select none" clears it');
    await ev(`(bk_end(), 1)`);
    // scrolling near the end loads the next page
    await ev(`(() => { const w = document.querySelector('#view .ctlistw'), sc = w.scrollHeight > w.clientHeight + 1 ? w : document.querySelector('#view'); sc.scrollTop = sc.scrollHeight; sc.dispatchEvent(new Event('scroll')); return 1; })()`);
    check(await ready(ev, `CT.items.length === 650`, 60), '#2081: scrolling loads the rest ' + await ev(`CT.items.length`));
    check(await ready(ev, `!document.querySelector('#view .ctmore') && new Set(CT.items.map(c => c.id)).size === 650`), '#2081: no doubles, the note is gone');
    await ev(`(() => { const w = document.querySelector('#view .ctlistw'), sc = w.scrollHeight > w.clientHeight + 1 ? w : document.querySelector('#view'); sc.scrollTop = sc.scrollHeight; sc.dispatchEvent(new Event('scroll')); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view [data-ctopen="' + CT.items[649].id + '"]')`), '#2081: the last contact is drawn at the end of the list');
    await shot('p21191a-list-650.png');
    // a new search starts at page one; the "Show more" button loads the next page too
    await ev(`(() => { const i = document.querySelector('#ct-q'); i.value = 'Many'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `CT.q === 'Many' && !CT.loading && CT.items.length === 500`, 40), '#2081: a new search loads page one again');
    await click(ev, '#view [data-ctxmore]');
    check(await ready(ev, `CT.items.length === 650`, 40), '#2081: "Show more" loads the next page');
    await ev(`(() => { const i = document.querySelector('#ct-q'); i.value = ''; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ready(ev, `CT.q === '' && !CT.loading`);

    // ================= #2080
    await click(ev, '#view [data-ct="menu"]');
    await ready(ev, `!document.querySelector('#pop').classList.contains('hidden')`);
    const mt = await popText(ev);
    check(/Import a vCard file…/.test(mt) && /Import a CSV file…/.test(mt) && /Export Office \(vCard\)/.test(mt) && /Export Office \(CSV\)/.test(mt) && /Manage groups…/.test(mt), '#2080: the menu offers CSV import + export ' + mt);
    await ev(`(closePop(), 1)`);
    await ev(`(ctx_csvMap(${bk.id}, new File(['Vorname;Nachname;E-Mail-Adresse;Mobiltelefon;Lieblingsfarbe\\r\\nUla;Csvtest;ula@example.com;0170 111222;Blau\\r\\nKnown;Twin;known@example.com;;Rot\\r\\n'], 'ui.csv', {type: 'text/csv'})), 1)`);
    check(await ready(ev, `document.querySelectorAll('.modal .ctxmap select').length === 5`), '#2080: the mapping step with a field per column');
    const guess = await ev(`[...document.querySelectorAll('.modal .ctxmap select')].map(s => s.value).join(',')`);
    check(guess === 'given,family,email:home,phone:cell,', '#2080: the suggested fields (the unknown column: not imported) ' + guess);
    check(await ev(`(document.querySelector('.modal .ctxmap label[for="ctx-c0"] small')?.textContent || '') === 'Ula'`), '#2080: an example under the column name');
    check(await ev(`/Import 2 contacts/.test(document.querySelector('.modal [data-ctx="go"]').textContent)`), '#2080: "Import 2 contacts"');
    await shot('p21191a-csv-map.png');
    await ev(`(() => { const s = document.querySelector('.modal #ctx-c4'); s.value = 'note'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await click(ev, '.modal [data-ctx="go"]');
    check(await ready(ev, `/Imported: 2 new/.test(document.querySelector('#ctimp .ctimp-t')?.textContent || '')`, 60), '#2080: the import runs and says what it did ' + await ev(`document.querySelector('#ctimp')?.textContent || ''`));
    const ula = (await call(CC, 'GET', '/api/contacts?q=Csvtest')).items || [];
    const u1 = ula[0] ? await call(CC, 'GET', `/api/contacts/${ula[0].id}`) : {};
    check(u1.fn === 'Ula Csvtest' && u1.emails?.[0]?.value === 'ula@example.com' && u1.phones?.[0]?.type?.[0] === 'cell' && u1.note === 'Blau', '#2080: the fields as mapped (the changed column into the note) ' + JSON.stringify([u1.fn, u1.note]));

    // ================= #2084 the import's look-alike
    check(await ev(`/1 possible duplicate/.test(document.querySelector('#ctimp .ctimp-t')?.textContent || '') && !!document.querySelector('#ctimp [data-ctimp="dup"]')`), '#2084: the import says "1 possible duplicate" + Check');
    await click(ev, '#ctimp [data-ctimp="dup"]');
    check(await ready(ev, `!!document.querySelector('.modal [data-ctxdm="0"]') && /Known Twin/.test(document.querySelector('.modal').textContent) && /Person0002 Many/.test(document.querySelector('.modal').textContent)`), '#2084: "Check" lists the new contact and its look-alike');
    await click(ev, '.modal [data-ctxdm="0"]');
    check(await ready(ev, `[...document.querySelectorAll('.modal')].some(m => /Merge 2 contacts/.test(m.textContent))`, 40), '#2084: "Merge" opens the merge view of the two');
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), document.querySelector('#ctimp')?.remove(), 1)`);
    // ================= #2084 the editor's note
    await click(ev, '#view [data-ct="new"]');
    check(await ready(ev, `!!document.querySelector('.modal #ct-given')`), '#2084: the editor opens');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#ct-given').value = 'Other'; m.querySelector('#ct-family').value = 'Name';
      const e = m.querySelector('[data-ctm="emails"] input[data-cf="value"]'); e.value = 'known@example.com'; e.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const n0 = (await call(CC, 'GET', '/api/contacts?limit=1')).total;
    await click(ev, '.modal [data-ctm2="save"]');
    check(await ready(ev, `!!document.querySelector('.modal .ctxdup')`), '#2084: a quiet note in the editor');
    check(await ev(`(() => { const d = document.querySelector('.modal .ctxdup'); return /There is already a contact like this/.test(d.textContent) && /Person0002 Many/.test(d.textContent) && /same e-mail/.test(d.textContent); })()`), '#2084: it names the one there and why');
    check(await ev(`document.querySelector('.modal [data-ctm2="save"]').textContent === 'Create anyway'`), '#2084: Save becomes "Create anyway"');
    check((await call(CC, 'GET', '/api/contacts?limit=1')).total === n0, '#2084: nothing created yet');
    await shot('p21191a-dup-note.png');
    await click(ev, '.modal [data-ctm2="save"]');
    check(await ready(ev, `!document.querySelector('.modal #ct-given')`), '#2084: the second Save creates it');
    check((await call(CC, 'GET', '/api/contacts?limit=1')).total === n0 + 1, '#2084: ... one more contact');
    // the name opens the one there
    await click(ev, '#view [data-ct="new"]');
    await ready(ev, `!!document.querySelector('.modal #ct-given')`);
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#ct-given').value = 'Person0003'; m.querySelector('#ct-family').value = 'Many'; return 1; })()`);
    await click(ev, '.modal [data-ctm2="save"]');
    check(await ready(ev, `!!document.querySelector('.modal .ctxdup [data-ctxdup]') && /same name/.test(document.querySelector('.modal .ctxdup').textContent)`), '#2084: the same name is named too');
    const pid = await ev(`+document.querySelector('.modal .ctxdup [data-ctxdup]').dataset.ctxdup`);
    await click(ev, '.modal .ctxdup [data-ctxdup]');
    check(await ready(ev, `!document.querySelector('.modal #ct-given') && CT.sel === ${pid} && CT.card?.fn === 'Person0003 Many'`), '#2084: the name opens the contact there (the editor closes)');

    // ================= #2085
    check(await ev(`[...document.querySelectorAll('#ct-group option')].some(o => o.textContent === 'Manage groups…')`), '#2085: the group filter offers "Manage groups…"');
    await ev(`(() => { const s = document.querySelector('#ct-group'); s.value = CTX_MANAGE; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Customers/.test(document.querySelector('#ctg-body')?.textContent || '') && !!document.querySelector('#ctg-body [data-ctgr]')`), '#2085: the dialog lists the groups');
    check(await ev(`document.querySelector('#ct-group').value === ''`), '#2085: the filter itself stays as it was');
    check(await ev(`/Customers · 2 contacts/.test(document.querySelector('#ctg-body').textContent)`), '#2085: with the count');
    await shot('p21191a-groups.png');
    await click(ev, '#ctg-body [data-ctgr="0"]');
    check(await ready(ev, `!!document.querySelector('#cdlg-in')`), '#2085: rename asks for the new name');
    await ev(`(() => { const i = document.querySelector('#cdlg-in'); i.value = 'Clients'; i.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('.modal [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `/Clients · 2 contacts/.test(document.querySelector('#ctg-body')?.textContent || '')`, 40), '#2085: renamed in the dialog');
    let gs = (await call(CC, 'GET', '/api/contacts/groups')).items || [];
    check(gs.length === 1 && gs[0].name === 'Clients' && gs[0].count === 2, '#2085: renamed on the server ' + JSON.stringify(gs));
    await ev(`(histStep('undo'), 1)`);  // the step Ctrl+Z / the toast's Undo take
    let back = false;
    for (let i = 0; i < 30 && !back; i++) { await sleep(250); gs = (await call(CC, 'GET', '/api/contacts/groups')).items || []; back = gs.length === 1 && gs[0].name === 'Customers'; }
    check(back, '#2085: the undo step puts the old name back ' + JSON.stringify(gs));
    check(await ready(ev, `/Customers · 2 contacts/.test(document.querySelector('#ctg-body')?.textContent || '')`, 40), '#2085: ... and the dialog shows it');
    await click(ev, '#ctg-body [data-ctgd="0"]');
    check(await ready(ev, `!!document.querySelector('.modal [data-cd="yes"]') && /The 2 contacts stay/.test(document.querySelector('.modal #cdlg-b')?.textContent || document.body.textContent)`), '#2085: delete asks, the contacts stay');
    await click(ev, '.modal [data-cd="yes"]');
    check(await ready(ev, `/No groups yet/.test(document.querySelector('#ctg-body')?.textContent || '')`, 40), '#2085: the group is gone');
    check((await call(CC, 'GET', '/api/contacts?limit=1')).total === n0 + 1, '#2085: every contact stays');

    // ================= phone 402 px: the mapping step fits
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await ev(`(ctx_csvMap(${bk.id}, new File(['First Name,Last Name,E-mail Address,Business Street,Business City\\r\\nPhone,Fit,fit@example.com,A very long street name 123,Somewhere\\r\\n'], 'phone.csv', {type: 'text/csv'})), 1)`);
    check(await ready(ev, `document.querySelectorAll('.modal .ctxmap select').length === 5`), 'phone: the mapping step opens');
    check(await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1 && [...document.querySelectorAll('.modal .ctxmap select')].every(s => s.getBoundingClientRect().right <= window.innerWidth + 1)`), 'phone: nothing sticks out to the side');
    await shot('p21191a-csv-map-phone.png');
  }, false);

  console.log(`p21191_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
