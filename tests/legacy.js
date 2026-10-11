// 2.26.0: one agent per list. Older suites test lists with several agents (still possible for lists from before the update)
// and members talking to agents (since 2.26.0 a list switch, default off). shareAny shares like PUT /lists/{id}/members;
// a second agent joins as in a list from before the update, and the list's members may use its agents.
const {execFileSync} = require('child_process');
const path = require('path');
async function shareAny(call, DATA, lid, uid, role) {
  const r = await call('PUT', `/api/lists/${lid}/members`, {user_id: uid, role});
  if (r && r.status === 409 && /one agent/i.test(String(r.error || ''))) {
    execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA,  // 2.37.0 (#1150): Postgres via dbx
      "INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
      JSON.stringify([Number(lid), Number(uid), role, role])]);
  }
  await call('PATCH', `/api/lists/${lid}`, {agent_members: true, agent_peers: true});
  return r;
}
module.exports = {shareAny};
