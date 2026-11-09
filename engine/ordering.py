import hashlib
import json
import re
from collections import defaultdict, deque
from itertools import zip_longest

if __package__:
    from .models import Conflict
else:
    from models import Conflict


def sequence(order, students, seed, group):
    people = sorted(students, key=lambda p: p.sid)
    ids = [p.sid for p in people]
    mode = order.mode
    if mode == 'ascending_sid':
        return ids
    if mode == 'descending_sid':
        return ids[::-1]
    if mode == 'low_high':
        queue = deque(ids)
        return [queue.popleft() if i % 2 == 0 else queue.pop() for i in range(len(ids))]
    if mode == 'round_robin':
        batches = defaultdict(list)
        for person in people:
            batches[person.batch].append(person.sid)
        return [sid for cycle in zip_longest(*(batches[b] for b in sorted(batches)))
                for sid in cycle if sid is not None]
    if mode == 'random':
        def digest(sid):
            data = json.dumps([seed, order.id, group, sid], ensure_ascii=True)
            return hashlib.sha256(data.encode()).digest(), sid
        return sorted(ids, key=digest)
    if mode == 'explicit':
        ranks = {sid: i for i, sid in enumerate(order.sids)}
        return sorted(ids, key=lambda sid: (ranks.get(sid, len(ranks)), sid))
    ranks = {number: i for i, number in enumerate(order.suffixes)}
    def suffix_key(sid):
        match = re.search(r'([0-9]+)$', sid)
        if not match:
            raise Conflict(f'{order.id}: {sid} has no numeric suffix.',
                           'Narrow the ordering scope or select full SID ordering.')
        number = int(match[1])
        return ranks.get(number, len(ranks)), number, sid
    return sorted(ids, key=suffix_key)


def precedence(rule):
    s = rule.scope
    level = (5 if s.position else 4 if s.row and s.column else
             3 if s.row or s.column else 2 if s.room else 1)
    return level, bool(s.room), rule.layer == 'session', rule.priority
