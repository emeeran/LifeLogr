# Blind Review — 2026-11-08 (verbatim, unedited)

Dispatched as a plain cold handover review of an unmodified checkout. The
prompt did not mention this pipeline, its phases, or that any cleanup ran;
the reviewer found the phase commits and AUDIT.md on its own by reading the
repo. Reproduced verbatim below.

---

# Production-Readiness Review — LifeLogr

**Scope of what I personally read and verified:** `backend/app/main.py`,
`core/config.py`, `core/security.py`, `core/database.py` (engine/pragmas),
`core/cron_utils.py`, `core/restore.py` (outline),
`services/encryption_service.py`, `services/media_crypto.py`,
`services/entry_service.py` (delete/restore paths),
`services/scheduler_service.py` (reminders, catch-up, `_run_backup`),
`services/backup_service.py` (archive build), `services/web_clip_service.py`
(SSRF guards), `routers/entries.py` (exports, calendar), `routers/backup.py`
(import/restore), `routers/media.py`, `routers/system.py`, plus greps across
all of `backend/app` for silent excepts/TODOs. I ran the gates myself:
**pytest 1004 passed (51s), vitest 322/322 passed, vue-tsc clean, mypy strict
clean, ruff clean**. Two sub-reviews (frontend, desktop/packaging) were done
separately; I independently re-verified their highest-severity claims in the
source before including them. I also read the repo's own `AUDIT.md` at HEAD
and cross-checked its claims rather than trusting them.

Important context: HEAD is `phase(4): production readiness audit` on branch
`cleanup/pipeline-2026-11-08`, 23 commits ahead of unmerged-into-`main` — and
the repo's **own audit at HEAD lists two data-integrity blockers as
still-open checkboxes**. Those findings are real (I verified them), and they
are not yet fixed.

---

## Blocker / High

**H1. `/api/v1/backup/import` and `/api/v1/backup/restore` are outside the
destructive-origin guard.** `main.py:348` — `_DESTRUCTIVE_PATHS =
frozenset({"/api/v1/entries/reset"})` — but `routers/backup.py:345`
(`POST /import`) and `:224` (`POST /restore`) atomically swap the live DB and
are ordinary POSTs. The generic CSRF guard (`main.py:299-312`) trusts **any
loopback origin**, and a multipart upload is a CORS "simple request" (no
preflight), so a hostile page on any other local port (e.g.
`http://localhost:9999`) can replace the database — including the
settings/AI-provider rows, letting it re-point `base_url`s and harvest stored
keys on the next AI call. The code clearly knows this threat model (the
comment block at `main.py:335-347` describes exactly this attack for
`/reset`) but applies it to only one path. This is the single worst gap I
found.

**H2. Scheduled local backups can be silently truncated and can be killed
mid-write.** `scheduler_service.py:782-805`: `tarfile.open(archive_path,
"w:gz")` writes **directly to the final** `lifelogr-backup-<ts>.tar.gz` (no
`.part` + `os.replace` staging), and `_run_backup` registers nothing with the
job registry that `/api/v1/system/shutdown-state` reads — so the desktop
shell's 2s SIGTERM / 2.5s SIGKILL window (`main.rs:211,308-348`) can kill the
job mid-tar. A truncated archive then still counts toward retention
(`_cleanup_old_backups`, `scheduler_service.py:823-834`, globs
`*-backup-*.tar.gz`), so the corrupt file can evict the last good one. Cloud
backups do stage via mkstemp + in-progress snapshot row
(`backup_service.py:196,231`) — the local path simply never got the same
treatment. For a "the backup you keep may be the one you need" app, this is a
blocker.

**H3. Soft delete destroys media immediately; restore recovers only text.**
`entry_service.py:302-332` unlinks every media file and deletes
`Media`/`VoiceRecording` rows at trash time; `restore()`
(`entry_service.py:343-348`) documents "media files … are not restored". The
notes flow keeps attachments through delete (lossless), so entries and notes
have **contradictory trash semantics** in the same app. Deliberate
(AGENTS.md mandates it; comments acknowledge it), but deliberate does not
mean safe: a user tapping delete expects trash and permanently loses
photos/voice clips.

**H4. Desktop shell: no SIGTERM handling, and relaunch hard-kills the port
owner.** `desktop/src-tauri/src/main.rs` registers no signal handler —
`RunEvent::ExitRequested` (`main.rs:710-718`) fires only on window close. On
logout/`systemd stop`/`kill`, the shell dies and the PyInstaller backend is
orphaned; the next launch reclaims port 18765 with `fuser -k`
(`main.rs:181-184`), whose default is SIGKILL — exactly the signal that
corrupts a mid-WAL-flush or mid-backup backend. The whole careful
graceful-teardown chain (bounded 2s lifespan deadline at `main.py:132-168`,
SIGTERM-then-SIGKILL by PID at `main.rs:214-299`) is reachable only through
the close button.

**H5. Desktop: foreign process on port 18765 → the app silently talks to
it.** `wait_for_sidecar` is a bare TCP probe (`main.rs:115-125`), so a
squatter satisfies it; `verify_sidecar_owner` failure only logs to the
desktop log (`main.rs:373-376`); nothing reaches the UI, and
`frontend/src/api/client.ts` then posts every journal entry to whoever
answers. The port is hardwired in three places (`main.rs:44`, `client.ts:4`,
`tauri.conf.json:25`). Should be a blocking error dialog, not a log line.

## Medium

- **M1. Autosave race guard doesn't cover the manual save path.**
  `useAutoSave.ts:46-49` claims it prevents "two concurrent updateEntry calls
  … last-write-wins data loss", but `saving` is only set inside the
  composable's own debounced callback (`useAutoSave.ts:108`); the manual
  `save()` in `EntryEditor.vue` never sets it. Ctrl+S + one more keystroke
  can race. Related: a tick that fires while `saving` is true returns without
  re-arming (`useAutoSave.ts:104-107`) — if that was the last keystroke, the
  edit sits unsaved with no timer and `saveState='pending'`. (I verified both
  in source.)
- **M2. Exports buffer the entire archive (media included) in RAM.**
  `routers/entries.py:424-531` (`_build_markdown_zip_sync` → `BytesIO`) and
  `services/export_service.py:418-512`. Contrast `backup_service.py:163-206`,
  which explicitly streams to a temp file to avoid "buffering the potentially
  multi-GB archive in RAM". A media-heavy journal export can OOM the machine
  — and there's a recorded history of OOM incidents in this project's memory
  notes.
- **M3. Tauri capability surface is broader than needed.**
  `capabilities/default.json:8-12` grants the renderer `shell:allow-spawn`
  with `args: true` (the Rust setup spawns the sidecar itself; the frontend
  doesn't need this), plus blanket `fs:allow-write-file` over
  `$DOWNLOAD/$DOCUMENT/$PICTURE/$DESKTOP/$HOME/Documents` rather than
  dialog-scoped.
- **M4. Port-reclaim details contradict the codebase's own rules.**
  `main.rs:187-191` falls back to `pkill -f lifelogr-backend`, the exact
  name-matching the `SidecarChild` doc (`main.rs:12-14`) says was rejected;
  `stop_backend`'s PID-correct path needs `lsof` (`main.rs:352-362`) but the
  .deb declares only `psmisc` (`tauri.conf.json:53`) — without lsof, graceful
  shutdown degrades to SIGTERM-ing the PyInstaller bootloader, which the
  code's own comment (`main.rs:255-258`) says can't be relied on.
- **M5. Malformed query params 500 instead of 422.** `routers/entries.py:197-204`
  takes raw `year: int, month: int`; `month=13` raises `ValueError` in
  `date()` (`entry_service.py:374`) → generic 500 via the unhandled handler,
  same for `start_date=oops` and `?tag_ids=abc`. `search.py:23-24` already
  does it right — inconsistent.
- **M6. Repo hygiene: AI-cleanup working artifacts are tracked in git.**
  `.pipeline/` (100K+ gate logs, `blind-review.md`, `inventory.csv`,
  purge/refactor plans) and `trash2review/` (parked deleted code, including
  an old `sync.py` router) are committed. They're process scaffolding, not
  product. Combined with commit-message seams (`phase(2): debloat — unit J`,
  `style and authorship consistency pass` vs. `Stability:`/`Notes UX:`
  one-liners), the multi-session, pipeline-driven provenance is visible in
  the repo itself.
- **M7. Two parallel markdown-ZIP export builders.** `routers/entries.py:424`
  (Diarium-compatible, router-local, ~90 lines) vs
  `services/export_service.py:418` (Obsidian-compatible, in the service where
  it belongs). Different formats, so not pure duplication — but a 90-line zip
  builder living in a router while a sibling export service exists is a
  layering seam someone will trip on.
- **M8. Frontend: ENC chip built by unescaped interpolation before
  sanitization.** `utils/markdown.ts:60-62` embeds matched ciphertext raw
  into `data-enc="${enc}"` where the regex admits `"`. DOMPurify downstream
  makes it non-exploitable, but safety rests entirely on the sanitizer while
  `escAttr()` sits unused in the same file.
- **M9. `useJobProgress` retries a failed poll forever at 1 Hz, no
  backoff/cap** (`useJobProgress.ts:44-49`) — the only unbounded loop in the
  app.
- **M10. ESLint is not a CI step** (frontend job runs
  vue-tsc/vitest/build/e2e; no `npm run lint`), despite zero-warning being a
  stated goal.
- **M11. Desktop logging: `init_logging` truncates the log every launch and
  `.expect()`s (`main.rs:385-400`)** — no post-mortem trail after a crash,
  and an unwritable data dir aborts startup.

## Low / Info

- Entry editor's localStorage draft mirror lacks the `maxWait` bound its
  notes twin has (`useDraftRecovery.ts:48-50,156-164` vs inline copy in
  `EntryEditor.vue:470-568`), and no `beforeunload` guard — an asymmetric
  port.
- Backend stale comment: `backup_service.py:184-185` says "engine pool is
  size 1"; `database.py:33-38` deliberately made it 5 (the "entries missing"
  bug). Doc-rot from iterative patching.
- No updater plugin — manual checksummed downloads; defensible for
  local-first, but a choice worth recording.
- Cross-platform scaffolding for a Linux-only app: `msi`/`dmg` bundle targets
  (`tauri.conf.json:35`), Windows/macOS CI jobs; `scripts/build.sh` is a
  divergent second build path (no `VITE_APP_VERSION`, different distpath) that
  would ship a stale-version artifact if anyone followed it.
- Version-source count drift: "5 places" vs "4 source files"
  (`Makefile:23-24`, `ci.yml:124`, `scripts/check_version.py:58-65` — the
  script is right; the docs aren't).
- CI checksum steps glob the wrong platform's artifacts
  (`build.yml:106,195,273`) — copy-paste noise, harmless.
- Env comparison styles differ: `config.py:432` (`== "production"`) vs
  `main.py:431` (`strip().lower() in ("test","testing")`) — works today,
  fragile tomorrow.

## Checked and found clean (explicitly)

- **Cryptography**: per-item scrypt KDF with versioned salt formats
  (`encryption_service.py:30-89`), AES-256-GCM, embeddings deleted on encrypt
  to kill the search oracle (`:136-139`); chunked media AEAD with storage
  path bound into AAD and domain-separated HKDF (`media_crypto.py:41-43,91-96`);
  credential encryption refuses the public default key outside test env
  (`security.py:48-71`); managed-run key generation persists with umask 077
  and **fails hard** rather than using an ephemeral key (`config.py:177-192`).
- **Injection/SSRF/traversal**: web clip validates the destination IP before
  every redirect hop (`web_clip_service.py:64-84`); static SPA catch-all has
  containment + API-404 (`main.py:693-701`); restore validates tar members
  and DB integrity (`restore.py`); `upload_media_from_path` is
  allowlist-sandboxed (`media.py:56-66`).
- **Frontend XSS**: single marked+DOMPurify pipeline, all 7 `v-html` sites
  render only its output, external links forced through `openExternal`
  (noopener / Tauri shell).
- **DB safety**: WAL + FK + busy_timeout + incremental auto_vacuum with a
  comment explaining the lock-ordering trap (`database.py:48-76`); rotating
  boot snapshot and corrupt-DB quarantine; 1004 tests including real
  backup/restore, encryption, and import round-trips.
- **Operational hygiene**: bounded shared-deadline shutdown
  (`main.py:132-168`), `/health` with per-subsystem checks, deduped/capped
  client-error reporting (`system.py:52-90`), egress report, WAL
  checkpointing before backups.
- **No TODO/FIXME/HACK, no commented-out code, no dead components, no silent
  `except: pass`** anywhere I grepped (backend, frontend, desktop). Comments
  are why-not-what and match the code — this does *not* read like templated
  AI slop; it reads like many careful, individually-audited sessions.

## Verdict

This is an unusually coherent, deliberately-written codebase — dense with
rationale comments that match the code, real round-trip tests at every data
boundary, clean gates (pytest 1004 / vitest 322 / vue-tsc / mypy strict /
ruff, all green locally), and a threat model (CSRF, DNS-rebinding, SSRF, key
management) most desktop apps never bother with. I would *not* take on-call
for it as-is, for one specific reason: the app's entire promise is "your data
is safe on disk," and its two data-safety mechanisms are currently the
weakest links — a database-swapping endpoint pair missing from the
destructive-origin guard (H1) and a local backup that can be silently
truncated by the very shutdown logic built to protect it (H2), with entry
trash quietly shredding attachments (H3). The repo's own phase(4) audit
already says this ("fix those two before calling the data-safety story done")
and the checkboxes are still empty on an unmerged branch — so the team knows,
which is a good sign, but on-call starts when the fixes do. First week, in
order: (1) add `/backup/import` + `/backup/restore` to `_DESTRUCTIVE_PATHS`,
(2) stage local backups via mkstemp + `os.replace` and register them with the
shutdown-state job registry, (3) add a SIGTERM handler in the Rust shell and
surface sidecar-owner verification failure to the UI instead of a log line,
(4) decide and document one trash semantic (defer media cleanup to purge,
matching notes), then merge `cleanup/pipeline-2026-11-08` and delete
`.pipeline/`/`trash2review/` from git.

---

**Honest limit:** this reviewer still runs on the same underlying model as
the pipeline that produced AUDIT.md. The sanitized dispatch removes
self-grading and framing bias, not model blind spots — the reviewer and the
audit agents can share failures. It also found AUDIT.md at HEAD mid-review
(it's a tracked file in the repo), so its H1–H3 agreement is corroboration
with knowledge of, not ignorance of, the audit. For a genuinely independent
signal, paste a code sample into a brand-new session (fresh terminal,
ideally a different reviewer) and ask the same cold-review question.
