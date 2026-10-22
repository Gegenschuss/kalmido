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
  const a = d.querySelector('#srail .sbacct');  // 2.152.2 (#2622): the account sits in the bar (sbb_render keeps the node too)
  check(!!a, 'account button in the bar');  // 2.152.2 (#2622)
  w.renderSide(); await sleep(50);
  check(d.querySelector('#srail .sbacct') === a, 'same .sbacct node after renderSide()');  // 2.152.2 (#2622): the bar
  w.eval("S.avatars = {1: '/x.png'}");
  const e2 = w.av(1, 'A', 'avatar', '', '', true), l2 = w.av(1, 'A');
  check(/decoding="sync"/.test(e2) && !/lazy/.test(e2), 'eager avatar: sync decoding, no lazy');
  check(/loading="lazy"/.test(l2), 'default avatar stays lazy');
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
