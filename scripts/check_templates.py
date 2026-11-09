"""Template rendering smoke check with synthetic fixtures; does not verify Flask routes."""
from jinja2 import Environment,FileSystemLoader,StrictUndefined
from types import SimpleNamespace
from pathlib import Path
import json
from datetime import datetime

ROOT=Path(__file__).resolve().parent.parent
env=Environment(loader=FileSystemLoader(str(ROOT/'templates')),undefined=StrictUndefined,autoescape=True)
env.filters['localtime']=lambda value,zone='Asia/Kolkata':value or 'Not scheduled'
env.globals.update(url_for=lambda endpoint,**kwargs:'/'+endpoint,csrf_token=lambda:'csrf',college_name='Example College',
 get_flashed_messages=lambda **kwargs:[],request=SimpleNamespace(endpoint='dashboard',path='/admin',form={}),
 available=lambda l:l['rows']*l['columns']*l['seats_per_bench']-sum(s in ('blocked','reserved') for s in l['seats'].values()),
 json_loads=json.loads,publication_label=lambda exam:'Private')
layout={'rows':2,'columns':2,'seats_per_bench':1,'seats':{}}
room={'id':1,'number':'A101','building':'Main','layout':layout,'version':1}
exam={'id':1,'title':'Exam','starts_at':'2026-12-15T04:00:00+00:00','timezone':'Asia/Kolkata','version':1,
 'rules':'[]','seed':42,'draft_id':1,'approved_id':None,'published_id':None,'publication':'off','publish_at':None,
 'show_names':0,'student_count':4,'room_count':1,'mode':'seating','shift':'','gtu_date':'','source':'spreadsheet','historical':0,'auto_publish':0}
seats=[{'seat_id':f'R1/{r}/{c}/1','room':'R1','row':r,'column':c,'seat_position':1,'sid':f'{r}{c}',
 'branch':'ICT','batch':'2024','name':'Test','year':'2','building':'Main','room_number':'A101','bench_number':(r-1)*2+c,
 'locked':False,'blocked':False,'applied_rules':[]} for r in range(1,3) for c in range(1,3)]
revision={'id':1,'approved':0,'created':'2026-11-08'}
metadata={'rooms':{'R1':room},'students':{},'exam':exam}
record={'row':2,'sid':'001','name':'Test','branch':'ICT','batch':'2024','year':'2','session':'Exam','valid':True}
common={'admin_user':{'username':'Test'},'exam':exam,'rooms':[{**room,'layout':json.dumps(layout)}],
 'exams':[{**exam,'public':exam}], 'logs':[{'id':1,'action':'login','username':'Test','created':'now','detail':'x'}],
 'student_count':4,'layout':layout,'room':room,'selected':{1},'count':4,'history':[revision],'errors':[],
 'local_start':'2026-12-15T09:30','local_publish':'','roster':[record],'fields':{'sid':'SID'},'records':[record],
 'token':'x','branches':['ICT'],'presets':[],'revision':revision,'data':{'metadata':metadata,'preview':{'seed':42}},
 'room_id':'R1','grid':{p['seat_id']:p for p in seats},'editable':True,'seat':seats[0],'ready':True,
 'rows':[],'selected_exam':None,'include_drafts':False,'total_students':0,'room_count':0,'log_cutoff':1,'people':[],'person':None,'added':1,'removed':0,'reason':'Test authorization','error':None,'hint':'','code':422,'message':'Invalid request','pdf_available':True,'mode':'seating',
 'groups':{'R1':[{**p,'block_no':'','pdf_bench':None} for p in seats]}}
gtu_exam={**exam,'mode':'gtu','shift':'morning','gtu_date':'2099-11-09'}
gtu_room={'id':'G721','number':'721','floor':'Ground Floor','building':'Ground Floor','capacity':30}
gtu_seats=[{'seat_id':f'G721/{n}','room':'G721','seat_number':n,'sid':f'{n:03}',
 'block_no':'001','subject_code':'3110001','subject_name':'Mathematics'} for n in range(1,4)]
gtu_record={'row':2,'exam_date':'2099-11-09','session':'morning','block_no':'001',
 'subject_code':'3110001','subject_name':'Mathematics','enrollment_no':'001','valid':True}
settings={'room_capacity':30,'max_blocks_per_room':4,'floors':[{'order':1,'name':'Ground Floor','rooms':['721']}]}
report={'title':'Test PDF','center':'Test College','pages':1,'blocks':1,'students':1,'mode':'gtu',
 'timezone':'Asia/Kolkata','auto_publish':True,'note':'Subject codes only',
 'sessions':[{'exam_date':'2099-11-09','shift':'morning','historical':False,'errors':[],
 'existing_id':None,'clock':'09:30','blocks':1,'records':[{**gtu_record,'sid':'001','pdf_bench':1,'pdf_page':1}]}]}
common['report']=report
for path in (ROOT/'templates').rglob('*.html'):

 if path.name.startswith('_'):continue
 context=common.copy()
 if path.name=='revised_pdf.html':context['report']=None
 if path.name=='chart.html':context['rooms']={'R1':room}
 if path.name.startswith('gtu_'):
  context.update(exam=gtu_exam,settings=settings,settings_version=1,disabled=[],sequence=[gtu_room],
    roster=[gtu_record],records=[gtu_record],rooms={'G721':gtu_room},room=gtu_room,room_id='G721',
    data={'metadata':{'exam':gtu_exam},'config':{'settings':settings}},seats=gtu_seats,used_rooms=1,
    total_students=3,can_approve=True)

 if path.name in ('index.html','result.html','login.html','error.html'):context['admin_user']=None
 try:env.get_template(str(path.relative_to(ROOT/'templates'))).render(**context)
 except Exception as exc:print(path,'FAIL',type(exc).__name__,str(exc));raise
 print('RENDERED',path)
