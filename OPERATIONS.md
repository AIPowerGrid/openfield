# Openfield operations

Operator material for the account-isolated staging shell, its offline backups
and restores. None of this is needed to run the single-user `openfield` app;
see [README.md](README.md) for setup and usage.

The separate account-isolated staging shell now has Core-backed sign-in, scoped
projects/assets and account-scoped browser drafts. It is not deployed, and the
local app below remains single-user. Staging rendering stays blocked until
Grid-backed billing and approved-workflow execution are integrated and verified.
The new Core video client and journal are development components, not a change to
the local SDK backend or permission to submit unqualified studio profiles.

Staging now limits expensive transfers/preview builds and offline exports with
shared cross-process slots (four overall, two per workspace, one export per
workspace). Status, recovery receipts and cached media remain readable while
capacity is busy. Request bytes are bounded before multipart parsing, including
chunked uploads; stalled uploads time out and close temporary files. Storage
admission checks existing workspace/total usage and free-space headroom. Before
reading media uploads, it reserves the route's maximum body size across
processes, including temporary-spool headroom. Portable imports instead reserve
1548 MiB for the archive, extraction, remapped copies and bounded metadata;
package creation reserves 1028 MiB for frozen media and the growing archive.
Missing or smaller length headers never reduce these server-owned reservations.
Archives are capped while writing, and rebuilt metadata has an aggregate cap.
A disconnected or dead process releases its OS-held claim. These are conservative
data-byte admission bounds, not filesystem quotas or bounds on every decoded or
generated output. OS limits, decoder isolation and retention/deletion remain
public-release gates. Staging persists the transfer limits with its work policy;
an old or mismatched policy fails closed. Review all writers while stopped before
an explicit policy upgrade; never delete a live lock root or user data to bypass it.

The staging app cache reuses idle workspace slots instead of permanently filling
after its first 128 accounts. Request pins cover the full response; live export
children and held work slots prevent eviction. On a cache miss, it lazily removes
idle entries older than fifteen minutes or the least-recently-used idle entry
needed for capacity. This only discards an in-memory app: sessions, projects and
media stay on disk. If all slots are active, new workspaces receive retryable 503
backpressure. This is not a hard memory quota or a production load qualification.

## Managed Account Staging

The installed wheel includes `aipg-studio-staging`, a separate loopback-only
launcher for the account-isolated shell. It does not enable inference or deploy
the public product. Do not reverse-proxy the single-user `openfield` command (alias `openreshoot`).
Before choosing a public hostname, complete the production-home, billed-workflow,
live-login, upload/decoder isolation and operating gates in the production plan.

Use a dedicated POSIX service user and private absolute state/key-file paths. The
key file must be a regular owner-only file (0600 or 0400), not a symlink, hard
link or pipe. It is read in-process, never passed as a CLI value or loaded into
the environment. Keep the state volume and backups private: the session database
contains credentials. Never commit them or put them in project packages.

```sh
aipg-studio-staging \
  --state-dir /absolute/private/studio-state \
  --service-key-file /absolute/private/grid-service-key \
  --origin https://studio.example \
  --google-client-id PUBLIC_GOOGLE_CLIENT_ID \
  --release-sha256 SHA256_OF_REVIEWED_INSTALLED_WHEEL \
  --port 8800 --check
```

`--check` validates configuration and initializes private session/workspace policy
storage; it does not listen, call Core, verify the credential's permissions, test
Google proofs or generate media. Use the verified wheel hash for the release
label; the launcher validates its format but does not attest installed code.
Remove `--check` to serve only on `127.0.0.1`. There is no remote-bind, reload,
multi-worker or inference-enable switch. A host-bound HTTPS proxy, certificates
and origin registration still require a reviewed deployment. Proxy-forwarded
headers are not trusted, and access logging is off by default.

One managed server holds the private state lease for its full lifetime. A second
server or `--check` against that store fails before session initialization. A
separate shared activity lease covers the server and resource-managed export
children, including after the server exits. Exclusive maintenance rejects active
writers; a late export leaves its saved request untouched and exits 75. The locks
release on normal exit or process death and are never deleted to bypass activity.
Direct factories and arbitrary external writers must still be stopped explicitly.
Existing state is not silently repaired, deleted or migrated on failure.

Send probe GETs with the configured origin's `Host` header. `/health/live` reports
that staging is alive; it does not check Core or create a login session.
`/health/ready` deliberately returns 503 `billed_execution_not_enabled` while
rendering is gated. Do not restart a healthy staging server because of that
expected readiness response, or treat liveness as production launch approval.

Pending sign-in state survives anonymous reloads without resetting its ten-minute
expiry. A reused HttpOnly capability does not authenticate anyone: Google or a
wallet proof and a matching CSRF header are still required. Used, expired or
abandoned wallet challenges get a fresh flow; no proof/signature is replayed.
The shared database admits at most 4096 pending logins. At capacity, new flows
receive a private retryable 429; existing fresh flows, signed-in sessions and
logout remain usable. The page exposes an explicit retry and keeps unavailable
provider controls disabled. This is bounded backpressure, not bot protection or
per-client rate limiting; trusted-edge abuse controls still need deployment review.
## Offline Backups And Restore

Use a reviewed [Restic binary](https://restic.readthedocs.io/en/stable/020_installation.html)
for encrypted snapshots. Keep its password, service credential and repository
outside the state/backup source paths, with owner-only permissions and a separate
recoverable password copy. Backups contain private media and account credentials;
they are not portable project packages and must never be exposed as web downloads.
The commands below configure neither an offsite destination nor a schedule.

Stop the managed web service and let exports finish. Stop direct-factory servers,
older incompatible runtimes and any other writers too. Set the non-secret canonical absolute
path variables `STATE`, `BACKUP_REPO` and `BACKUP_PASSWORD_FILE`, then initialize
the repository once and run a foreground backup:

```sh
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" init
aipg-studio-maintenance hold --state-dir "$STATE" -- \
  restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" \
  backup auth workspaces .workspaces-resources/policy.json \
  --exclude '*.lock' --exclude render.log --tag aipg-studio-state-v1
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" check --read-data
```

Maintenance checks the private layout, policy, bounded file tree, account schema
and ownership records. It takes exclusive writer/observer fences and changes the
command's working directory to `STATE`. The foreground executable inherits the
leases directly; do not wrap it in a shell that launches background work. Busy
stores exit 75 without running the command. Never delete a lock file to retry.
Record the full snapshot ID and require a zero backup/check exit; partial backups
are failures. See [Restic's backup semantics](https://restic.readthedocs.io/en/stable/040_backup.html).

Restore the chosen full snapshot ID (`SNAPSHOT`) only into a brand-new, empty,
owner-only canonical directory (`RESTORED_STATE`) outside the original state tree.
Run as the service user and verify repository health first. Never restore in place:

```sh
mkdir -m 700 "$RESTORED_STATE"
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" \
  restore "$SNAPSHOT" --target "$RESTORED_STATE" --verify --overwrite never
aipg-studio-maintenance prepare-restore --state-dir "$RESTORED_STATE" \
  --previous-state-dir "$STATE"
```

[Restic verifies restored content](https://restic.readthedocs.io/en/stable/050_restore.html);
`prepare-restore` is not that cryptographic verification. It checks the relocated
trusted store, preserves account/workspace mapping and data, clears copied login
sessions/challenges, and rebinds only the resource-policy workspace path last.
Schema/policy changes need a separate migration review. Original, nested,
already-prepared or mismatched stores are rejected. No command starts a service,
submits a model job or rolls back Core credit balances.

Run the staging launcher's `--check` against the restored directory, sign in
fresh, and verify project/media access and an offline export before switching a
service to that path. Keep the original state and exact reviewed wheel. Reconcile
uncertain paid jobs by their original Core IDs, never replacement submissions.
Offsite recovery, scheduling, alerts, retention and software rollback compatibility
still need deployment-specific review and tests; no automatic pruning is enabled.
