import json
import unittest
from pathlib import Path
from pydantic import ValidationError
if __package__:
    from .engine import Plan
    from .models import Conflict, Exam, Preset
else:
    from engine import Plan
    from models import Conflict, Exam, Preset

BASE = Path(__file__).parent


def demo():
    return json.loads((BASE/'example.json').read_text())


def run(d, previous=None):
    return Plan(Exam.model_validate(d), previous).allocate()


def column(preview, col):
    return [p['sid'] for p in preview['positions'] if p['column'] == col]


class AllocationTests(unittest.TestCase):
    def test_exact_grid(self):
        p = run(demo())
        for col, expected in enumerate([['ICT-001','ICT-013','ICT-003','ICT-025'],
                ['ECE-021','ECE-003','ECE-015','ECE-009'],['DASI-011','DASI-025','DASI-004','DASI-017']],1):
            self.assertEqual(column(p,col),expected)

    def test_seed_shuffled_input(self):
        d = demo()
        d['rules'][3].update(mode='random', sids=[])
        a = column(run(d),1)
        d['students'].reverse()
        self.assertEqual(a,column(run(d),1))
        self.assertNotEqual(a, sorted(a))
        d['seed'] = 51
        self.assertNotEqual(a,column(run(d),1))

    def test_order_modes(self):
        d=demo()
        for mode, expected in [('ascending_sid',[1,3,13,25]),('descending_sid',[25,13,3,1]),
                ('suffix',[13,1,3,25]),('low_high',[1,25,3,13]),('round_robin',[1,13,3,25])]:
            with self.subTest(mode=mode):
                d['students'][1]['batch']='Z'
                d['rules'][3].update(mode=mode,sids=[],suffixes=[13] if mode=='suffix' else [])
                self.assertEqual(column(run(d),1),[f'ICT-{v:03}' for v in expected])

    def test_suffix_collision(self):
        d=demo()
        d['rules']=[dict(type='order',id='suffix',mode='suffix')]
        ids=[p['sid'] for p in run(d)['positions']]
        self.assertEqual(ids,sorted(ids,key=lambda s:(int(s[-3:]),s)))

    def test_over_quota(self):
        d=demo()
        d['rooms'][0]['rows']=10
        d['rules'].append(dict(type='quota',id='ict40',scope={'column':1},value='ICT',minimum=40))
        with self.assertRaisesRegex(Conflict,'40 seats; only 10'):
            run(d)

    def test_proven_infeasible(self):
        d=demo()
        d['rules'].append(dict(type='quota',id='ict-cap',value='ICT',maximum=3))
        with self.assertRaisesRegex(Conflict,'No joint allocation'):
            run(d)

    def test_solver_repairs_greedy(self):
        d=demo()
        d['rules']=[dict(type='quota',id='ece4',scope={'column':1},value='ECE',minimum=4),
                    dict(type='order',id='order',mode='descending_sid',scope={'column':1})]
        p=run(d)
        self.assertEqual(p['method'],'verified_milp')
        self.assertEqual(column(p,1),['ECE-021','ECE-015','ECE-009','ECE-003'])

    def test_lock_and_pins(self):
        d=demo()
        d['rooms'][0]['rows']=5
        old=run(d)
        d['locks']=[dict(column=1)]
        d['rules'][4].update(mode='random',sids=[])
        p=run(d,old)
        self.assertEqual(column(old,1),column(p,1))
        self.assertTrue(all(v['locked'] for v in p['positions'] if v['column']==1))
        d['pins']={'A101/5/1/1':'ICT-001'}
        with self.assertRaisesRegex(Conflict,'Pin conflicts'):
            run(d,old)

    def test_override_and_precedence(self):
        d=demo()
        d['rules'].append(dict(type='order',id='default',mode='descending_sid'))
        p=run(d)
        self.assertEqual(p['positions'][0]['superseded_orders'],['default'])
        plan=Plan(Exam.model_validate(d),p)
        with self.assertRaisesRegex(Conflict,'order violated'):
            plan.edit(p,'A101/1/1/1','A101/2/1/1')
        d['rules'].append(dict(type='order',id='ambiguous',mode='random',scope={'column':1}))
        with self.assertRaisesRegex(Conflict,'Ambiguous'):
            run(d)

    def test_swap_move(self):
        d=demo()
        d['rooms'][0]['rows']=5
        d['rules']=d['rules'][:3]
        old=run(d)
        plan=Plan(Exam.model_validate(d),old)
        p=plan.edit(old,'A101/1/1/1','A101/5/1/1')
        self.assertEqual(column(old,1)[0],column(p,1)[-1])
        swapped=plan.edit(old,'A101/1/1/1','A101/2/1/1')
        self.assertEqual(column(old,1)[1],column(swapped,1)[0])

    def test_alternation_bench_and_block(self):
        d=demo()
        d['rooms']=[dict(id='A101',rows=3,columns=3,seats_per_bench=2)]
        d['rules']=[dict(type='cycle',id='cycle',axis='row',values=['ICT','ECE','DASI']),
                    dict(type='blocked',id='broken',scope=dict(row=1,column=1,position=1)),
                    dict(type='distinct_neighbors',axis='row',id='adj')]
        p=run(d)
        self.assertTrue(p['positions'][0]['blocked'])
        for v in p['positions']:
            if v['sid']:
                self.assertEqual(v['branch'],['ICT','ECE','DASI'][v['row']-1])

    def test_dynamic_group_solver(self):
        d=demo()
        d['rules']=[dict(id='single',type='uniform',axis='column'),
                    dict(id='neighbors',type='distinct_neighbors',axis='column')]
        p=run(d)
        self.assertEqual(len({v.split('-')[0] for v in column(p,2)}),1)
        self.assertNotEqual(column(p,1)[0][:3],column(p,2)[0][:3])

    def test_schema_and_presets(self):
        for f in (BASE/'presets').glob('*.json'):
            Preset.model_validate_json(f.read_text())
        d=demo()
        d['rules'][0]['typo']=1
        with self.assertRaises(ValidationError):
            run(d)


if __name__=='__main__':
    unittest.main()
