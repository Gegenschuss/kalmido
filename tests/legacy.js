// 2.26.0: one agent per list. Older suites test lists with several agents (still possible for lists from before the update)
// and members talking to agents (since 2.26.0 a list switch, default off). shareAny shares like PUT /lists/{id}/members;
// a second agent joins as in a list from before the update, and the list's members may use its agents.
const {execFileSync} = require('child_process');
const path = require('path');
async function shareAny(call, DATA, lid, uid, role) {
  const r = await call('PUT', `/api/lists/${lid}/members`, {user_id: uid, role});
  if (r && r.status === 409 && /one agent/i.test(String(r.error || ''))) {
    execFileSync('python3', ['-c', `import sqlite3, sys
c = sqlite3.connect(sys.argv[1], timeout=10)
c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", (int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[4]))
c.commit()`, path.join(DATA, 'tasks.db'), String(lid), String(uid), role]);
  }
  await call('PATCH', `/api/lists/${lid}`, {agent_members: true, agent_peers: true});
  return r;
}
module.exports = {shareAny};
