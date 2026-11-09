# Configurable exam seating engine

A standalone Python allocator for one exam session per run. The administrator chooses rules, selectors, presets, pins and a seed in JSON. The engine returns a verified draft for review. No hosted service is required.

## Try the supplied classroom

Use Python 3.10 or later. In the extracted project directory run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v
python cli.py example.json > preview.json
```

Each item in `students` is eligible for this session. Import the full SID, branch and batch as strings if building an Excel adapter. Preserve leading zeros. SID is the identity key. Rows, columns and seat positions start at 1. Each row/column intersection is a bench. Rooms can have different sizes; use blocked rules to describe broken seats, aisles and irregular shapes. The example reproduces all twelve entries of the requested grid.

## Rule builder contract

`exam.schema.json` and `preset.schema.json` are JSON Schemas produced from the actual Pydantic models in `models.py`. Each rule has an ID, a typed payload, an optional scope and an exam/session layer. Unknown versions, properties, or rule types fail validation. Semantic checks also run on the server, including selector matches and cross-field checks. Keep v1 readers when introducing incompatible semantics. New policy combinations use existing operators; introducing a new primitive requires a new typed handler and corresponding solver and verifier support.

| Operator | Meaning |
| --- | --- |
| allow | Occupants must match one of the named branch, batch or full SID values. Multiple allow rules intersect. Allowing ICT in a room does not reserve all ICT students for that room. To confine ICT to one room, exclude ICT from every other room's allowed branches or set its maximum there to zero. |
| cycle | Repeat a list of branches or batches by absolute row, column or seat position. For example, row values ICT, ECE implement A/B/A/B, including across a room with more than two branches on the roster. |
| uniform | All occupied seats of each selected row, column or bench share one branch or batch, chosen by the solver. |
| distinct_neighbors | Neighboring selected columns, rows, or horizontally adjacent benches have disjoint sets of branch or batch values. Room boundaries and gaps break adjacency. An empty group has no values. |
| quota | Inclusive minimum/maximum count for a branch or batch over the whole selector. Use equal bounds for an exact count. For separate counts in several columns or rooms, emit one quota per group. |
| blocked | The position must remain empty. Combine position selectors to model arbitrary unavailable seats. |
| order | Ranks occupants of the effective selected seats, in row-major or column-major traversal, optionally partitioned by branch or batch. |

Omit a coordinate to match every value. A room selector targets a classroom, row or column alone targets a strip, row plus column targets a bench, and adding position targets an individual seat. Selectors with no room apply across rooms. Grouping rules divide selected seats inside each room. Quotas and ordering can intentionally span rooms. Save a scoped rule per room for independent ordering. Several permitted branches in one column allow mixing; add a minimum for each if the mixture is mandatory.

### Change only the ICT ordering

In example.json replace the entire rule with ID ICT-sequence with:

```json
{"id":"ICT-sequence","type":"order","scope":{"room":"A101","column":1},"mode":"random"}
```

Set the top-level seed to 42. Random ranks use SHA-256 over seed, rule ID, group and full SID. The same identifiers and inputs yield the same sequence, even if roster records arrive in a different order. Renaming the ordering rule deliberately changes its shuffle. A required hand-picked sequence belongs in explicit mode. Display suffixes are never used as identity keys.

| Mode | Ranking |
| --- | --- |
| ascending_sid / descending_sid | Case-sensitive full-string lexical order. Use suffix mode for natural numeric suffix sorting. |
| random | Stable seeded permutation with full SID as a final tie-breaker. |
| low_high | Lowest full SID, highest, second lowest, second highest, continuing inward. |
| round_robin | One lexically sorted SID from each lexically sorted batch per round; exhausted batches drop out. |
| explicit | Listed full SIDs first, then other eligible SIDs in lexical order. Unknown or duplicate listed SIDs fail. |
| suffix | Optional preferred numeric suffix list, then remaining suffixes numerically, then full SID for ties. Missing trailing digits in a candidate SID produce an error. |

Ranks are computed over the union of eligible candidates for that effective order region. The occupants must form a subsequence of those ranks. For an exact round-robin cycle of all members, restrict that group to its designated seats. Empty positions are skipped. With a single-seat rule, ordering has no effect on occupant selection; use a pin or eligibility rule to select a student.

## Precedence and safety

All hard eligibility, geometry, quotas, group restrictions, pins, locks and roster invariants apply together, independent of scope or priority. A more specific allowance can narrow the allowed set. Two incompatible hard requirements fail. Order is a replaceable policy slot. Once resolved, the winning sequence is enforced as a constraint, including on manual moves.

Order resolution at each seat compares these keys in order:

1. Seat > bench > row or column > room > unscoped.
2. Within the same geometric level, an explicit room outranks a cross-room selector.
3. Session layer outranks exam layer.
4. Higher integer priority wins. Equal winning priorities on overlapping rules fail with both IDs.

Rows and columns have equal specificity. Each preview position records applied IDs and superseded ordering IDs. Its full rule definitions are stored once in the preview. An allow rule is permission, while a quota creates an obligation.

## Architecture and pseudocode

| Component | Location and responsibility |
| --- | --- |
| 1. Configuration | models.py validates exam, preset, room, roster and discriminated rule payloads. |
| 2. Precedence | ordering.precedence and Plan._orders choose the effective order independently per seat. |
| 3. Student grouping and ordering | ordering.sequence builds full-SID ranks after partitioning candidates. |
| 4. Physical grouping | Cell, Plan.select and physical_groups expand selectors and group seats by room and axis. |
| 5. Assignment | Plan.allocate first fills compatible free seats in traversal and rank order. |
| 6. Search and conflicts | Plan._preflight checks direct conflicts. solver.solve handles overlapping constraints using sparse mixed-integer linear programming. |
| 7. Manual operations | Plan._locks, pins and Plan.edit preserve protected positions and validate a copied candidate map. |
| 8. Verification | Plan.verify checks roster bijection, eligibility, protected seats, counts, neighbors and ordered subsequences before Plan.preview returns a grid. |

```text
validate exam + preset rules; expand rooms into physical seat IDs
load approved occupants/empties for locked scopes; reconcile pins
intersect hard eligibility; resolve ordering rules; compute candidate ranks
check quota capacity, protected placements and total usable seats
fill unlocked seats deterministically; verify complete map
if greedy verification fails:
    build binary x[seat, eligible SID] with exactly one seat per student
    enforce occupancy <= 1, pins, quotas and branch/batch group indicators
    enforce monotone rank through occupied seats of each ordered group
    minimize summed seat index to prefer earlier physical positions
    distinguish proven infeasibility from time/resource limits
independently verify candidate; emit grid + rule trace or structured error
```

The fast path stops after finding a verified feasible layout. Compactness is a secondary objective of the fallback only. A search deadline applies to solver execution after model construction. The fallback can require one variable per allowed student/seat pair, up to S × P for S students and P seats. A dense thousand-student instance with coupled policies can be expensive. Scope branches to rooms where appropriate. For repeatable deployments pin the Python/SciPy solver environment; tied optimal layouts can vary across solver versions. A timed-out solve never publishes a partial result.

For a quota of 40 ICT students in ten usable positions, preflight reports the rule ID, required count, and ten available seats. The CLI exits with status 2 and a JSON error on stderr. Joint infeasibility reports the active rules and fixed seats for review. That list is a candidate set, not a minimal conflict explanation.

## Saving, applying and editing

Save a custom preset as a named JSON file containing version and rules, in the format of the eight examples in presets/. Apply with repeatable `--preset PATH` arguments. Rules combine with those already in the exam; duplicate IDs are rejected. Start with an empty rules list to try individual presets. Scope names, branch labels and quota sizes in sample presets are editable. A future admin panel can store those same documents and snapshot the expanded exam policy per published revision.

To pin a student, add `"pins":{"A101/1/1/1":"ICT-001"}` to the exam. To preserve an entire approved room, add `"locks":[{"room":"A101"}]` and supply its previous preview. Use a row, column, bench or position selector for narrower approvals. Locks preserve empty seats too. Prior locked flags carry forward. An intentional unlock requires an explicitly revised approval snapshot with the corresponding flags cleared and matching pins/lock selectors removed.

```bash
python cli.py updated-exam.json --previous preview.json > regenerated.json
python cli.py updated-exam.json --previous regenerated.json --swap A101/1/1/1 A101/2/1/1 > edited.json
```

The second command is a swap when both seats are occupied or a move when the target is empty. Strict ordering may reject it. Keep the original snapshot until a new command succeeds. Manual edits have no implicit power to override hard rules. To preserve a newly approved layout on subsequent regeneration, lock the approved scope. A future multi-admin service should atomically publish a verified snapshot against its expected revision and reject stale edits. This module operates on in-memory snapshots; publication, authentication and Excel import belong to the application layer.
