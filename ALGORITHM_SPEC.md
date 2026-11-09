# Supplied algorithm and integration contract

The archive `exam-seating-engine.zip` is the supplied Astra engine. Its implementation is retained in `engine/`. See [the original engine specification](engine/README.md), [exam JSON Schema](engine/exam.schema.json), and [preset schema](engine/preset.schema.json). This application does not substitute a baseline allocator.

## Interfaces

- `Exam.model_validate(document)` strictly validates v1 configuration. Unknown properties and operators fail.
- `Plan(exam, previous_preview=None)` expands geometry, intersects eligibility, resolves ordering, loads locks and pins, and runs preflight checks.
- `Plan.allocate(seconds=20)` uses verified deterministic greedy allocation, falling back to SciPy MILP when necessary.
- `Plan.verify(assignment)` independently checks a bijection between the roster and physical seats, eligibility, pins, locks, quotas, grouping, neighbors, and ordering.
- `Plan.edit(previous, source, target)` validates a swap or move without changing its input snapshot.
- `Plan.preview(assignment, method)` produces verified physical positions and rule traces.

Imports were adapted to support both package use by Flask and the original standalone CLI. The original allocation, ordering, solver, and verification logic are retained; imports in the supplied test file and CLI were updated for package discovery.

## Physical model

Every row/column intersection is **one bench**. The number of benches is `rows × columns`. Each bench has `seats_per_bench` positions, numbered from 1. Room IDs are stable database keys `R1`, `R2`, etc.; room labels and building names are independent. A full physical key is `R1/row/column/position`. The editor stores the local part `row/column/position`.

Blocked and reserved seats both generate native `blocked` constraints and remain empty. Accessible seats are allocatable physical labels. The engine has no disability/student-accessibility field; automatic accessibility matching is unsupported. Administrators can use a seat-scoped full-SID `allow` rule plus a minimum/exact quota if necessary to require that student in the seat. Merely allowing a SID at a seat does not force it there. A quota for a branch/batch can constrain a single seat; native pins are available to engine CLI consumers. The web builder uses SID allow rules, not native pins.

Bench number on student tickets and exports is `(row − 1) × columns + column`. Seat number is the position on that bench. The chart uses this identical mapping.

## Rule semantics

Native operators: `allow`, `cycle`, `uniform`, `distinct_neighbors`, `quota`, `blocked`, `order`. Scopes can select all rooms, a classroom, row, column, bench (row + column), or seat (+ position). Rule layers are exam/session. Ordering modes: `ascending_sid`, `descending_sid`, `random`, `round_robin`, `low_high`, `explicit`, `suffix`. Full SID strings are case-sensitive. Explicit lists rank the listed SIDs first, followed by other eligible SIDs; they do not restrict the roster. Random ordering always uses a recorded seed for reproducibility.

Hard rules combine; none are silently overridden. Ordering is the only replaceable slot: specificity, explicit room, session layer, then priority resolve precedence. Equal winning overlaps fail. An allowance grants permission; it does not create an obligation. Conflicting quotas or impossible branch restrictions fail rather than relaxing policies.

The app's mixed preset emits a minimum-one quota per observed branch per selected room, so every branch must appear in every room. The branch-column/row presets use uniform grouping; alternating adds distinct neighboring columns. Batch-separated means distinct batch sets on horizontally adjacent benches, as in the supplied preset. Unequal group sizes can make these policies infeasible.

## Resource boundaries

The app permits up to 10,000 physical seats per exam, 250 policy rules, 50 rows/columns and 6 seats per bench. Imports permit 10,000 rows and 5 MB compressed/30 MB expanded workbooks. Solver fallback is bounded to 250,000 eligible seat/student pairs with a 20-second solver deadline. Larger instances use the same supplied greedy placement and verifier; if greedy fails, the app reports a resource limit without constructing the dense solver model. The limit avoids a large dense MILP exhausting an ordinary laptop. Model construction time is not included in SciPy's solve deadline.

Generation is synchronous with visible loading feedback. Complex policies may exceed practical laptop limits; narrow branch eligibility to reduce domains. No partial allocation is stored or published. Successful results must seat every student exactly once; a successful revision therefore has an empty unallocated report. Failed attempts have a readable error log rather than a partial result.

## Persistence and publication

Allocation revisions retain the full engine input, roster metadata, room geometry, verified preview and per-SID indexed assignments. Manual edits and regeneration create new revisions. Approved revisions are immutable through the application. Expected exam versions reject stale changes, including changes during generation. Approval and publication each use a SQLite `BEGIN IMMEDIATE` transaction. Publication points only at an approved revision; release is server-gated to the snapshot’s examination time minus 24 hours, with no manual early bypass. Enabling publication only arms that release; unpublishing disables lookup. Updated metadata applies when generating a new revision; published tickets always use their snapshot.


## GTU mode — supplied rules v2

The user additionally supplied `gtu_room_allocation_rules.md`. New examinations default to GTU mode; existing examinations retain the original engine. GTU's whole-block room packing is a separate algorithm in `services/gtu_engine.py`, dispatched by the snapshot's `mode: "gtu"`. Student-level Astra rules do not apply in this mode.

Blocks are grouped by the exact provided block number, must have one subject each and contain 1–30 enrollments. The full blocks are allocated exclusively first, sorted by block ID. Partial blocks sort by descending size then block ID and use first-fit decreasing: capacity, different subject, and at most four blocks per room. No block is split, extended across import files or synthesized. The configured floor/list sequence maps packed rooms to physical room labels, skipping only explicit unavailable rooms. Every date and shift independently starts with its own saved room pool. The default is 13 rooms × 30 seats = 390.

GTU configuration is saved per examination, with editable global defaults for future sessions. A v1 → v2 transaction adds GTU configuration and receipt storage after making an SQLite backup; it never rewrites old revision JSON. Separate GTU dates/shifts are unique in SQLite. A roster cannot be moved to a different date/shift/time zone after import.

The native CSV/XLSX importer validates the exact six GTU columns, subject consistency, duplicates, block size, available capacity, date/shift references and server-recorded upload time. D−1 is enforced by converting the receipt timestamp to the examination's IANA time zone; D−1 at 23:59:59 passes and exam-day midnight fails. Upload previews retain the real receipt time, and confirmation/generation/approval/export recheck the receipt rule. No optional deadline override is implemented.

A separate independent GTU verifier checks the roster bijection, exact seat keys, all block/subject metadata, unsplit blocks, capacity/block limits, distinct subjects, full-block exclusivity and precedence, continuous available-room order, consecutive seat numbering, contiguous blocks and enrollment ordering. The application invokes it before saving a revision, approving and exporting. GTU revisions use the same atomic approval/publication and protected historical snapshots as the original engine.

The GTU spec defines sequential seat numbers rather than a physical row/bench grid, so GTU tickets and room charts show room, floor, block, subject and 1..N seat numbers. No physical bench coordinates are fabricated. Student-level GTU edits/locks are rejected server-side; whole-block moves and complete room swaps are independently verified before saving. Custom Mode supports individual seat edits. Reports include all requested room/block mappings, attendance and session summaries; browser printing supplies printable door charts/seating plans and PDF saving.


## Native PDF import, visual edits and 24-hour release

`services/pdf_service.py` parses the user's text-based Crystal Reports block-arrangement layout with local Poppler tools. Enrollment numbers come from the PDF's Seat No fields; its Bench No is retained as source provenance. Declared totals, exact bench sequences, duplicate block IDs, duplicate enrollment IDs and all subject/date/shift headers reconcile before preview. Multi-session selection and explicit clock times are handled by `web/pdf_routes.py`. Its import is atomic; draft generation then runs independently per selected session. PDF subject codes are used as names because the supplied report does not contain subject names.

The source PDF contains seven May 2026 sessions, so they import as permanently private historical rehearsals. Only this private PDF workflow may bypass the obsolete live D−1 receipt for past dates; same-day live imports cannot use it. Historical status is included in immutable snapshots and student publication is prohibited. Source dates are preserved. Future live GTU sessions still use their real server-recorded D−1 upload receipt.

`edit_blocks` re-packs the existing complete block memberships into a proposed room map after a whole-block move or room swap. It enforces capacity, different subjects, maximum blocks, full-block exclusivity/precedence, contiguous occupied room order, contiguous positions per block and enrollment ordering through the independent GTU verifier. It does not claim a manual plan remains the original first-fit optimum. Custom Mode continues using the supplied `Plan.edit` and all its hard constraints, with source PDF block/subject/bench labels attached as metadata.

Every revision records `release_at = snapshot.starts_at (UTC) − 24 hours`. Approval with automatic release enabled atomically arms the approved revision with this release time. Public lookup requires approval, an armed publication, a non-historical session, a non-null reached release time, and the current configured exam time also being within 24 hours. Neither manual publication flags nor forged early publication timestamps bypass the gate. Unpublishing is immediate; no background process is needed. Schema v3 backs up v1/v2 databases, preserves original snapshot JSON, and backfills valid old release timestamps; invalid timestamps remain NULL/private.


## Visual rearrangement with direct emergency seats

Direct emergency admissions have explicitly authorized, fixed seat IDs. GTU manual edits build the proposed regular block groups independently, overlay unchanged emergency occupants, and validate the complete physical map plus normal GTU constraints. Supported operations are whole-block moves, two-block interchanges and room-allocation interchanges. Emergency occupants never move with a room header; an incoming regular block that overlaps their confirmed seats is rejected. These edits are available on drafts and through an atomic copy-and-edit of the latest approved board, retaining old approval/publication until review. They do not modify the supplied Custom Mode engine.


## Administrator-selected rooms across floors

Manual GTU edits persist `preview.manual_room_selection: true`, set only by the backend's validated block/room editing path. The independent verifier skips automatic room-prefix filling and global full-before-partial room priority for those snapshots. Full blocks remain exclusive, and all physical room/seat identity, availability, capacity, maximum-block, subject separation, block integrity and within-room order checks remain active. This allows a ground-floor allocation to move to a second-floor room while earlier enabled rooms stay empty, including a full block above a partial block. Automatic allocation emits no override and continues to satisfy the original floor/full-block priorities. Approval and export revalidate the saved policy; generation resets to automatic placement. No database migration or modification of the supplied Custom Mode engine is involved.
