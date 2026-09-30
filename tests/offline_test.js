const {boot, sleep, errs} = require('./boot'); const ids = require('./ids.json');
(async () => {
  const w = await boot({user: 'alice', hash: 'inbox'});
  w.__offline = true;
  await w.eval(`patchTask(${ids.PT}, {title: 'Offline edit', url: 'https://offline.example/x'})`).catch(() => {});
  await w.eval(`api('POST', '/api/tasks', {title: 'made offline', url: 'https://o.example'})`);
  const q = w.eval('OUT.q.length');
  w.__offline = false; await w.eval('flush()'); await sleep(800);
  const t = w.eval(`S.tasks.get(${ids.PT})`), n = [...w.eval('S.tasks').values()].find(x => x.title === 'made offline');
  const ok = [q === 2, t.title === 'Offline edit' && t.url === 'https://offline.example/x', !!n && n.url === 'https://o.example', w.eval('OUT.q.length') === 0, errs.length === 0];
  console.log('queued', q, 'after flush:', ok[1], ok[2], 'queue', w.eval('OUT.q.length'), 'errs', errs.length);
  console.log(`${ok.filter(Boolean).length} ok, ${ok.filter(x => !x).length} failed`);
  process.exit(ok.every(Boolean) ? 0 : 1);
})();
