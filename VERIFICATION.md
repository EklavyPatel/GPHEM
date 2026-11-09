# Verification — GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT, 9 November 2026

**Current status:** B01–B08 from [BUG_REPORT.md](BUG_REPORT.md) have been addressed in source and covered by regression checks. New amendment forms were checked in Playwright at desktop/mobile widths using temporary Flask-rendered HTML. The currently running Python server needs a restart to load the new routes. These checks are not a deployment load test or a college go-live certification.

## Latest automated results

```bash
.venv/bin/python -m pytest -q
```

**197 tests passed, 5 ordering subtests passed** (68.57 seconds in the full-suite run). The full suite exercises the supplied original engine and SciPy solver, GTU allocation, imports/exports, authentication, CSRF, rate limits, immutable revisions, approvals, publication, backup/restore and dataset sizes up to 5,000 students. Existing publication tests now advance a controlled test clock to the release boundary rather than expecting early manual publication. No production examination dates are falsified to make the tests pass.

## Provided PDF verified end to end

The local private file `624_DI-SEM4SUMMEREXAMINATION-2026 (1).pdf` was actually extracted through Poppler, parsed and allocated. Its data was tested only in temporary test databases; this change does **not** silently import its student roster into the live database.

| Source examination date | Shift | Supplied blocks | Enrollments | Rooms used |
| --- | --- | --- | --- | --- |
| 2026-05-13 | Morning | 12 | 259 | 9 |
| 2026-05-15 | Morning | 21 | 282 | 10 |
| 2026-05-19 | Morning | 19 | 298 | 11 |
| 2026-05-21 | Morning | 18 | 301 | 11 |
| 2026-05-25 | Morning | 18 | 279 | 10 |
| 2026-05-28 | Morning | 13 | 213 | 8 |
| 2026-05-30 | Morning | 2 | 31 | 2 |
| **Total** | | **103** | **1,663** | |

All **24 pages**, **103 declared totals**, enrollment memberships and per-block 1..N bench sequences reconcile. Each session receives an independently verified allocation using the default GTU room configuration. As the PDF's dates have passed, the upload workflow imports these sessions as **private historical rehearsals**, with their exact source dates retained and publication disabled.

Two local verification tests use this private PDF if it exists. The PDF and its personal enrollment data are **not distributed in the source archive**; those two tests skip when the file is absent. Independent generated PDF fixtures contain invented identifiers and test the same extraction and workflow. Poppler is required for PDF-specific tests; scanned/image-only reports are explicitly unsupported without prior OCR.

## New workflow and editing checks

- Real Flask test-client workflow: upload PDF, inspect session preview, choose examination times, confirm selected sessions, generate drafts, inspect all-room visual arrangements, approve and enable automatic release, perform SID lookup, and export reports.
- Multi-session import creates all selected source rosters atomically and generates each draft independently. Invalid selections, bad PDFs, duplicate sessions, insufficient capacity, stale rooms and reused/expired preview tokens are handled without overwriting approved results.
- Exact leading-zero enrollment strings, source block/subject labels and source bench/page provenance survive import, generation and export.
- GTU edits move whole blocks or swap complete rooms. Tests verify preserved block membership and enrollment order, and reject over-capacity, same-subject merging, individual swaps and skipped available rooms. Rejected edits preserve the previous revision.
- Custom Mode imports use the supplied allocator with subject/block metadata. Tests swap individual seats and verify the resulting enrollment, original block label and source PDF bench number.
- Historical sessions remain private even after approval or an explicit publication attempt. Approved private arrangements can be copied into editable drafts again.
- Approval with automatic release checked atomically arms the approved revision for `exam_start_utc − 24 hours`. Results remain hidden one microsecond before the boundary and appear at the boundary. Forged early publication timestamps and manual flags do not bypass it. Moving the configured exam later also prevents an old snapshot from leaking early.
- Branding and UI assertions cover **GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT** and **made by Eklavy Patel**. The mode selector now uses **Custom Mode**; the underlying supplied engine is retained.

## Static/render checks

```bash
python3 -m compileall -q app.py services web tests scripts
node --check static/js/main.js
node --check static/js/arrangement.js
.venv/bin/python scripts/check_templates.py
```

These pass. All **25 full/base templates** render with strict undefined checking and representative data. The navigation partial is exercised through its pages. The real PDF and Custom/GTU arrangement pages are also rendered through authenticated Flask routes in integration tests. SQL compilation checks include the new PDF workflow module.

## Persistence and verification limits

Schema v5 makes a private consistent backup before upgrading v1/v2/v3/v4 databases. Accounts, roster data, original allocation JSON and approved/publication pointers are preserved. Revision release times are derived from recorded examination times; historical and invalid-date revisions fail closed. Databases, backups, sessions, credentials and the private user PDF are excluded from source packages.

The original audit exercised real live-site drag operations and browser PDF printing; its synthetic records were removed afterward. In this fix pass, the new emergency-admission, settings and visual-arrangement screens were rendered from a temporary authenticated Flask application and inspected in Playwright at 1440px and 390px: no full-document overflow, leading-zero SID retained, required reason field, editable release input, typed deletion confirmation and mode-specific notice. POSTs from those browser fixtures were blocked to avoid editing real college sessions. Backend changes were exercised through real Flask/SQLite test requests. The existing live Python process still uses its old route table; `/favicon.ico` remains 404 there until restart. No new synthetic college records were written to its database in this pass; only the automatic schema migration and backup ran.

To inspect the UI on the PC, stop the old Flask process, restart `.venv/bin/python app.py`, and open `/admin`. Choose **Import GTU PDF**, preview the file, confirm its sessions, then open **Visual arrangement**. Use keyboard/touch controls if native HTML drag-and-drop is unavailable. **Print all rooms / Save PDF** and per-room printing use the browser's “Save as PDF” dialog. Normal live GTU imports still require a D−1 receipt. Authorized emergency/revised receipts retain the actual timestamp plus administrator/reason. Review and approval are required before the configured student release.


## Amendment and bug regression coverage

`tests/test_amendments.py` verifies stale copies and approvals after real room changes; withdrawing stale examination times; cancelling automatic publication; custom release timing on the server; late additions after publication with existing Custom Mode seats preserved; duplicate/capacity rollback; same-session PDF replacement preview/confirmation; original-PDF room filling; same-subject/block conflict rejection; real late receipt timestamps and explicit exceptions; typed-confirmation deletion isolated from other examinations; separate client quotas on one IP; authorization; and favicon delivery.

Original PDF export was additionally exercised against the provided private PDF: all **103 room blanks across seven sessions** were filled while retaining **24 original pages**. The private resulting PDF was not written to the source package. Synthetic export tests check extracted room values and unchanged enrollment text. Original roster/bench tables are preserved; current corrected/late assignments belong in the allocation/attendance supplement. Custom Mode blocks split across rooms are explicitly refused by the single-room-blank exporter.

The original PDF bytes now persist privately in SQLite, linked to immutable revision provenance. Sources from old app versions need an explicit revised-PDF upload before this export is possible. Invalid preview confirmations and failed generation do not replace old approved/published results. Deletion is permanent and audited; referenced/shared PDFs are retained, and orphan sources are cleaned when previews expire or the last references are deleted.


## Confirmed emergency placement on the visual board

The dedicated `tests/test_emergency_placement.py` covers an exact chosen seat in draft, approved, unpublished and scheduled/published stages. Confirmation of an approved placement creates a new approved revision; an already published base switches to that revision atomically without changing its release schedule. Private approvals remain private. Existing assignments and historical revisions are preserved. Tests reject occupied/blocked/locked targets, unknown seats, duplicate SIDs, missing confirmation, stale versions/revisions, unauthorized requests, missing CSRF, GTU gaps and split blocks; rejected requests roll back the roster and pointers.

Playwright used a temporary Flask-rendered published board, actual local JavaScript/CSS, and an intercepted synthetic POST destination. It verified the floating card, cancellation, drag onto an empty seat, confirmation and exact submitted SID/seat/confirmation values; `000123` stayed intact. Cancel sent zero requests, confirmed drag sent one, no JavaScript errors occurred, and a 390px viewport had no document overflow. A dropdown and tap/keyboard controls provide alternatives to dragging. Backend persistence/publication is verified separately with real Flask test-client requests and SQLite transactions; the browser fixture never posts to a real college examination.


## Direct emergency placement without a block number

The emergency form now requires only the SID; name, branch, batch/year and subject details are optional. Official block membership is not requested. Direct GTU admissions have a persisted exact-seat reservation and explicit administrator authorization. They are excluded from regular GTU grouping/ordering checks, while independent verification still checks physical cells, room availability/capacity, unique SIDs, identity metadata and their exact reserved seats. Regular GTU assignments continue to pass the original whole-block rules unchanged. UI and exports label these as emergency admissions and distinguish the exception policy from normal-rule validation.

Updated regression tests cover placement at an arbitrary empty seat with a gap, a later room/floor without filling intermediate rooms, no block/subject supplied, successive published amendments, retained student name, regeneration preserving reserved seats, regular-block tampering still rejected, emergency-seat tampering rejected, deletion cleanup, and Custom Mode PDF admission without a block number. Database schema v5 adds private emergency seat reservations with foreign keys and a pre-migration backup. Existing approvals and earlier ordinary GTU configurations are preserved.

The GTU emergency form was also exercised in Playwright with only an SID entered, no block field, and an arbitrary later-room seat selected. The floating card prepared without extra required fields and the confirmed POST reached the intercepted synthetic destination. Backend persistence and rule exceptions are covered by the Flask/SQLite tests; no real examination was modified.


## Institute notice, identity, log deletion and post-exam register

The search and printable seat pages contain the exact requested testing/notice-board message and **BEST OF LUCK**. The title is corrected to **GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT**. The supplied logo is used in both headers, favicon and printed register. An image_gen cleanup draft changed Gujarati lettering, so the original JPEG remains the official live asset; the draft and full prompt are documented in `design/LOGO_NOTES.md`.

`tests/test_college_features.py` verifies both student notices and identity, logo delivery, selected/all log deletion with confirmation/authentication/CSRF checks, preservation of concurrently created log entries, a new deletion marker above the cutoff, and unchanged examination/roster data. It also verifies the consolidated approved block/classroom register, optional drafts, Excel values/text formatting, split blocks across actual classrooms, emergency admissions, authorization, invalid exam filters and historical snapshot details after current metadata changes.

Playwright inspected actual temporary Flask-rendered student/register/audit HTML with local JavaScript/CSS and the supplied logo at 1440px and 390px. The final checks found no document overflow; images loaded, the exact student messages appeared, deletion confirmation was required, and the synthetic two-block register printed to a one-page A4 PDF (83,316 bytes). The initial browser check caught a stylesheet write error; it was restored from the prior source archive and the institute/report styles were reapplied before all six viewport checks passed. Browser fixtures and intercepted assets contained synthetic test records and did not change real college examinations.

The consolidated register is one web page; larger datasets can print on multiple sheets to preserve legibility. All statements about room/block assignment refer to approved immutable allocation snapshots (or visibly marked drafts when opted in). Deleting an examination removes its register data, so export/archive the report before permanent exam deletion. No schema migration or new runtime package was needed for these features.


## Restored visual block and room dragging

The emergency-seat restriction that disabled all normal GTU block/room drags is removed. `edit_blocks` now supports `move_block`, `swap_blocks` and `swap_rooms` while preserving each direct emergency seat. Regular block membership, subject separation, capacity, floor order, contiguous seating and enrollment ordering remain independently validated. Invalid incoming blocks that overlap an emergency seat are rejected without changing the earlier allocation.

The latest approved board now exposes drag controls when its saved inputs still match current inputs. A confirmed normal move creates an editable copy and applies its edit in one transaction. Approval/publication pointers remain unchanged until the new draft is reviewed and approved; rejected edits roll back the copy too. Stale inputs/revisions stay read-only and are rejected on the backend. Historical snapshots retain immutable allocations. Chart-page edits retain their existing draft-only authorization.

Six additional regression cases in `tests/test_board_rearrangement.py` exercise block swaps, room swaps and block moves with an emergency seat, approved/publication preservation, atomic rejected-copy rollback, identity preservation and stale-input rejection. Playwright dragged real rendered block handles and room headers from a temporary approved board containing an emergency admission. Intercepted synthetic requests carried the correct operation, source, target and base revision for all three operations. The 390px board had no document overflow and no JavaScript errors. Backend persistence/validation was checked separately with real Flask test requests and SQLite transactions. No real college arrangements were modified by these browser checks.


## Ground-to-second-floor manual moves

The previous rejection came from applying automatic room-prefix filling and full-before-partial room precedence to manual edits. The manual edit path now records an administrator-selected room policy in the immutable preview. Independent validation honors that policy at saving, approval and export; normal generation still checks the original automatic priorities. UI guidance and the allocation validation report explicitly distinguish administrator-selected rooms from automatic filling.

Six regression cases in `tests/test_cross_floor_moves.py` verify ground-room 721 to empty second-floor room 761 and back, both block moves and room swaps, a full block moved above a partial block, occupied cross-floor block/room swaps, and continued rejection of over-capacity/same-subject/unknown/unavailable rooms. Integration coverage preserves emergency seat 762/17, retains previous publication until approval, verifies the student's published room 761/Second Floor, verifies reports, and retains the manual policy plus fixed emergency seat through a subsequent official roster amendment. Existing automatic-verifier tests still reject unmarked room gaps.

Playwright inspected a temporary approved board with ground, first and second floors plus a fixed emergency seat. Actual block dragging and room-header dragging submitted the expected targets for room 761; the keyboard/touch controls submitted the same room swap at 390px. There were no JavaScript errors or full-document mobile overflow. The browser used synthetic fixtures/intercepted POSTs; the real Flask/SQLite integration tests verified persistence, approval and lookup without modifying real college allocations.


## Deployment upload preparation

The production entry point `serve.py` uses Waitress and the hosting provider's `PORT`; `Procfile`, `.python-version`, runtime/development requirements, the OS-package list, CI workflow and `DEPLOYMENT.md` describe the host-independent setup. The application now creates a missing configured SQLite parent directory for a persistent disk. Eight deployment tests validate server options/body limit and first-run database creation without creating default credentials. The complete local suite passed 197 tests and 5 subtests. An isolated copy containing only the upload manifest passed 195 tests, skipped the two private-PDF tests as expected, and passed 5 subtests; no real database/PDF was copied to it.

GitHub upload was attempted using the connected integration against `EklavyPatel/GPHEM`. GitHub returned HTTP 403, `Resource not accessible by integration`, for both blob creation and file creation. No source commit was published. The command-line fallback could not connect to GitHub from the restricted environment, and the browser was not signed in. `GITHUB_UPLOAD.md`, `UPLOAD_FILES.txt` and `scripts/upload-gphem.sh` provide a reviewed source-only upload path once repository write access is restored. These are access failures, not a successful deployment or an application test failure.
