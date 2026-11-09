import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
if __package__:
    from .models import Conflict
else:
    from models import Conflict

INF = np.inf


class Matrix:
    def __init__(self):
        self.cost, self.upper, self.integer = [], [], []
        self.rows, self.cols, self.data = [], [], []
        self.lo, self.hi = [], []

    def var(self, maximum=1, integer=True, cost=0):
        index = len(self.cost)
        self.cost.append(cost)
        self.upper.append(maximum)
        self.integer.append(integer)
        return index

    def row(self, pairs, lo=-INF, hi=INF):
        for index, coeff in pairs:
            self.rows.append(len(self.lo))
            self.cols.append(index)
            self.data.append(coeff)
        self.lo.append(lo)
        self.hi.append(hi)

    def run(self, seconds):
        a = coo_matrix((self.data, (self.rows, self.cols)), shape=(len(self.lo), len(self.cost))).tocsc()
        return milp(self.cost, integrality=self.integer, bounds=Bounds(0, self.upper),
                    constraints=LinearConstraint(a, self.lo, self.hi),
                    options={'time_limit': seconds})


def solve(plan, seconds):
    m = Matrix()
    by_sid = {s: [] for s in plan.people}
    x = {}
    reserved = {s:k for k,s in plan.fixed.items() if s is not None}
    for idx, key in enumerate(plan.keys):
        x[key] = {}
        for sid in sorted(plan.domain[key]):
            if key in plan.fixed and plan.fixed[key] != sid or reserved.get(sid, key) != key:
                continue
            v = m.var(cost=idx)
            x[key][sid] = v
            by_sid[sid].append(v)
        m.row([(v, 1) for v in x[key].values()], hi=1)
    for sid, variables in by_sid.items():
        if not variables:
            raise Conflict(f'No eligible seat for {sid}.', 'Review room permissions, blocks and locks.')
        m.row([(v, 1) for v in variables], 1, 1)
    for rule, keys in plan.quotas:
        m.row([(v, 1) for k in keys for s,v in x[k].items()
               if getattr(plan.people[s], rule.field) == rule.value],
              rule.minimum, INF if rule.maximum is None else rule.maximum)
    if __package__:
        from .engine import neighbors
    else:
        from engine import neighbors
    for rule, groups in plan.groups:
        indicators = {}
        labels = sorted({getattr(p, rule.field) for p in plan.people.values()})
        for g, keys in groups.items():
            indicators[g] = {}
            for label in labels:
                vs = [v for k in keys for s,v in x[k].items() if getattr(plan.people[s],rule.field)==label]
                if vs:
                    flag = m.var()
                    indicators[g][label] = flag
                    m.row([(v,1) for v in vs] + [(flag,-len(keys))], hi=0)
            if rule.type == 'uniform':
                m.row([(v,1) for v in indicators[g].values()], hi=1)
        if rule.type == 'distinct_neighbors':
            for a,b in neighbors(groups, rule.axis):
                for label in sorted(indicators[a].keys() & indicators[b].keys()):
                    m.row([(indicators[a][label],1),(indicators[b][label],1)], hi=1)
    for _, keys, ranks in plan.orders:
        maximum = len(ranks)
        last = None
        for k in keys:
            choices = [(v,ranks[s]) for s,v in x[k].items() if s in ranks]
            if not choices:
                continue
            prefix = m.var(maximum, integer=False)
            if last is not None:
                m.row([(prefix,1),(last,-1)], lo=0)
            # With one occupant prefix equals its rank. Otherwise it may carry forward.
            m.row([(prefix,1)] + [(v,-rank) for v,rank in choices], lo=0)
            m.row([(prefix,1)] + [(v,maximum-rank) for v,rank in choices], hi=maximum)
            last = prefix
    result = m.run(seconds)
    if result.status != 0 or result.x is None:
        if result.status == 2:
            raise Conflict(f'No joint allocation satisfies rules {list(plan.rules)} and fixed seats {list(plan.fixed)}.',
                           'Compare quotas with eligible students, then review overlapping rules, ordering and pins.')
        raise Conflict(f'Search incomplete: {result.message}', 'Increase the solver time limit or narrow seat domains.')
    return {k: next((s for s,v in choices.items() if result.x[v] > 0.5), None) for k, choices in x.items()}
