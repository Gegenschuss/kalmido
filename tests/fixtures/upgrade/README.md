# Upgrade fixtures

Each `<version>.sql.gz` here is the database of an older release with invented data in it (`tests/upgrade_seed.py`, addresses
`@example.com`), next to `<version>.json`: what that release showed through its API. The suite `p2192_c_upgrade` starts the
current server on every dump in this folder and compares (`tests/upgrade_views.py`); `p4286_restore` uses the 2.101.0 one.

- `2.101.0`: the first dump (before the task search's side tables of 2.281).
- `2.941.0`: the state live ran before the update to 2.995.0 failed (12.11.2026): the old triggers `kalmido_fts_cmt_*` on
  `comments` and `cmt_fts.comment_id -> comments(id)`, which only a jump over the stages Q4a / Q6a in one start meets. Made
  without a local docker: the tag's tree + the current `tests/upgrade_seed.py` as a suite (`upgrade_seed`), run with
  `kalmido-mactest.sh shot upgrade_seed` (KMT_SRC = that tree); the dump comes back in the run's `shots` folder.

## A new dump every quarter (#4359)

Once a quarter the current release joins as a further old state, so the step from it is tested for good.

The nightly CI run makes it anyway: its job "install-upgrade" installs the latest release with its `install.sh`, fills it with
`tests/upgrade_seed.py` and keeps the database as the artifact `upgrade-fixture` (90 days) before it updates to the candidate.
Take it from the newest nightly run whose job "install-upgrade" was green (`gh` inside a checkout of the repository):

```sh
gh run list --workflow ci.yml --event schedule --limit 10 --json databaseId,createdAt,conclusion
gh run view <run id> --json jobs --jq '.jobs[] | select(.name | startswith("Install the last release")) | .conclusion'
gh run download <run id> -n upgrade-fixture -D tests/fixtures/upgrade
```

Then commit the two new files (`<version>.sql.gz`, `<version>.json`) and run `p2192_c_upgrade` and `p4286_restore`.

Without the artifact (a machine with Docker): `tools/make_upgrade_dump.sh v<version>` builds the release's tree and fills its
test server the same way.
