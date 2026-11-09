from collections import defaultdict
from itertools import pairwise
if __package__:
    from .models import Cell, Conflict, Exam
    from .ordering import precedence, sequence
else:  # Original standalone CLI
    from models import Cell, Conflict, Exam
    from ordering import precedence, sequence


def require(ok, message, hint):
    if not ok:
        raise Conflict(message, hint)


def unique(items, label):
    require(len(items) == len(set(items)), f'Duplicate {label}.', f'Give each {label} a unique identifier.')


def physical_groups(cells, axis):
    groups = defaultdict(list)
    for c in cells:
        axis_key = (c.row, c.column) if axis == 'bench' else (getattr(c, axis),)
        groups[(c.room, *axis_key)].append(c.key)
    return groups


def neighbors(groups, axis):
    for key in groups:
        # Benches are horizontal neighbors in the same row.
        other = (*key[:-1], key[-1] + 1)
        if other in groups:
            yield key, other


class Plan:
    def __init__(self, exam: Exam, previous=None):
        self.exam = exam
        unique([p.sid for p in exam.students], 'SID')
        unique([r.id for r in exam.rooms], 'room')
        unique([r.id for r in exam.rules], 'rule ID')
        self.people = {p.sid: p for p in sorted(exam.students, key=lambda p: p.sid)}
        self.cells = [Cell(room=r.id, row=i, column=j, position=k)
                      for r in sorted(exam.rooms, key=lambda r: r.id)
                      for i in range(1, r.rows + 1) for j in range(1, r.columns + 1)
                      for k in range(1, r.seats_per_bench + 1)]
        self.keys = [c.key for c in self.cells]
        self.active = defaultdict(list)
        self.rules = {}
        self.quotas = []
        self.groups = []
        self.orders = []
        self.blocked = set()
        self.fixed = {}
        self.locked = set()
        for rule in exam.rules:
            cells = self.select(rule.scope, rule.id)
            self.rules[rule.id] = rule
            for c in cells:
                self.active[c.key].append(rule)
            if rule.type == 'blocked':
                self.blocked.update(c.key for c in cells)
            if rule.type == 'quota':
                self.quotas.append((rule, [c.key for c in cells]))
            if rule.type in ('uniform', 'distinct_neighbors'):
                self.groups.append((rule, physical_groups(cells, rule.axis)))
            if rule.type == 'order' and set(rule.sids) - self.people.keys():
                raise Conflict(f'{rule.id}: unknown explicit SID.', 'Update the roster or ordering list.')
        self._locks(previous)
        for key, sid in exam.pins.items():
            require(key in self.keys and sid in self.people, f'Invalid pin {key} = {sid}.',
                    'Use a current seat key and full SID.')
            require(self.fixed.get(key, sid) == sid, f'Pin conflicts with lock at {key}.',
                    'Review the pin and approved seat.')
            self.fixed[key] = sid
            self.locked.add(key)
        unique([sid for sid in self.fixed.values() if sid is not None], 'fixed SID')
        self.domain = {}
        cache = {}
        for c in self.cells:
            filters = []
            for r in self.active[c.key]:
                if r.type == 'allow':
                    filters.append((r.field, tuple(r.values)))
                elif r.type == 'cycle':
                    value = r.values[(getattr(c, r.axis) - 1) % len(r.values)]
                    filters.append((r.field, (value,)))
            signature = tuple(filters)
            if c.key in self.blocked:
                self.domain[c.key] = frozenset()
                continue
            if signature not in cache:
                cache[signature] = frozenset(s for s, p in self.people.items()
                    if all(getattr(p, field) in values for field, values in signature))
            self.domain[c.key] = cache[signature]
        self._orders()
        self._preflight()

    def select(self, scope, label):
        cells = [c for c in self.cells if c.matches(scope)]
        require(cells, f'{label}: selector matches zero seats.', 'Check room and one-based coordinates.')
        return cells

    def _locks(self, previous):
        old = {} if previous is None else {p['seat_id']: p for p in previous['positions']}
        protected = {k for k, p in old.items() if p['locked']}
        for scope in self.exam.locks:
            protected.update(c.key for c in self.select(scope, 'lock'))
        for k in protected:
            require(k in old and k in self.keys, f'Missing snapshot seat {k}.',
                    'Supply the approved preview with the same locked seat coordinates.')
            self.fixed[k] = old[k]['sid']
        self.locked.update(protected)

    def _orders(self):
        regions = defaultdict(list)
        for c in self.cells:
            rules = [r for r in self.active[c.key] if r.type == 'order']
            if rules:
                rules.sort(key=precedence, reverse=True)
                if len(rules) > 1 and precedence(rules[0]) == precedence(rules[1]):
                    raise Conflict(f'Ambiguous ordering at {c.key}: {rules[0].id} and {rules[1].id}.',
                                   'Set distinct priorities at this scope or remove the overlap.')
                regions[rules[0].id].append(c)
        self.winners = {}
        for name, cells in regions.items():
            rule = self.rules[name]
            cells.sort(key=lambda c: (c.room, c.column, c.row, c.position) if rule.traversal == 'column'
                       else (c.room, c.row, c.column, c.position))
            keys = [c.key for c in cells]
            candidates = set().union(*(self.domain[k] for k in keys))
            groups = defaultdict(list)
            for sid in candidates:
                p = self.people[sid]
                groups[getattr(p, rule.group_by) if rule.group_by != 'all' else '*'].append(p)
            for group in sorted(groups):
                ids = sequence(rule, groups[group], self.exam.seed, group)
                self.orders.append((name, keys, {sid: i + 1 for i, sid in enumerate(ids)}))
            self.winners.update(dict.fromkeys(keys, name))

    def _preflight(self):
        for k, sid in self.fixed.items():
            require(sid is None or sid in self.domain[k], f'Fixed assignment {k} = {sid} is ineligible.',
                    'Review the seat restrictions, roster, and pin or lock.')
        for rule, keys in self.quotas:
            possible = [k for k in keys if any(getattr(self.people[s], rule.field) == rule.value
                         for s in self.domain[k]) and (k not in self.fixed or
                         (self.fixed[k] and getattr(self.people[self.fixed[k]], rule.field) == rule.value))]
            require(len(possible) >= rule.minimum,
                    f'{rule.id}: {rule.value} requires {rule.minimum} seats; only {len(possible)} available.',
                    'Lower the minimum or expand the selected seats.')
        require(len(self.people) <= sum(bool(self.domain[k]) and self.fixed.get(k, True) is not None
                                        for k in self.keys), 'Insufficient usable seats for this roster.',
                'Add seats or review blocks, eligibility, and locks.')

    def verify(self, assignment):
        require(assignment.keys() == set(self.keys), 'Incomplete seat map.', 'Include every physical position.')
        occupied = [s for s in assignment.values() if s is not None]
        require(sorted(occupied) == sorted(self.people), 'Duplicate, missing or unknown SID.',
                'Place every eligible full SID exactly once.')
        for k, s in assignment.items():
            require(s is None or s in self.domain[k], f'Ineligible student at {k}.', 'Review matching allow/block rules.')
            require(k not in self.fixed or self.fixed[k] == s, f'Locked or pinned seat changed: {k}.',
                    'Restore the approved occupant.')
        for r, keys in self.quotas:
            n = sum(getattr(self.people[assignment[k]], r.field) == r.value for k in keys if assignment[k])
            require(n >= r.minimum and (r.maximum is None or n <= r.maximum),
                    f'{r.id}: actual count {n} outside quota.', 'Change the placement or quota.')
        for r, groups in self.groups:
            values = {g: {getattr(self.people[assignment[k]], r.field) for k in keys if assignment[k]}
                      for g, keys in groups.items()}
            if r.type == 'uniform':
                valid = all(len(v) <= 1 for v in values.values())
            else:
                valid = all(values[a].isdisjoint(values[b]) for a, b in neighbors(groups, r.axis))
            require(valid, f'{r.id}: {r.axis} grouping violated.', 'Review the conflicting placements or grouping.')
        for name, keys, ranks in self.orders:
            seen = [ranks[assignment[k]] for k in keys if assignment[k] in ranks]
            require(all(a < b for a, b in pairwise(seen)), f'{name}: SID order violated.',
                    'Choose seats compatible with the sequence or change the ordering policy.')

    def preview(self, assignment, method):
        self.verify(assignment)
        positions = []
        for c in self.cells:
            k = c.key
            p = self.people.get(assignment[k])
            ids = [r.id for r in self.active[k] if r.type != 'order' or r.id == self.winners.get(k)]
            positions.append(dict(seat_id=k, room=c.room, row=c.row, column=c.column,
                bench=f'{c.row}/{c.column}', seat_position=c.position, sid=p.sid if p else None,
                branch=p.branch if p else None, batch=p.batch if p else None, locked=k in self.locked,
                blocked=k in self.blocked, applied_rules=ids,
                superseded_orders=[r.id for r in self.active[k] if r.type=='order' and r.id not in ids]))
        return dict(version=1, method=method, seed=self.exam.seed, positions=positions,
                    rules={k:r.model_dump(exclude_none=True) for k,r in self.rules.items()})

    def allocate(self, seconds=30):
        assignment = dict.fromkeys(self.keys)
        assignment.update(self.fixed)
        used = set(self.fixed.values())
        # Try a cheap complete placement before constructing binary variables.
        for _, keys, ranks in self.orders + [('remaining', self.keys, self.people)]:
            queue = [s for s in ranks if s not in used]
            for k in keys:
                if k in self.fixed or assignment[k] is not None:
                    continue
                for i, sid in enumerate(queue):
                    if sid in self.domain[k]:
                        assignment[k] = queue.pop(i)
                        used.add(sid)
                        break
        try:
            return self.preview(assignment, 'verified_greedy')
        except Conflict:
            if __package__:
                from .solver import solve
            else:
                from solver import solve
            return self.preview(solve(self, seconds), 'verified_milp')

    def edit(self, previous, source, target):
        # A swap with an empty seat implements a move.
        a = {p['seat_id']:p['sid'] for p in previous['positions']}
        require(source in a and target in a and a[source] is not None, 'Invalid move or swap.',
                'Choose an occupied source and an existing target.')
        protected = {p['seat_id'] for p in previous['positions'] if p['locked']}
        require(not ({source, target} & protected), 'Move touches a protected seat.',
                'Select two unlocked seats.')
        a[source], a[target] = a[target], a[source]
        return self.preview(a, 'verified_manual')
