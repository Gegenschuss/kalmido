// kalmido-suite:
// 2.1155.0 UI test (#5652): the call sheet by e-mail, used as a person would. Own container (start.sh with the SMTP stub of
// tests/stub_mail.py), Firefox (desktop and phone width). Invented names and addresses only.
// - the call sheet dialog has "Send by e-mail"; it opens the mail dialog: the recipients per group (crew, agency, client), each
//   ticked, its name and address visible; the crew member without an address is named under "Without an e-mail address"
// - a recipient left out, the subject changed -> "Preview": the recipients chosen ("To (2)"), the subject typed, the text with
//   the signature, the PDF as a link that opens the PDF; nothing is sent yet
// - "Back" keeps what was chosen and typed; "Send" -> the dialog closes with "Call sheet sent to 2 recipients", the SMTP stub
//   got one mail for each of the two (the PDF attached), none for the one left out
// - nobody ticked: "Preview" is off; at phone width the recipients stay inside the dialog
// freelancer-matrix: hub (alice works in her own personal area, no organisation)
// P21155AUI_NOSTART=1 = the server already runs. Screenshots: P21155A_SHOTS.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21155_a_csmail_ui', check, shots: 'P21155A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const ENV = '-e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test';
if (!process.env.P21155AUI_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: ((process.env.EXTRA || '') + ' ' + ENV).trim()}});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'collab,comments,contacts,office,clients,workload,dispo';
const dstr = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
// the mails the SMTP stub got: [{to, subject, pdf}] (MIME decoded by the standard library)
const MAILS = `import email, email.policy, json, sys
out = []
for ln in open(sys.argv[1]):
    if ln.strip():
        m = email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default)
        pdf = [a.get_filename() for a in m.iter_attachments() if a.get_content_type() == "application/pdf" and a.get_content()[:5] == b"%PDF-"]
        out.append({"to": str(m["To"]), "subject": str(m["Subject"]), "pdf": pdf})
print(json.dumps(out))`;
const mails = () => { try { return JSON.parse(execFileSync('python3', ['-I', '-c', MAILS, path.join(DATA, 'mail', 'out.jsonl')]).toString()); } catch { return []; } };
/** the mail dialog: its step, the recipients (name, address, ticked, inside the card), the "without" line, subject, text */
const DLG = `(() => { const m = document.querySelector('.modal.csmail'); if (!m) return 'null';
  const card = m.querySelector('.card').getBoundingClientRect();
  const rc = [...m.querySelectorAll('.csrcpt')].map(l => { const r = l.getBoundingClientRect(), i = l.querySelector('input');
    return {group: l.closest('fieldset')?.querySelector('legend')?.textContent || '', name: l.querySelector('.csrn')?.textContent || '', email: l.querySelector('.csre')?.textContent || '',
      on: i.checked, inside: r.left >= card.left - 1 && r.right <= card.right + 1 && r.width > 0}; });
  return JSON.stringify({title: m.querySelector('h3')?.textContent || '', rc, without: [...m.querySelectorAll('.csrg .cshint')].map(x => x.textContent).join(' | '),
    subject: m.querySelector('#csm-subject')?.value ?? null, text: m.querySelector('#csm-text')?.value ?? null,
    preview: (b => b ? !b.disabled : null)(m.querySelector('[data-csm="preview"]')), send: !!m.querySelector('[data-csm="send"]'),
    to: [...m.querySelectorAll('.csprev li')].map(x => x.textContent.trim()), lbl: [...m.querySelectorAll('.lbl')].map(x => x.textContent),
    psubj: m.querySelector('.csmsubj')?.textContent || '', ptext: m.querySelector('.csmtext')?.textContent || '',
    pdf: m.querySelector('[data-csm="pdf"]')?.getAttribute('href') || '', pdfName: m.querySelector('[data-csm="pdf"]')?.textContent || ''}); })()`;

(async () => {
  fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
  fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ind = await call('PUT', '/api/industry', {industry: 'film'});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', city: 'Musterstadt', country: 'DE', email: 'buero@beispielfilm.example'}});
  const bk = await call('POST', '/api/books', {name: 'Crew und Kunden', org_id: null});
  const kim = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Kim Kamera', emails: [{value: 'kim@example.com'}]});
  const tom = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Tom Ton'});
  const agy = await call('POST', '/api/contacts', {book_id: bk.id, kind: 'org', fn: 'Werbe Beispiel GmbH', emails: [{value: 'agentur@example.com'}]});
  const knd = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Karla Kunde', org: 'Kundenfirma Beispiel KG', emails: [{value: 'karla@example.com'}]});
  const t = new Date(), D = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 3));
  const b = await call('POST', '/api/team/dispo/bookings', {title: 'Imagefilm', start: D + 'T07:00', end: D + 'T19:00', status: 'firm',
    resources: [{kind: 'contact', id: kim.id}, {kind: 'contact', id: tom.id}]});
  const job = b.bookings?.[0]?.job, org = (await call('GET', `/api/team/dispo?start=${D}&days=1`)).org_id;
  const sv = await call('PUT', `/api/team/dispo/callsheet/${job}?org=${org}`, {data: {agency_contact: agy.id, client_contact: knd.id}});
  check(ind.status === 200 && kim.id && tom.id && agy.id && knd.id && b.status === 201 && sv.status === 200,
    `setup: Film & Video, four contacts, a shoot day with Kim and Tom, agency and client chosen ${b.status} ${sv.status}`);

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
  const dlg = async ev => JSON.parse(await ev(DLG));
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const openMail = async ev => {
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); cs_open(${JSON.stringify(job)}, ${org}); return 1; })()`);
    if (!(await ready(ev, `!!document.querySelector('.modal.csmd [data-cs="mail"]')`))) return false;
    await ev(`(() => { document.querySelector('.modal.csmd [data-cs="mail"]').click(); return 1; })()`);
    return ready(ev, `!!document.querySelector('.modal.csmail .csrcpt')`);
  };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#workload');
    check(await ready(ev, `typeof cs_open === 'function' && !!document.querySelector('#view')`), 'the app is up');

    // ================= the mail dialog: the distribution per group, all ticked
    check(await openMail(ev), 'the call sheet has "Send by e-mail", it opens the mail dialog');
    let d = await dlg(ev);
    const rc = d.rc.map(x => `${x.group}|${x.name}|${x.email}|${x.on}`);
    check(JSON.stringify(rc) === JSON.stringify(['Crew|Kim Kamera|kim@example.com|true', 'Agency|Werbe Beispiel GmbH|agentur@example.com|true',
      'Client|Karla Kunde Kundenfirma Beispiel KG|karla@example.com|true']), 'crew, agency and client with name and address, each ticked ' + JSON.stringify(d.rc));
    check(/Without an e-mail address: .*Tom Ton/.test(d.without), 'Tom (no address) is named, not offered ' + d.without);
    check(/Imagefilm/.test(d.subject) && /^Hello,/.test(d.text) && d.preview === true, `the subject and text are filled in ${d.subject} / ${d.text}`);
    await shot('p21155a-mail-form.png');

    // ================= nobody ticked: no preview
    await ev(`(() => { document.querySelectorAll('.modal.csmail [data-csm-to]').forEach(i => { i.checked = false; i.dispatchEvent(new Event('change', {bubbles: true})); }); return 1; })()`);
    check((await dlg(ev)).preview === false, 'nobody ticked: "Preview" is off');
    await ev(`(() => { document.querySelectorAll('.modal.csmail [data-csm-to]').forEach(i => { i.checked = i.dataset.csmTo !== 'agentur@example.com'; i.dispatchEvent(new Event('change', {bubbles: true})); }); return 1; })()`);

    // ================= the agency left out, the subject changed -> the preview
    await ev(`(() => { const s = document.querySelector('.modal.csmail #csm-subject'); s.value = 'Dispo Imagefilm Drehtag 1'; s.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const n0 = mails().length;
    await ev(`(() => { document.querySelector('.modal.csmail [data-csm="preview"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.csmail [data-csm="send"]')`), 'the preview shows');
    d = await dlg(ev);
    check(d.lbl.includes('To (2)') && d.to.length === 2 && /Kim Kamera.*kim@example.com/.test(d.to[0]) && /Karla Kunde.*karla@example.com/.test(d.to[1]),
      'the preview: the two recipients chosen ' + JSON.stringify(d.to));
    check(!d.to.some(x => /agentur/.test(x)), 'the agency is not among them');
    check(d.psubj === 'Dispo Imagefilm Drehtag 1', 'the subject typed ' + d.psubj);
    check(/^Hello,/.test(d.ptext) && /\n-- \n/.test(d.ptext), 'the text with the signature ' + JSON.stringify(d.ptext));
    check(/\.pdf/.test(d.pdfName) && /\/pdf\?org=.*inline=1/.test(d.pdf), 'the PDF attached, as a link ' + d.pdf + ' ' + d.pdfName);
    const pdf = await ev(`fetch(${JSON.stringify(d.pdf)}, {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.text()).then(t => t.slice(0, 5))`);
    check(pdf === '%PDF-', 'the link opens the PDF ' + pdf);
    check(mails().length === n0, 'the preview sent nothing');
    await shot('p21155a-mail-preview.png');

    // ================= back keeps it, then send
    await ev(`(() => { document.querySelector('.modal.csmail [data-csm="back"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.csmail #csm-subject')`), '"Back" goes to the form');
    d = await dlg(ev);
    check(d.subject === 'Dispo Imagefilm Drehtag 1' && d.rc.find(x => x.email === 'agentur@example.com')?.on === false && d.rc.filter(x => x.on).length === 2,
      '"Back" keeps the subject and the choice ' + JSON.stringify(d.rc));
    await ev(`(() => { document.querySelector('.modal.csmail [data-csm="preview"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.csmail [data-csm="send"]')`), 'the preview again');
    await ev(`(() => { document.querySelector('.modal.csmail [data-csm="send"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.csmail') && [...document.querySelectorAll('.toast, #toast, [role="status"]')].some(x => /Call sheet sent to 2 recipients/.test(x.textContent))`, 100),
      'sent: the dialog closes with "Call sheet sent to 2 recipients"');
    let got = [];
    for (let i = 0; i < 40; i++) { got = mails().slice(n0); if (got.length >= 2) break; await sleep(200); }
    check(got.length === 2 && got.map(x => x.to).sort().join(',') === 'karla@example.com,kim@example.com', 'one mail each for Kim and Karla ' + JSON.stringify(got));
    check(got.every(x => x.subject === 'Dispo Imagefilm Drehtag 1' && x.pdf.length === 1 && /^callsheet-.*\.pdf$/.test(x.pdf[0])), 'the subject typed, the PDF attached ' + JSON.stringify(got));
    check(!got.some(x => /agentur/.test(x.to)), 'nothing for the agency');

    // ================= phone width: the recipients inside the dialog
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await sleep(300);
    check(await openMail(ev), 'phone: the mail dialog opens');
    d = await dlg(ev);
    check(d.rc.length === 3 && d.rc.every(x => x.inside), 'phone: the recipients stay inside the dialog ' + JSON.stringify(d.rc));
    await shot('p21155a-mail-phone.png');
  });

  console.log(`p21155_a_csmail_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
