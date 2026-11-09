# GTU Exam Room Allocation – Rules & Implementation Spec (v2)

## 1. Scope

GTU provides **ready-made, subject-wise blocks** (up to 30 students each). The application does **not** create, split or change blocks. It only **allocates rooms to blocks**.

> **Unit of allocation = one GTU block.** A block is never split across rooms.

---

## 2. Configuration

```json
{
  "room_capacity": 30,
  "max_blocks_per_room": 4,
  "floors": [
    { "order": 1, "name": "Ground Floor", "rooms": [721, 722, 723, 724, 725] },
    { "order": 2, "name": "First Floor",  "rooms": [731, 732, 733, 734] },
    { "order": 3, "name": "Second Floor", "rooms": [761, 762, 764, 765] }
  ]
}
```

- Fill sequence: `721, 722, 723, 724, 725, 731, 732, 733, 734, 761, 762, 764, 765`
- 13 rooms × 30 = 390 seats per session
- Keep config editable; do not hardcode.

---

## 3. Rules

| # | Rule |
|---|------|
| R1 | Blocks are ready-made from GTU, subject-wise, up to 30 students. App allocates **rooms only**. |
| R2 | Maximum **30 students per room**. |
| R3 | A block of **30** students gets a room to itself. |
| R4 | Blocks with **fewer than 30** students may be **merged into one room**: the other block must be of a **different subject** and its size must fit in the **remaining seats** (30 − students already in the room). Maximum **4 blocks (subjects) per room**. Example: a 13-student block leaves 17 seats, so any other-subject block of **17 or fewer** can join. |
| R5 | A room can hold fewer than 30 students if the merge limits are reached. Example: 4 blocks of 3 students = one room with 12 students. |
| R6 | Rooms: Ground 721–725, First 731–734, Second 761, 762, 764, 765. |
| R7 | Allocation **starts from the Ground Floor**, then First, then Second. |
| R8 | Block-wise student list must be **uploaded the day before the exam**. |
| R9 | **Rooms are reused** as required: each exam session (date + shift) is allocated independently from the full room list. |

---

## 4. Inputs

Block-wise student list (uploaded D-1), CSV/Excel:

| Column | Description |
|--------|-------------|
| `exam_date` | Date of exam |
| `session` | Shift (morning/afternoon) |
| `block_no` | GTU block number |
| `subject_code` | Subject code |
| `subject_name` | Subject name |
| `enrollment_no` | Student enrollment number |

Derived: `block_size = count(enrollment_no)` per `block_no`.

---

## 5. Algorithm (per exam date + session)

1. **Validate**: upload done on/before D-1; no duplicate enrollment numbers in the session; each `block_size ≤ 30`; total students ≤ 390.
2. **Split blocks into two lists**
   - `full_blocks` : size = 30
   - `partial_blocks` : size < 30
3. **Full blocks**: each gets its own room.
4. **Partial blocks**: sort by size descending, then pack (first-fit decreasing):
   - Place the block in the first open room where `size ≤ 30 − used` (remaining seats), `blocks_in_room < 4`, **and the block's subject is not already in that room**.
   - If none fits, open a new room.
5. **Assign physical rooms**: map the resulting rooms in the fill sequence (721 first) per R7. Do not skip an earlier room.
6. **Seat numbers**: 1..N in each room; keep each block's students together, ordered by enrollment number.
7. **Reset for the next session**: all 13 rooms become available again (R9).

### Examples

| Blocks (sizes) | Result |
|----------------|--------|
| 30, 30, 20, 10 | Room 721: 30 · Room 722: 30 · Room 723: 20 + 10 (30) |
| 9, 10, 3 | One room: 22 students, 3 blocks |
| 3, 3, 3, 3 | One room: 12 students, 4 blocks |
| 3, 3, 3, 3, 3 | Room 1: 4 blocks (12) · Room 2: 1 block (3) |
| 13, 17 (different subjects) | One room: 13 + 17 = 30 |
| 13, 18 | Two rooms (18 > 17 remaining seats) |
| 13 (Maths), 10 (Maths) | Separate rooms (same subject cannot share) |
| 25, 10, 5 | Room 1: 25 + 5 (30) · Room 2: 10 |

---

## 6. Pseudocode

```python
ROOMS = [721,722,723,724,725,731,732,733,734,761,762,764,765]
CAP, MAX_BLOCKS = 30, 4

def allocate(blocks):            # blocks: list of {id, subject, students[]}
    rooms = []
    partial = []
    for b in blocks:
        n = len(b.students)
        if n > CAP:
            raise ValueError(f"Block {b.id} exceeds {CAP}")
        if n == CAP:
            rooms.append({"blocks": [b], "count": n})
        else:
            partial.append(b)

    partial.sort(key=lambda b: len(b.students), reverse=True)
    mixed = []
    for b in partial:
        n = len(b.students)
        for r in mixed:
            if (n <= CAP - r["count"] and len(r["blocks"]) < MAX_BLOCKS
                    and b.subject not in {x.subject for x in r["blocks"]}):
                r["blocks"].append(b); r["count"] += n
                break
        else:
            mixed.append({"blocks": [b], "count": n})

    rooms += mixed
    if len(rooms) > len(ROOMS):
        raise RuntimeError("Not enough rooms for this session")
    return {ROOMS[i]: r for i, r in enumerate(rooms)}
```

---

## 7. Post-allocation Checks

- Every room: students ≤ 30 and blocks ≤ 4
- No two blocks of the same subject in one room
- Every block is in exactly one room (never split)
- Every room with 30 students has exactly one block, or blocks totalling 30
- Rooms used are continuous from 721 in the fill sequence
- Every student allocated exactly once

---

## 8. Outputs

1. Room-wise list: room, floor, blocks, subjects, student count, enrollment numbers
2. Block-wise list: block → room
3. Room door chart and seating plan (printable PDF)
4. Attendance sheet per room
5. Session summary: rooms used, students, vacant seats

---

## 9. Edge Cases

| Case | Behaviour |
|------|-----------|
| Total students > 390 | Stop and show the shortfall |
| Block size > 30 | Reject upload, show block number |
| Upload missing before D-1 | Warn / block allocation (admin override optional) |
| Room unavailable | Admin can disable a room; skip it in the sequence |
| Same subject in several blocks | Each block is treated independently; they never share a room |
| Multiple sessions in a day | Allocate each session separately, rooms reused |

---

## 10. Open Questions

1. Should the packing minimize the **number of rooms**, or is first-fit acceptable? (Spec uses first-fit decreasing.)
2. Is there a rule for the missing numbering in the original list? (Now renumbered R1–R9.)
