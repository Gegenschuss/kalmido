// 2.47.0 (#1654): renderSide() keeps the account node (and so its avatar <img>) when nothing about it changed,
// and the sidebar avatar is not lazy-loaded (no blink while navigating).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const w = await boot({user: 'alice'}), d = w.document;
  const a = d.querySelector('#kbar .kbacct');  // 2.152.3 (#2619): the account moved into the head bar (sbb_bar keeps the node too)
  check(!!a, 'account button in the head bar');  // 2.152.3 (#2619)
  w.renderSide(); await sleep(50);
  check(d.querySelector('#kbar .kbacct') === a, 'same .kbacct node after renderSide()');  // 2.152.3 (#2619): the head bar
  w.eval("S.avatars = {1: '/x.png'}");
  const e2 = w.av(1, 'A', 'avatar', '', '', true), l2 = w.av(1, 'A');
  check(/decoding="sync"/.test(e2) && !/lazy/.test(e2), 'eager avatar: sync decoding, no lazy');
  check(/loading="lazy"/.test(l2), 'default avatar stays lazy');
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
