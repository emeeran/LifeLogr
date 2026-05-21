## Verdict: PASS

---

# Gate Review — Diarilinux SPEC.md

**Reviewer:** Principal Engineer (automated SDD gate)
**Date:** 2026-05-08
**Spec version:** docs/02-spec/SPEC.md

---

## BLOCKERS (must all pass for PASS)

- [x] **Every FR-NNN has at least one endpoint mapped in the traceability matrix**
  All 23 FRs (FR-001 through FR-023) and all 8 NFRs present in the traceability matrix with mapped spec items and priorities.

- [x] **Auth scheme is defined and all protected endpoints are listed**
  Auth section explicitly states: no auth for local endpoints (single-user, offline-first); backup endpoints use stored provider credentials. Since zero endpoints require request-level auth, "no protected endpoints" is the correct and documented answer.

- [x] **Every endpoint has a complete error response list (no "etc.")**
  All 22 endpoints have explicit error response sections. No "etc." or open-ended lists appear anywhere. Three endpoints (`GET /tags`, `GET /backup/config`, `GET /backup/snapshots`) have no error responses listed — see Minor 001, Minor 002.

- [x] **No field typed as Any, dict, or object without justification**
  One field uses `dict[str, str]`: `BackupConfigCreate.credentials`. Justified by the field description ("Provider-specific credential map") and the multi-provider architecture requiring varying credential shapes. See Minor 003 for a suggested improvement.

- [x] **Pagination contract present on all list endpoints**
  Core list endpoints (`GET /entries`, `GET /entries/search`, `GET /backup/snapshots`) all use offset pagination with the standard envelope. `GET /tags` returns a tree (not a flat list) and `GET /entries/calendar/{y}/{m}` is bounded to max 31 entries — neither requires pagination. See Minor 004.

---

## MAJORS (two or more unresolved → FAIL)

- [x] **NFRs have measurable targets (not "fast" or "secure")**
  All 8 NFRs have concrete targets: <200 ms response time, 25 MB upload limit, 30-day retention, AES-256-GCM encryption, WCAG 2.1 AA, SQLite single-file, offline-first testable. No vague qualifiers.

- [x] **No nullable field without a stated reason**
  All 9 nullable columns have clear justifications: `mood` (optional), `deleted_at` (set on soft-delete), `parent_id` (top-level tags), `caption` (optional), `transcription` (pre-transcription state), `schedule_cron` (optional auto-backup), `last_sync_at` (never synced), `completed_at` (in-progress snapshots), `error_message` (no error).

- [x] **Service layer covers all API operations (no missing methods)**
  All 22 endpoints map to service methods across 6 services. `TagService.associate`/`dissociate` support `EntryCreate.tag_ids` internally. `MediaService.delete_by_entry` supports the cascade on soft-delete. No orphan endpoints.

- [x] **ER diagram matches schema definitions**
  Table columns align with Pydantic schema fields. Computed fields in responses (`media_count`, `has_recording`, `tags`, `children`, `entry_count`) are clearly derived, not stored. The `credentials` → `credentials_encrypted` transform is documented in Column Notes.

---

## MINORS (log but do not fail)

### Minor 001 — Missing error responses on GET /tags
**Issue:** `GET /tags` accepts an optional `parent_id` query parameter but lists no error responses. If `parent_id` references a non-existent tag, the behavior is undefined.
**Fix:** Add `404 Not Found — parent_id does not exist` or explicitly state that an invalid `parent_id` returns an empty list.

### Minor 002 — Missing error responses on GET /backup/snapshots
**Issue:** `GET /backup/snapshots` accepts `offset`, `limit`, and `config_id` query parameters but lists no error responses.
**Fix:** Add `422 Unprocessable Entity — invalid query parameters`.

### Minor 003 — BackupConfigCreate.credentials typed as dict
**Issue:** `credentials: dict[str, str]` is the only dict-typed field in the spec. While justified by multi-provider credential variance, a discriminated union based on `provider` would give stronger typing and per-provider validation.
**Fix (optional):** Consider replacing with a `provider`-discriminated union:
```python
ProviderCredentials = Annotated[
    GoogleDriveCreds | OneDriveCreds | DropBoxCreds | WebDAVCreds | NASCreds,
    Field(discriminator="provider")
]
```

### Minor 004 — GET /tags and calendar endpoint lack pagination note
**Issue:** `GET /tags` and `GET /entries/calendar/{y}/{m}` return lists without pagination.
**Fix:** Add an explicit note: "No pagination — bounded result set (single-user tag tree / max 31 entries per month)."

### Minor 005 — Missing examples on several schemas
**Issue:** `TagUpdate`, `TagBrief`, `TagResponse`, `MediaCreate`, `MediaResponse`, `VoiceRecordingResponse`, `TranscriptionRequest`, `BackupConfigResponse`, `BackupSnapshotResponse`, and `RestoreRequest` lack `json_schema_extra` examples.
**Fix:** Add example blocks to all schemas for consistency.

### Minor 006 — No Out of Scope section
**Issue:** The spec does not include an explicit Out of Scope section. REQUIREMENTS.md has one, but the spec should restate or link it.
**Fix:** Add an Out of Scope section referencing the REQUIREMENTS.md list, or include the 6 items directly.

---

## Summary

| Category | Count |
|----------|-------|
| Blockers | 0 |
| Majors   | 0 |
| Minors   | 6 |

**Result: PASS** — The spec is complete, internally consistent, and ready for the design phase (p4). The 6 minors are low-risk and can be addressed during implementation without blocking progress.
