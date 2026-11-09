# Playwright audit: GTU SEATING ARRANGEMENT

Date: 9 November 2026. Target: the running application at `http://127.0.0.1:5000`.

**Original audit recommendation:** fix B01/B02 and the shared campus quota before college rollout. The implementation status below supersedes that open-defect assessment.

This was a functional browser audit, not a penetration test, full accessibility certification, or large-scale load test. Application source code was not changed during the audit.


## Fix status — 9 November 2026

The findings below describe the original audit. The source now addresses B01–B08:

| ID | Resolution |
| --- | --- |
| B01 | Copies, approvals and publication recheck the saved snapshot against current roster, room versions, availability, rules and exam metadata. Stale inputs require regeneration. |
| B02 | Critical exam metadata edits withdraw publication; public lookup also rejects mismatched snapshot metadata. Historical approvals remain immutable. |
| B03 | Separate browser quota (60/minute) and network ceiling (6,000/minute). Independent browsers on one NAT no longer share a 30-search quota. Deployment burst/load testing remains necessary. |
| B04 | Explicit same-session revised PDF preview/confirmation, plus individual record corrections and emergency admissions. Generation failure rolls back the proposed roster; old publication remains intact until reviewed release. |
| B05 | Switching automatic release off disables current publication. The UI explains this. Release date/time is now editable and audited, defaulting to exam minus 24 hours. |
| B06 | Public instructions use #465541 on #f6f8f3 (approximately 7.45:1); small form hints are darkened. This is not a full accessibility certification. |
| B07 | Arrangement notices describe the selected mode's actual constraints. |
| B08 | Local SVG favicon and a /favicon.ico redirect. |

Regression checks are in `tests/test_amendments.py` plus the existing workflow suite. New screens were checked in Playwright at 1440px and 390px using HTML rendered by a temporary Flask test application; no full-document overflow was found. The live running Python process still has the old route table and needs a restart (its /favicon.ico remains 404 until then). Browser checks of those fixtures do not substitute for the real Flask/SQLite request tests.

Emergency admission now also supports entering details directly on the visual board, dragging a pending card to an empty seat and confirming. For an approved/published base this confirmation updates the approved/published revision atomically, retaining the release schedule and every existing student seat. Direct emergency placement no longer asks for an official block number. Any available empty GTU seat can be chosen as an explicitly recorded exception; regular students retain their assignments and rules. Larger corrections still use the reviewed draft workflow.

Original-PDF annotation was also verified with the provided private 24-page PDF, retaining all pages and filling the selected session's room blanks. Original student tables are preserved; late/corrected records belong to the supplemental allocation report. See README for the reviewed amendment workflow.

## Findings at a glance

| ID | Priority | Finding | Classification |
| --- | --- | --- | --- |
| B01 | High | Copying an approval can bypass newly saved room restrictions | Confirmed application defect |
| B02 | High | Students can receive the old examination time after the administrator changes it | Confirmed application defect |
| B03 | High for campus deployment | Thirty searches per minute per IP can block students sharing college Wi-Fi/NAT | Confirmed threshold; deployment capacity risk |
| B04 | Medium | A corrected GTU roster cannot replace an existing date/shift through the UI | Confirmed college workflow gap |
| B05 | Medium | Clearing the automatic-release checkbox leaves an existing publication armed/live without explaining the distinction | Confirmed state/UX ambiguity |
| B06 | Medium | Student instructions have insufficient text contrast | Measured accessibility defect |
| B07 | Low | Custom Mode shows a notice describing GTU-only movement constraints | Confirmed copy defect |
| B08 | Low | `/favicon.ico` returns 404 | Confirmed missing asset |

## B01 — Current room restrictions can be bypassed by copying an approval

**College impact:** a newly approved arrangement can still place students in a room the administrator has disabled. An invigilator could receive a plan that contradicts the session's active room availability.

Reproduction performed in Playwright:

1. Import a clearly labelled synthetic GTU PDF, generate and approve its arrangement. Room 721 contains students.
2. Open GTU room rules, disable room 721 and save.
3. Choose **Create editable copy of approval**.
4. The copied draft still contains room 721 and its students, is treated as current/editable, and can be approved successfully.

Observed database verification: the examination stored `gtu_disabled=["721"]`, while the newly approved revision stored `disabled_rooms=[]`. Its `input_version` matched the current examination version. This is a fresh approval of obsolete constraints, not merely viewing an old historical snapshot.

Likely cause: [copy_approved](app.py:509) passes the old snapshot's complete configuration into `save_revision`. [save_revision](services/allocation_service.py:106) labels it with the current expected version. [approve](services/allocation_service.py:189) validates against that copied configuration, not the current examination inputs.

Fix direction: track a content fingerprint/version for actual allocation inputs. Reject copying/reapproving an obsolete configuration, or reconcile the copy against current rooms, rules and roster before allowing approval. Do not mark old inputs as fresh merely because a new revision was created.

Evidence:

- [Room 721 explicitly disabled](audit/2026-11-09/bug-disabled-room-settings.png)
- [Copied draft still uses room 721 and offers approval](audit/2026-11-09/bug-stale-copy-disabled-room.png)

## B02 — Changed exam time does not invalidate published student information

**College impact:** students can be told the wrong arrival/examination time, even though the administrator sees a successful save and an updated time.

Reproduction performed in Playwright:

1. Approve and release the synthetic examination with an 08:00 start.
2. Change the start to 09:00 on the same date and save settings. Both times are already within the 24-hour visibility window.
3. Search the same enrollment again from a separate, anonymous student browser context.

Observed: administration displayed **09:00**, but both the student's examination dropdown and ticket still displayed **08:00**. The administrator page continued to say **Visible to students**. The printable snapshot also retained 08:00.

The current 24-hour gate correctly hides results if the revised start moves outside the window; that does **not** solve stale times once both old and new starts are inside it.

Likely cause: [exam_detail](app.py:245) updates examination metadata but leaves the published snapshot active; student results read the immutable snapshot through [published_exams](services/allocation_service.py:208).

Fix direction: unpublish/invalidate the affected active result when critical exam metadata changes, requiring an explicit refreshed approval/release, or implement a separately versioned metadata amendment. Preserve old historical snapshots, but do not present their old time as the current confirmed examination time.

Evidence:

- [Administrator sees 09:00](audit/2026-11-09/bug-stale-time-admin.png)
- [Student still receives 08:00](audit/2026-11-09/bug-stale-time-student.png)

## B03 — Campus IP sharing can trigger a student search outage

**College impact:** many students on the same college Wi-Fi/NAT connection can exhaust one shared quota. A reverse proxy can also cause every visitor to appear to come from the proxy if client-address handling is not configured for the deployment.

Playwright sent valid-CSRF lookup requests from one browser context: **requests 1–30 returned 200; request 31 returned 429**. A repeat also returned 429. These were invented/nonexistent enrollment values, not real student records. The audit's lookup limiter state was restored afterward.

This threshold is implemented intentionally; the defect is its suitability as a deployment default for college-scale traffic. Actual campus NAT topology was not available to test, so the shared-network impact is an inference from the confirmed IP-only key and the observed quota.

Sources: [lookup quota](app.py:140), [IP-only limiter key](services/security.py:105).

Fix direction: size the burst/rate policy for expected examination-release traffic, use correctly configured trusted-proxy client addresses, and combine per-client/per-enrollment protections without making the entire campus share 30 searches/minute. Do not trust arbitrary forwarding headers or simply remove all abuse protection.

## B04 — Corrected official GTU PDFs have no supported replacement workflow

**College impact:** an official revised list or an accidentally confirmed wrong enrollment cannot be repaired through the normal GTU interface while keeping the same examination date/shift and preserving approval history.

Reproduction performed in Playwright:

1. Import the synthetic date/shift with 45 enrollments.
2. Upload a corrected PDF containing 46 enrollments for that same date/shift.
3. Preview reports that the session already exists; the import checkbox is disabled.

This duplicate protection is appropriate for preventing accidental overwrites. However, the application has no explicit **Replace roster / import revised GTU list** operation. A PDF-backed session also rejects mixing in spreadsheet records, and creating another GTU examination with that same date/shift is disallowed.

Classification: **workflow gap**, not a claim that the duplicate validation itself is incorrect. A safe replacement must be explicit, versioned and reviewed; approved/published data should remain protected until a revised plan is approved.

Source: [PDF duplicate-session validation](web/pdf_routes.py:50), [PDF-backed roster import restriction](app.py:272).

Evidence: [Valid corrected PDF blocked at the existing session](audit/2026-11-09/bug-corrected-pdf-blocked.png).

## B05 — Automatic-release setting and active publication state are ambiguous

Observed in Playwright: after automatic approval had released a test arrangement, clearing **Automatically release approved results at the 24-hour mark** and saving left **Student access: Visible to students**. The session's publication remained active; only the separate **Unpublish results** action withdrew it.

This does not demonstrate a bypass of the 24-hour boundary. It shows that the checkbox changes the policy for subsequent approvals rather than clearly controlling an already armed/live publication. Continuing to display an already published result can be a legitimate design, but the UI does not explain that distinction or warn when saving.

**College risk:** staff may believe they paused a release by clearing the checkbox. For an already scheduled future publication, the public visibility query likewise does not use `auto_publish`; the separate publication state remains the deciding control. That future consequence was confirmed by code inspection rather than by waiting for a second live release window.

Fix direction: label the checkbox as applying to future approvals, show an explicit armed/live state with a **Cancel release / Unpublish** control beside it, and warn when a policy toggle will not affect an existing release. If the intended product behavior is to cancel pending release, update that state transactionally.

Source: [settings update](app.py:245), [approval auto-arm](services/allocation_service.py:203), [public visibility conditions](services/allocation_service.py:212).

Evidence: [Checkbox cleared while student access stays visible](audit/2026-11-09/bug-auto-release-off-still-visible.png).

## B06 — Student instructions fail minimum normal-text contrast

Playwright measured the public homepage instruction text:

- Text: `Find your examination classroom and seat in a moment.`
- Foreground: `rgb(145,160,128)`.
- Background: `rgb(246,248,243)`.
- Mobile size/weight: 11px / 400.
- Calculated contrast: approximately **2.60:1**.

Normal-sized instructional text needs at least **4.5:1** under [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). This is actual instructional text, not a logo or disabled control.

Fix direction: darken the relevant text colors and audit the other small hints, table metadata and labels. This finding checks one specific instance; it is not a full WCAG audit.

## Minor findings

### B07 — Custom Mode notice incorrectly describes GTU-only restrictions

After a successful individual Custom Mode seat swap, the page still says GTU moves must preserve whole blocks and enrollment order. The mode-specific heading is correct, but the generic notice can cause staff to believe those restrictions were enforced on a Custom Mode plan.

Source: [unconditional editable-board notice](templates/admin/arrangement.html:4).

Evidence: [Individual swap succeeded in Custom Mode](audit/2026-11-09/custom-seat-swap-passed.png).

### B08 — Missing favicon

Browser console recorded `GET /favicon.ico → 404`. Add a local favicon and link it in the base template. This has no seating-data impact.

## Checks that passed

- Administrator login with a temporary audit account.
- PDF upload, preview, confirmation and draft generation using invented data.
- A whole-block GTU drag and a valid room swap; source memberships were retained.
- Individual Custom Mode drag/swap with both enrollments changing places as expected.
- A blocked physical seat was unavailable as a destination.
- SID lookup preserved leading zeros.
- A newly generated result with a start more than 24 hours ahead stayed absent from the public list and did not return a confirmed ticket, even after release was explicitly armed.
- Anonymous admin, backup, export and arrangement access redirected to login.
- Missing-CSRF login POST returned 400.
- Mobile homepage and admin pages at a 390px viewport had no full-document horizontal overflow; deliberately scrollable tables/tabs were not counted as defects.
- Excel download succeeded with five synthetic student rows, text SID cells and `@` number formatting.
- Browser PDF printing produced a one-page A4 room chart containing all 25 synthetic enrollments in that room.

Evidence/artifacts: [Excel export](audit/2026-11-09/custom-export.xlsx), [printed room chart PDF](audit/2026-11-09/gtu-room-print.pdf), [mobile board](audit/2026-11-09/mobile-board.png).

## Audit boundaries and cleanup

The audit used independent administrator and anonymous student Playwright contexts on the actual running site. Layouts were checked at 1440×1000, 1600×1800 and 390×844. The small viewport check is not a physical-phone/touch-device certification. Tool-side selector, navigation-wait and scripting errors were excluded from the bug list; the drag findings above are based on persisted server results.

Only clearly labelled `QA-AUDIT-1dcab573` sessions and a classroom with invented enrollments were created. They were used for temporary publication tests, then withdrawn. Existing college sessions were not edited. Other activity occurred during the audit, so cleanup was scoped to exact audit IDs rather than restoring an old database snapshot or deleting everything created since a timestamp.

Cleanup status is recorded in [the machine-readable audit results](audit/2026-11-09/results.json). The temporary account, its active sessions, its two examination sessions, revisions, assignments, preview tokens and classroom are removed on completion. QA audit-log entries are retained and explicitly labelled. Existing college records, including concurrently created examinations, are preserved. Screenshots and exported evidence use synthetic audit data.

The original audit included no fixes; the fixes are recorded above. Original recommended order: **B01 → B02 → B03**, then the roster-correction workflow, release-control clarity and contrast fixes. Add regression tests for the two stale-state defects before considering the existing passing test count evidence of college readiness.
