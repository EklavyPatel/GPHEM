# GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT

The issues in [BUG_REPORT.md](BUG_REPORT.md) have been addressed with regression tests. Restart the Python process after updating; the already running process does not reload new routes automatically.

A local Flask + Jinja application with vanilla JavaScript, SQLite persistence, GTU whole-block room allocation, Excel imports/exports and the **supplied Astra seating engine** from `exam-seating-engine.zip`. There are no cloud services, frontend frameworks, default administrator credentials, or publication of unapproved drafts. Approved live results default to release 24 hours before the exam; administrators can change the release date and time.


## Institute identity, student notice and block register

The student search and printable result pages show **BEST OF LUCK** and the notice: “The exam management system is currently under testing. Please verify your seating arrangement on the institute notice board.” The supplied institute logo appears in student/admin headers and the block register. The original JPEG is used faithfully. An AI cleanup draft changed Gujarati lettering, so it is retained only for review and is not displayed as the official logo. See [logo notes and exact restoration prompt](design/LOGO_NOTES.md).

Open **Block–classroom register** in the administration sidebar, dashboard or an examination's navigation. One consolidated page shows examination date/time and shift, block, subject/branch, building/floor, classroom, student count and approved revision. It uses immutable saved allocation snapshots, so the mapping remains available after the examination and after working metadata/room settings change. Choose one exam or all exams, print/save PDF, or download Excel. A split source block has a row for each actual classroom. Emergency admissions are listed separately. Drafts are excluded unless explicitly requested; an existing approval is always preferred. Large registers remain on one web page and may require multiple printed sheets for legibility. This administrative report does not publish student lists.

**Activity log → Delete logs** deletes selected events or all events that existed when the page loaded (including older rows beyond the latest 500 displayed). Type `DELETE` and confirm. Newer concurrent events are preserved. Deletion itself leaves one new event identifying the administrator and the number removed; exam/student/assignment records are not removed by this action. Back up the database before deleting history. Deleting an examination separately also removes its allocation register, so export the register before removing past exams.

## Deploy from GitHub

The application source is prepared for Python hosting. [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) explains the source-only upload and authentication requirements. See [DEPLOYMENT.md](DEPLOYMENT.md) for the production start command (`python serve.py`), persistent SQLite disk, PDF system packages, HTTPS settings and first administrator setup. GitHub Pages cannot run this Flask server. No local college database or student PDF is included in the repository.

## Install and start

Python **3.12 or newer** is required. Python 3.12/3.13 are sensible choices with broadly available SciPy wheels. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app create-admin
python app.py
```

On Windows use `py -3.12 -m venv .venv` and `.venv\Scripts\activate`. The administrator command prompts for a username, a password (at least 12 characters), and password confirmation. Passwords are hashed with Werkzeug's scrypt implementation. Setup is local CLI only, so a visitor cannot claim an unconfigured installation. No production credentials are embedded in source.

Open **http://127.0.0.1:5000/** for students and **http://127.0.0.1:5000/admin** for administrators. The SQLite database is initialized at `instance/seating.sqlite`; it is persistent across restarts. Back it up before changing application/database versions. The current schema version is 5. Existing v1/v2/v3/v4 databases are upgraded transactionally, with a consistent `*-before-gtu-*.sqlite` or `*-before-pdf-*.sqlite` backup saved beside the database first. Existing accounts, examinations, approved revisions and publication pointers are preserved; old sessions retain their original mode. The release gate is checked on the server for every lookup. Existing immutable approvals are preserved. Original PDFs uploaded in older versions were not retained: use the revised-PDF workflow to store them for room-number export.

Optional unpublished demo:

```bash
flask --app app seed-demo
```

This requires an empty examinations database. It creates the supplied algorithm's 12-student roster and one classroom with blocked, reserved and accessible seats. It does not create credentials, generate seats, approve, or publish anything.

Local password recovery:

```bash
flask --app app reset-password
```

This revokes all browser sessions.


## Drag an emergency student onto an empty seat

In **Visual arrangement**, enter the student's details in **Add an emergency student to an empty seat** and click **Prepare student to drag**. A floating student card stays visible as you scroll through rooms. Drag it onto an empty seat, or tap an empty seat / choose one from the dropdown. Confirm the displayed student, exact seat and publication effect.

The server validates the entire arrangement and saves the student, new revision, approval and publication changes in one transaction. Existing students keep their exact seats. When the displayed arrangement is approved, confirmation creates an approved revision immediately. When that revision was published, its published pointer updates too, preserving the release time and publication state. A private approval stays private, and a draft stays a draft. Previous revisions remain available in history. Cancelled, occupied, blocked, locked, duplicate, stale or rule-breaking drops leave the database unchanged.

**No block number is required for direct emergency placement, including GTU/PDF sessions.** Enter the SID and any available name, branch, batch/year or subject details, select any available empty seat and confirm. GTU direct placements are explicitly authorized exceptions to normal block membership, subject separation, floor-fill and enrollment-order rules. Their exact seats and administrator authorization are stored, and they are labelled **Emergency admission** on the board, seat information and attendance report. Regular GTU students retain their rules and positions. Capacity, availability, unique SIDs and physical seats remain mandatory for everyone.

GTU regeneration preserves fixed emergency seats; if a new regular allocation conflicts with them it fails without replacing the earlier result. Whole-block moves, block-to-block swaps and room-allocation swaps remain available with emergency seats present. Those students keep their exact confirmed seats; moves that overlap them are rejected. Further direct emergency additions remain available. Custom Mode still checks its configured seating rules. The reviewed roster workflow below remains available for official block-based roster corrections.

## Manual moves between floors

In **Visual arrangement**, move a block or interchange room allocations between any enabled rooms, including **721 on the Ground Floor → 761 on the Second Floor**. You can leave earlier rooms empty. Manual selection also permits a full block above a lower-floor partial block, while keeping that full block exclusive to its room.

Automatic generation still follows the configured floor order and fills full blocks first. Manual revisions record an administrator-selected room policy; their validation report identifies this override. Capacity, room availability, whole blocks, different subjects, maximum blocks per room, contiguous within-room seating and enrollment order still apply. Emergency students stay in their confirmed seats, so a move that overlaps one is rejected. Approved/publication snapshots remain unchanged until you review and approve the new draft. Official roster amendments retain a saved manual room policy; generating afresh uses automatic placement priorities again.

## Emergency admissions, corrections and deletion

- For changes requiring repacking or an individual record correction, open **Visual arrangement → Edit roster / review larger changes** (also available under **Late admissions & corrections**). Add a late student or select **Edit record**, supply an authorization/correction reason, and create a draft. This works after approval and publication. The backend rejects duplicates, invalid subjects, impossible blocks and insufficient capacity. A failure rolls back both the roster and draft changes. Actual receipt timestamps are retained; authorized late GTU receipts carry the administrator and reason instead of a fabricated D−1 timestamp.
- Existing Custom Mode seats are preserved by default; GTU preserves block rooms where possible while maintaining enrollment order. Check **Allow repacking** if new capacity/subject constraints require existing assignments to move. The result reports how many existing students moved. Review the full visual board, make permitted adjustments, and approve. Automatic release switches the published pointer atomically; otherwise enable release explicitly. The earlier publication stays available while the new draft is reviewed.
- To replace an official PDF list for the **same date and shift**, choose **Upload revised PDF**. Preview the entire replacement, including added/removed counts, then confirm. Only that session changes; other sessions in the PDF are not imported by this action. Stale previews are rejected. Old approvals and their original source PDFs remain available through revision history.
- Download **Original PDF with room numbers** from the visual arrangement. The original pages are retained and their Room No blanks are filled for the selected revision. **Fill all linked sessions in source PDF** also fills other linked sessions, preferring their approved revision and using a labelled draft when no approval exists. Unimported sessions remain unchanged. Each annotated page identifies revision status. This needs **Ghostscript** and Poppler (`sudo apt install ghostscript poppler-utils` on Debian/Ubuntu); on other systems add both tools to PATH. No upload leaves the computer.
- This is a room-blank annotation of the original roster. Emergency students and record corrections are reflected in the current allocation/attendance report, not inserted into the original PDF's student table. Print/export that report as the supplement. If Custom Mode splits one source block among rooms, the app refuses to put a misleading single room into its blank; use the allocation report.
- Change release date/time in **Overview & settings**. Changing examination title, start, time zone or public-name permission withdraws the stale publication; regenerate, review and approve to release the updated details. Old snapshots retain their historical details.
- **Delete examination** is at the bottom of **Overview & settings**. Type the exact title and confirm. This permanently removes that session's roster, revisions and publication; other examinations and audit history remain. Download a SQLite backup first. A PDF shared by other sessions is retained; sources no longer referenced by sessions, history or unexpired private previews are removed.

The schema upgrade creates a consistent backup beside the database before migration. Private PDF previews expire after 30 minutes; original sources linked to approved/history revisions persist in SQLite and are included in backups. No Python dependency is added for room-number annotation.

Student lookup now permits 60 requests/minute per browser session with a separate 6,000/minute network ceiling, avoiding the previous shared 30/minute campus quota. New cookies do not bypass the network ceiling. Client IP forwarding headers remain untrusted by default; configure a trusted reverse proxy for the real deployment and load-test the expected release burst.

## Upload the GTU PDF directly

The app is branded **GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT**, with **made by Eklavy Patel** in the corner. The original supplied allocator is presented as **Custom Mode** in the interface; its implementation is retained.

1. Sign in and choose **Upload GTU PDF** on the dashboard or **Import GTU PDF** in the sidebar.
2. Choose the original text-based GTU block-arrangement PDF, GTU mode or Custom Mode, time zone and the real morning/afternoon examination start times. The PDF supplies AM/PM but not an exact clock time. For Custom Mode select your configured physical classrooms.
3. Review the extracted dates, shifts, block counts, enrollment counts and source bench/page information. Correct any selected start times. Only explicitly checked, valid sessions are imported; a session that already exists in GTU mode is never overwritten.
4. Choose **Confirm import & generate arrangements**. All selected sessions are imported atomically, then draft arrangements are generated independently. Any generation failure is reported without replacing existing approved results.
5. Open a session's **Visual arrangement**. Every room displays its student IDs, assigned positions and block/subject labels. GTU mode moves complete blocks or swaps whole rooms. Custom Mode swaps individual unlocked seats, while retaining original PDF block labels. Every edit is checked by the backend and saved as a new draft revision. Keyboard/touch controls are available when HTML drag-and-drop is unavailable.
6. Review and approve. With automatic release enabled (the default in the PDF form), the approved arrangement becomes visible to students **exactly 24 elapsed hours before the exam start**, or immediately after approval if already within that window. It cannot be exposed earlier by editing publication time or clicking an enable/publish action. Unapproved drafts remain private. The laptop/server must be running when students access it; no separate scheduler is required.
7. Use **Print all rooms / Save PDF** for the complete visual board, or the per-room door chart/attendance print view for a compact PDF. Select “Save as PDF” in your browser. Reports also download as text-safe Excel workbooks.

PDF extraction runs locally through Poppler (`pdftotext` and `pdfinfo`). These tools are already present on the current machine. On Debian/Ubuntu install them with `sudo apt install poppler-utils` if needed; on another OS install Poppler and add both executables to PATH. No Python dependency was added for PDF import. Scanned/image-only PDFs need OCR first and are rejected with a clear message, not guessed.

The supported layout is the supplied GTU Crystal Reports report with **Subject Code, exam date, AM/PM, Block No, Room No, enrollment/bench pairs and Total**. Every block total and the exact 1..N source bench sequence must reconcile, and unrecognized headers cause the whole PDF to fail validation. Limits are 5 MB, 100 pages, 2,000 blocks, 100 sessions and 10,000 enrollments per PDF. Enrollment strings and source bench/page numbers are retained; the PDF does not provide subject names, so subject codes serve as labels. Source room labels, if present, are replaced by new allocations according to the chosen mode.

**The supplied May 2026 PDF is historical.** Its 24 pages contain 103 blocks, 1,663 enrollments and seven morning sessions. As these dates have passed, import keeps their original dates and creates **private historical rehearsal arrangements**. They may be edited, approved privately, printed and exported, but can never publish to students. The source dates are never silently moved into the future, and the source's printed creation date is never mistaken for an actual upload receipt. Future live GTU sessions continue to require an upload on or before D−1; same-day uploads do not get the historical exception. Custom Mode can use a different seating policy.

Historical/private status cannot be changed into a live publication through the settings form. For a real future exam upload its actual current GTU report. Existing JSON allocation snapshots and approval pointers survive the v3 migration; release timestamps are derived from their recorded examination times and missing/invalid timestamps fail closed.

## GTU room allocation (default for new examinations)

The supplied [GTU room allocation rules v2](gtu_room_allocation_rules.md) are implemented as a dedicated **GTU mode**. The unit of allocation is an existing, subject-wise GTU block. The original Astra engine remains available through **Custom Mode** and continues to serve existing examinations.

1. Restart the application after updating the source: stop it with Ctrl+C, then run `source .venv/bin/activate` and `python app.py` from this directory. The database upgrade and backup happen automatically. No reinstall or database reset is needed.
2. Choose **New examination → GTU — ready-made subject blocks → rooms**. Enter the examination date/time, time zone and **morning/afternoon** shift. There can be one GTU session for each date + shift. Existing students cannot be reassigned to a different date/shift by editing the session.
3. Open **GTU room rules** to inspect the saved floor order, capacity and room availability. The default sequence is `721, 722, 723, 724, 725, 731, 732, 733, 734, 761, 762, 764, 765` (390 seats). Disable a room to skip it for this session only. All rooms are available again for other dates/shifts. **GTU room defaults** in the sidebar configures the defaults copied into future sessions; it does not change existing sessions.
4. In **GTU blocks & students**, download the session-specific template or upload a UTF-8 `.csv` / `.xlsx` containing the exact headers below. Upload **on or before D−1** in the examination time zone, preview the validation report, then confirm. Exam-day and late uploads are blocked; no deadline override is enabled.
5. Choose **Allocate GTU blocks to rooms**. Full blocks receive their own rooms first. Smaller blocks are sorted largest-first and packed into the first compatible open room, then rooms are mapped in floor/list order. Every block stays together and enrollments are sorted within it. Block-ID lexical order breaks size ties and orders full blocks so the result is deterministic across input row order. This implements first-fit decreasing, not a claim of globally minimum room count.
6. Open **Visual arrangement** to see every room, student and block. Drag one block onto another to interchange them, onto a room to move it, or drag room headers to interchange their regular block allocations. Emergency students stay in their confirmed seats; all other GTU constraints remain enforced. Use the keyboard/touch controls as an alternative. Approve the reviewed draft: if automatic release is checked, it is armed for the configured release time (24 hours before the exam by default). Students search with their full enrollment number. Individual seat swaps and locks use Custom Mode.
7. Download GTU Excel reports (room-wise list, block → room mapping, attendance sheets, utilization, session summary and validation). **Print door chart / save PDF** uses the browser print dialog for the current room's door chart and seating/attendance list; select “Save as PDF” to create a PDF.

GTU columns:

| exam_date | session | block_no | subject_code | subject_name | enrollment_no |
| --- | --- | --- | --- | --- | --- |
| 2099-11-09 | morning | GTU-001 | 3110001 | Mathematics | 0012345678 |

Use ISO dates (`YYYY-MM-DD`) or real Excel date cells; shift values are exactly `morning` or `afternoon`. Store enrollments as Excel **Text**, including leading zeros. A file targets one date/shift; rows for another session are rejected, not routed silently. Each block must have exactly one subject and at most 30 members. The same enrollment may appear in different shifts, but cannot appear twice in one session. Import each complete block once: later files may add other complete blocks, but cannot extend an imported block. The app cannot infer omitted members from GTU's source list, so administrators must supply the complete authoritative blocks.

A room holds at most **30 students and four different-subject blocks**. Two blocks of the same subject code cannot share a room (subject code comparisons ignore letter case). A full 30-student block gets an exclusive room. Four blocks of three students fill a room's block limit at 12 students, leaving 18 seats empty. Seat shortage and room shortage from packing restrictions are reported separately. Capacity is derived from the editable active room list, so disabling rooms reduces it; the default is 13 × 30 = 390. Local room capacity/block limits may be tightened below 30/four but cannot exceed the GTU limits. Editing room configuration never splits a block to make it fit.

GTU seats are numbered **1..N per room** with each block consecutive. The spec does not define physical bench/row coordinates, so GTU tickets and charts display the actual room, floor, block, subject and seat number without inventing a grid. GTU room configuration is separate from the legacy physical classroom editor.

Examples: [GTU CSV roster](examples/gtu_blocks.csv), [GTU Excel roster](examples/gtu_blocks.xlsx), [default room configuration](examples/gtu_room_config.json). These example rosters use **2099-11-09 / morning** to remain suitable for testing the D−1 restriction. Change their date and shift to match your real session, or use its downloaded template. The samples have 82 enrollments in six supplied blocks (30, 17, 13, 10, 9, 3), producing rooms 721/722/723 with 30/30/22 students and eight vacant seats in used rooms. Session reports distinguish vacancy in used rooms from remaining capacity across the whole room pool.

## Custom Mode workflow

1. Sign in and choose **New examination → Custom Mode**. Enter its title, local date/time and IANA time zone (default `Asia/Kolkata`).
2. Create reusable classrooms in **Classrooms → Add classroom**. A row/column intersection is a bench. Set dimensions, apply them, and paint blocked, reserved or accessible seats. Save the layout.
3. On the examination overview, select participating classrooms and save settings. This selection defines availability for that session. Benches and usable capacity are derived from the physical layout.
4. In **Students**, download the session-specific Excel template, fill in the roster and upload it. Map different column headings if needed. Review the preview; fix all errors before confirming. Imports append new records and reject duplicate SIDs already in the same session. The same SID may occur in a different examination.
5. In **Seating rules**, choose a preset, add scoped rules or edit the engine's native rules array. Save the policy and seed. A unique preset name also saves it for reuse in other sessions. Save settings before generation.
6. Choose **Generate new draft**. Loading feedback remains visible while the backend checks capacity, executes the engine and verifies all hard constraints.
7. Review **Seating preview**, select a classroom and inspect each bench. Select an occupied source, then another unlocked seat, to swap or move. Select one seat to toggle its lock. **Regenerate unlocked seats** preserves locks, including empty locked seats. Every change is validated on the server and saved as a new revision.
8. Approve the reviewed draft. Approval is a separate transaction; results remain private until the configured release time, even if release is armed.
9. When automatic release is checked, approval arms the snapshot for its configured release time. Otherwise choose **Enable student release** after approval. Change **Overview & settings → Student release date & time** to choose an earlier or later release, up to the exam start. An override is recorded in the audit log. Switching automatic release off disables current student access, including an already armed publication. Student visibility is checked on the server on every request; no background scheduler or open browser is necessary. **Unpublish results** disables access immediately.
10. Students select a published session and enter their full SID. They can print their individual seat information. They never receive a public roster.

Approved results cannot be edited in place. **Create editable copy of approval** makes a separate draft while retaining the approved and published snapshots. Visual arrangement can create that copy automatically when you drag the current approved arrangement: confirm the move, review its new draft, then approve/release it. A rejected move rolls back both the copy and edit, leaving no partial draft. Generating a new draft also retains prior approval/publication. Historical revisions remain inspectable and exportable. A failed generation or swap leaves previous results intact. Stale tabs are rejected using examination and room version checks.

## Excel format and validation

Required columns:

| SID | Student Name | Branch | Batch | Year | Examination / Session |
| --- | --- | --- | --- | --- | --- |
| 001 | Example Student | ICT | 2024 | 2 | Exact examination title or ID |

- **Store SIDs as Excel Text**, including leading zeros. Numeric SID cells are rejected instead of guessing a lost prefix. SIDs remain exact and case-sensitive; whitespace around them is rejected rather than silently trimmed.
- The selected worksheet is the workbook's active sheet. Header matching is exact after trimming headings; custom mappings must use distinct columns.
- Every field is required. Formulas, cell errors, unexpected cell types, duplicate SIDs, wrong session references and malformed archives produce visible errors. Completely empty rows are ignored.
- Upload limit: 5 MB workbook (6 MB total HTTP request), 30 MB expanded ZIP content, 1,000 archive entries, 50 columns, 10,000 data rows. Macro-enabled/encrypted content is rejected. `defusedxml` hardens XML processing.
- Preview displays the first 50 submitted records and first 50 errors; **Download validation report** includes all records and errors. Nothing is imported until every record is valid and the administrator confirms. Previews expire after 30 minutes and belong to the uploading administrator.
- Existing student rosters are append-only through this version's UI. For corrections after a confirmed import, create a corrected examination session; a student edit/delete UI is not implemented. There is no silent replacement of approved roster data.

Ready-to-open examples: [student_template.xlsx](examples/student_template.xlsx), [example_students.xlsx](examples/example_students.xlsx). The sample workbook's session is `Semester Examination — Demo`; use the live download for other session titles. Sample layouts: [classrooms.json](examples/classrooms.json). Example presets: [rule-presets.json](examples/rule-presets.json). Layout JSON examples are reference documents; create/edit rooms through the visual editor.

## Rules and engine integration

See [ALGORITHM_SPEC.md](ALGORITHM_SPEC.md) and the [supplied engine documentation](engine/README.md). The original engine has strict Pydantic models, scoped selectors, reproducible ordering, hard constraint verification, manual moves, protected seats and SciPy MILP fallback. Package imports were adjusted; allocation/verification logic is retained.

The visual editor supports all seven native rule operators and ordering modes, with examination/classroom/row/column/bench/seat scopes, policy layers and ordering priorities. The advanced JSON editor uses the same native rule list schema. Invalid or unsupported operators fail server validation. Rules are syntax-checked on save; generation checks selectors and joint feasibility against actual rooms/students.

Preset meanings are explicit:

- **Sequential / random:** full-SID ascending or seeded random order.
- **Branch-wise columns / rows:** uniform branch within every occupied column or row.
- **Alternating branches:** uniform columns with different branches in neighboring columns.
- **Mixed branches:** minimum one student of each observed branch in each participating classroom; insufficient counts or capacity cause an error.
- **Batch-separated:** different batch sets on horizontally adjacent benches, matching the supplied engine preset.
- **Custom:** starts with an empty policy. Add allowed branches, explicit cycles, ordering, quotas and scoped constraints.

Custom SID ordering supports sequences such as `001, 013, 003, 025`; listed SIDs rank first, then remaining eligible SIDs. It is not a roster filter. Multiple allowed branches permit mixing; add quotas to require representation. An allow rule does not force a student/branch to occupy its scope. Restricting ICT to one room requires excluding ICT from other rooms. Hard rules intersect and can make a configuration impossible. Manual swaps cannot override ordering or other hard rules.

**Physical/accessibility limits:** benches form a rectangular grid; blocked seats model aisles and irregular shapes. Accessible is an available seat label; the engine has no student accessibility attribute and automatic accessibility matching is unsupported. The web rules UI supports seat-scoped SID eligibility; native pin dictionaries and lock scopes are supported by the engine CLI but are not an editable web configuration field. Use the chart to move a student into an eligible accessible seat and lock it before regeneration. Backend validation still applies.

**Resource limits:** at most 10,000 physical positions per exam, 250 policy rules, 50 rows/columns and 6 seats per bench. Dense coupled constraints can make a MILP expensive. The integration uses the supplied verified greedy path for large instances and refuses solver fallback above 250,000 candidate pairs. Solver time limit is 20 seconds; model construction is additional. Large failed greedy cases report a resource-limit message rather than claiming impossibility. Narrow room/branch eligibility or simplify rules. Generation is synchronous; a background job queue and animated progress percentages are not included. The UI shows a working state, not an invented progress value.

The successful allocation contract is all-or-nothing. Every student must receive exactly one valid seat. The unallocated sheet is therefore empty for successful revisions; failed attempts appear in the examination's generation error log.

## Reports and printing

Every allocation export includes **Complete allocation**, **Room-wise lists**, **Branch-wise lists**, per-room **Attendance** sheets, **Classroom utilization**, **Unallocated students**, **Allocation validation** and the examination metadata. SIDs and all untrusted strings are explicitly written as text, preventing Excel formula injection. The exported revision is independently verified again. Export any historical revision from its chart or the overview's history.

Use **Print room chart** on each classroom's seating preview for a landscape A4 chart. Students can use **Print seat information** after lookup. The browser print dialog can save PDF. Charts reflect the snapshot's physical layout, with blocked seats, empty seats, locks and accessibility labels.

## Security, persistence and operations

- Opaque random session cookies refer to server-side SQLite records; only token hashes are stored. Cookies are HttpOnly and SameSite=Lax. Login rotates sessions; logout/password recovery revoke them. A concurrent request cannot recreate a revoked session. Default expiry is two hours; modified sessions refresh it.
- All state-changing forms, including sign-in and public lookup, require a CSRF token. Admin routes verify the logged-in administrator on every request. All administrators currently have the same role; delegated permissions/SSO/MFA are not included.
- Login limits: 10 attempts per five minutes per source IP and per username. Public searches: 30 per minute per source IP. Counters persist in SQLite and are shared by workers. Do not enable forwarding-header trust without a known reverse proxy; forwarded client IPs are ignored by default.
- Public lookup is POST-only for SIDs, uses an indexed `(revision_id, sid)` query, enforces approval/publication on the server and displays only one exact SID result. Names are hidden unless enabled in the allocation snapshot. SID lookup is a modest privacy boundary rather than identity verification: someone who knows a SID can view its published seat. The college should decide whether stronger student authentication is required.
- Browser responses use no-store caching, a restrictive same-origin CSP, anti-framing, MIME sniffing prevention and no-referrer headers. No third-party fonts, scripts or analytics are used. These controls follow [Flask's security guidance](https://flask.palletsprojects.com/en/stable/web-security/).
- SQLite uses foreign keys, uniqueness constraints, WAL, a busy timeout and explicit write transactions. Allocation publication updates a pointer to an approved immutable snapshot atomically. Assignments have unique SID and physical seat constraints within each revision. Exam version checks reject stale generation, approval and manual updates.
- The audit log records sign-in/out, imports, settings, rules, generation failures, revisions, approvals, publication, exports, backups and CLI recovery.
- Database and instance directory permissions are restricted on POSIX. Protect the host OS account, network and backup storage.

The **Activity log → Download SQLite backup** action uses SQLite's backup API to create a consistent snapshot including configuration, roster data, revisions and password hashes. Store this sensitive file securely. To restore, stop the server, keep the old database as a backup, replace `instance/seating.sqlite` with the downloaded file, remove obsolete `-wal` and `-shm` sidecars only after shutdown, and restart. A backup can contain active sessions; run `flask --app app reset-password` after recovery to revoke sessions. Test restoration periodically.

Configuration via environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `COLLEGE_NAME` | Your College | College name in headers; logo is a placeholder |
| `SEATING_DATABASE` | instance/seating.sqlite | Absolute database path; parent directory must exist |
| `COOKIE_SECURE` | 0 | Set `1` when served through HTTPS |
| `TRUSTED_HOSTS` | unset | Comma-separated allowed hostnames for a deployed instance |

For a small production installation use Waitress instead of Flask's development server:

```bash
# Set real values for your deployment; keep the database on a local durable disk.
export COLLEGE_NAME='Example College'
export COOKIE_SECURE=1
export TRUSTED_HOSTS='exams.example.edu'
waitress-serve --host=127.0.0.1 --port=8000 --call app:create_app
```

Terminate HTTPS at a configured reverse proxy. Use `COOKIE_SECURE=0` only for local HTTP development. Do not expose Flask debug mode. Keep SQLite on one host's durable local disk (not a shared network filesystem) and take backups. Multiple threads/workers on that host share SQLite rate limits; intense write concurrency remains a SQLite limitation. This is a small-college application, not a multi-tenant platform.

## Tests and verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The suite includes the supplied 13 engine tests, large generated datasets (10/100/1,000/5,000 students), irregular/blocked layouts, ordering conflicts, duplicate detection, Excel validation and text preservation, secure sessions/CSRF/rate limits, classroom/rule management, imports with explicit confirmation, manual swaps/locks, revision safety, approval, default 24-hour and configurable publication, privacy, reports and backup restoration. Tests use temporary databases and generated workbooks. The application tests use Flask's real test client and SQLite, not mocked allocation responses.

See [VERIFICATION.md](VERIFICATION.md) for the latest complete test results, including GTU integration and v1 database migration checks, and the browser verification limit.

## Free hosting considerations

A college laptop or existing campus Linux machine can run the application without hosting fees. For any free Python hosting plan, verify current support for Python/SciPy and **persistent writable storage** first. Some free plans sleep, delete local files or provide ephemeral disks; those are unsuitable for the authoritative SQLite database. Sleeping also delays student access even though the publication gate itself is server-enforced. This repository includes a production entry point and hosting instructions; uploading it to GitHub does not itself deploy a live site or create cloud storage. Use campus hosting or a plan with a durable local volume, HTTPS, backups and a stable process. Exact vendor limits change, so no particular free provider is guaranteed here.

## Project map

```text
app.py                         Flask factory, routes, first-run/recovery/demo CLI
engine/                        Supplied models, allocator, ordering, solver, schemas and tests
services/db.py                 SQLite schema and transactions
services/security.py           Server-side sessions, CSRF and shared rate limits
services/excel_service.py      Bounded preview-first workbook validation
services/room_service.py       Physical geometry validation and capacity
services/allocation_service.py Engine adapter, immutable snapshots and approval
services/export_service.py     Text-safe Excel reports
services/gtu_engine.py         GTU whole-block first-fit decreasing and independent verification
services/gtu_import_service.py Native GTU CSV/XLSX validation and D−1 deadline checks
services/gtu_service.py        Session/default GTU config and roster snapshot adapter
services/gtu_export_service.py GTU reports, attendance and native Excel templates
services/pdf_service.py        Bounded local Poppler extraction and strict GTU PDF parsing
services/publication_service.py UTC default and administrator-configured release boundary
web/pdf_routes.py              Multi-session PDF preview, import and draft workflow
static/css/                    Responsive administration/student/print styles
static/js/                     Layout/rule editors, seat selection and loading feedback
templates/                     Jinja student and administrator screens
tests/                         Engine scale and application/Excel tests
examples/                      Real Excel examples, room layouts and rule presets
instance/                      Local runtime database, ignored from version control
```
