"""Whole-block GTU allocation, implementing the user-provided v2 specification.

No block creation/splitting or student-level moves are permitted. Packing uses
first-fit decreasing, with full blocks first and stable full block IDs for ties.
"""
from collections import defaultdict
import re

DEFAULT_CONFIG = {
    'room_capacity': 30,
    'max_blocks_per_room': 4,
    'floors': [
        {'order': 1, 'name': 'Ground Floor', 'rooms': ['721','722','723','724','725']},
        {'order': 2, 'name': 'First Floor', 'rooms': ['731','732','733','734']},
        {'order': 3, 'name': 'Second Floor', 'rooms': ['761','762','764','765']},
    ],
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {'room_capacity','max_blocks_per_room','floors'}:
        raise ValueError('GTU configuration requires room_capacity, max_blocks_per_room and floors only.')
    capacity, maximum = value['room_capacity'], value['max_blocks_per_room']
    if type(capacity) is not int or not 1 <= capacity <= 30:
        raise ValueError('GTU room capacity must be 1–30; the GTU upper limit is 30 students.')
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError('GTU permits at most four different-subject blocks per room.')
    if not isinstance(value['floors'], list) or not 1 <= len(value['floors']) <= 20:
        raise ValueError('Configure between 1 and 20 floors.')
    floors, orders, numbers = [], set(), set()
    for floor in value['floors']:
        if not isinstance(floor, dict) or set(floor) != {'order','name','rooms'}:
            raise ValueError('Each floor requires order, name and rooms.')
        order, name, rooms = floor['order'], floor['name'], floor['rooms']
        if type(order) is not int or order < 1 or order in orders:
            raise ValueError('Floor orders must be distinct positive integers.')
        if not isinstance(name,str) or not name.strip() or len(name)>100 or any(ord(c)<32 for c in name):
            raise ValueError('Enter a valid floor name (up to 100 characters).')
        if not isinstance(rooms,list) or not rooms:
            raise ValueError(f'{name}: list at least one room.')
        converted = []
        for number in rooms:
            if type(number) not in (str,int) or not re.fullmatch(r'[A-Za-z0-9_-]{1,20}',str(number)):
                raise ValueError('Room numbers must be 1–20 letters, digits, hyphens or underscores.')
            number = str(number)
            if number.casefold() in numbers:
                raise ValueError(f'Duplicate GTU room number: {number}.')
            numbers.add(number.casefold()); converted.append(number)
        orders.add(order)
        floors.append({'order':order,'name':name.strip(),'rooms':converted})
    if len(numbers)>200:
        raise ValueError('Configure at most 200 GTU rooms.')
    return {'room_capacity':capacity,'max_blocks_per_room':maximum,'floors':sorted(floors,key=lambda f:f['order'])}


def room_sequence(config, disabled=()):
    config = validate_config(config)
    all_rooms = [(number,f['name']) for f in config['floors'] for number in f['rooms']]
    disabled = list(disabled)
    if len(set(disabled))!=len(disabled) or not set(disabled)<={n for n,_ in all_rooms}:
        raise ValueError('Unavailable room selections must be distinct configured room numbers.')
    return [{'id':'G'+number,'number':number,'floor':floor,'building':floor,
             'capacity':config['room_capacity']} for number,floor in all_rooms if number not in disabled]


def grouped_blocks(config):
    settings = validate_config(config['settings'])
    students = config['students']
    if not students:
        raise ValueError('Upload the ready-made GTU blocks before allocating rooms.')
    blocks, seen, subjects = {}, set(), {}
    for student in students:
        for field in ('sid','block_no','subject_code','subject_name'):
            value=student.get(field)
            if not isinstance(value,str) or not value or value!=value.strip() or len(value)>250:
                raise ValueError(f'GTU {field} must be nonblank text without surrounding whitespace.')
        sid=student['sid']
        if sid in seen:
            raise ValueError(f'Duplicate enrollment number in this session: {sid}.')
        seen.add(sid)
        block_no=student['block_no']; code=student['subject_code'].casefold()
        if code in subjects and subjects[code]!=student['subject_name']:
            raise ValueError(f'Subject {student["subject_code"]} has inconsistent names.')
        subjects[code]=student['subject_name']
        block=blocks.setdefault(block_no,{'id':block_no,'subject':code,'subject_code':student['subject_code'],
                                          'subject_name':student['subject_name'],'students':[]})
        if block['subject']!=code or block['subject_name']!=student['subject_name']:
            raise ValueError(f'GTU block {block_no} contains more than one subject.')
        block['students'].append(student)
    for block in blocks.values():
        if len(block['students'])>settings['room_capacity']:
            raise ValueError(f'GTU block {block["id"]} has {len(block["students"])} students; maximum {settings["room_capacity"]}. Blocks cannot be split.')
        block['students'].sort(key=lambda s:s['sid'])
    return settings, blocks


def pack(config):
    settings, blocks = grouped_blocks(config)
    rooms = room_sequence(settings,config.get('disabled_rooms',[]))
    capacity=settings['room_capacity']
    total=len(config['students']); available=len(rooms)*capacity
    if total>available:
        raise ValueError(f'Insufficient GTU capacity: {total} students, {available} seats; shortfall {total-available} seats.')
    full=sorted((b for b in blocks.values() if len(b['students'])==capacity),key=lambda b:b['id'])
    partial=sorted((b for b in blocks.values() if len(b['students'])<capacity),key=lambda b:(-len(b['students']),b['id']))
    groups=[[b] for b in full]
    mixed=[]
    for block in partial:
        for group in mixed:
            if (sum(len(b['students']) for b in group)+len(block['students'])<=capacity
                and len(group)<settings['max_blocks_per_room']
                and block['subject'] not in {b['subject'] for b in group}):
                group.append(block);break
        else:
            mixed.append([block])
    groups.extend(mixed)
    if len(groups)>len(rooms):
        raise ValueError(f'Not enough GTU rooms: first-fit packing requires {len(groups)} rooms, but only {len(rooms)} are available '
                         f'(shortfall {len(groups)-len(rooms)} room(s)). The same-subject/four-block limits can leave seats vacant.')
    return settings,rooms,groups


def _allocate_regular(config):
    settings,rooms,groups=pack(config)
    positions=[]
    for index,room in enumerate(rooms):
        occupants=[s for b in groups[index] for s in b['students']] if index<len(groups) else []
        for seat in range(1,settings['room_capacity']+1):
            person=occupants[seat-1] if seat<=len(occupants) else None
            positions.append({'seat_id':f'{room["id"]}/{seat}','room':room['id'],'seat_number':seat,
                              'sid':person['sid'] if person else None,
                              'block_no':person['block_no'] if person else None,
                              'subject_code':person['subject_code'] if person else None,
                              'subject_name':person['subject_name'] if person else None,
                              'locked':False,'blocked':False})
    preview={'version':1,'mode':'gtu','method':'gtu_first_fit_decreasing','positions':positions}
    verify(config,preview)
    return preview


def _verify_regular(config,preview):
    """Independent hard-constraint validation, also enforced at approval and export."""
    settings,blocks=grouped_blocks(config)
    rooms=room_sequence(settings,config.get('disabled_rooms',[]))
    capacity=settings['room_capacity']
    manual=preview.get('manual_room_selection',False)
    if type(manual) is not bool:
        raise ValueError('Manual room selection must be explicitly recorded as true or false.')
    people={s['sid']:s for s in config['students']}
    cells={f'{r["id"]}/{n}' for r in rooms for n in range(1,capacity+1)}
    positions=preview.get('positions',[])
    if len(positions)!=len(cells) or {p.get('seat_id') for p in positions}!=cells:
        raise ValueError('GTU preview has duplicate, missing or unknown physical seat numbers.')
    occupied=[p['sid'] for p in positions if p.get('sid') is not None]
    if sorted(occupied)!=sorted(people):
        raise ValueError('GTU allocation has duplicate, missing or unknown enrollment numbers.')
    by_room=defaultdict(list); block_rooms=defaultdict(set)
    for p in positions:
        if p['seat_id']!=f'{p["room"]}/{p["seat_number"]}':
            raise ValueError('GTU seat number and room coordinates do not match.')
        if p['sid'] is not None:
            person=people[p['sid']]
            if any(p.get(k)!=person[k] for k in ('block_no','subject_code','subject_name')):
                raise ValueError('GTU subject/block metadata differs from the supplied roster.')
            by_room[p['room']].append(p)
            block_rooms[person['block_no']].add(p['room'])
    if set(block_rooms)!=set(blocks) or any(len(v)!=1 for v in block_rooms.values()):
        raise ValueError('A GTU block was split or omitted. Each block must occupy exactly one room.')
    used=[r['id'] for r in rooms if by_room[r['id']]]
    if not manual and used!=[r['id'] for r in rooms[:len(used)]]:
        raise ValueError('GTU rooms must fill continuously in configured floor order, skipping only disabled rooms.')
    partial_seen=False
    for room in rooms:
        occupants=sorted(by_room[room['id']],key=lambda p:p['seat_number'])
        if not occupants:continue
        room_blocks={p['block_no'] for p in occupants}
        if len(occupants)>capacity or len(room_blocks)>settings['max_blocks_per_room']:
            raise ValueError('GTU room capacity or maximum block count was exceeded.')
        if len({blocks[b]['subject'] for b in room_blocks})!=len(room_blocks):
            raise ValueError('Two GTU blocks of the same subject cannot share one room.')
        if any(len(blocks[b]['students'])==capacity for b in room_blocks):
            if len(room_blocks)!=1:
                raise ValueError('Full GTU blocks require exclusive rooms.')
            if partial_seen and not manual:
                raise ValueError('Automatic allocation places full GTU blocks before partial blocks.')
        else:partial_seen=True
        if [p['seat_number'] for p in occupants]!=list(range(1,len(occupants)+1)):
            raise ValueError('GTU seats must be numbered continuously from 1 to N.')
        for b in room_blocks:
            members=[p for p in occupants if p['block_no']==b]
            seat_numbers=[p['seat_number'] for p in members]
            if seat_numbers!=list(range(min(seat_numbers),max(seat_numbers)+1)):
                raise ValueError(f'GTU block {b} must remain together in consecutive seats.')
            if [p['sid'] for p in members]!=sorted(s['sid'] for s in blocks[b]['students']):
                raise ValueError(f'GTU block {b} must be ordered by enrollment number.')
    return True


def regular_input(config):
    fixed=config.get('emergency_seats',{})
    if not isinstance(fixed,dict) or any(not isinstance(sid,str) or not isinstance(seat,str) for sid,seat in fixed.items()):
        raise ValueError('Invalid emergency seat reservations.')
    return {**config,'emergency_seats':{},'students':[p for p in config['students'] if p['sid'] not in fixed]}


def verify(config,preview):
    """Validate regular GTU blocks independently of explicitly authorized direct seats."""
    fixed=config.get('emergency_seats',{})
    if not fixed:return _verify_regular(config,preview)
    import copy
    regular=regular_input(config)
    people={p['sid']:p for p in config['students']}
    if len(people)!=len(config['students']):raise ValueError('Duplicate enrollment number in emergency roster.')
    positions=preview.get('positions',[])
    if sorted(p['sid'] for p in positions if p.get('sid'))!=sorted(people):
        raise ValueError('Duplicate, missing or unknown enrollment number.')
    clean=copy.deepcopy(preview)
    for sid,target in fixed.items():
        person=people.get(sid)
        authorization=person.get('emergency_admission',{}) if person else {}
        if not person or authorization.get('sid')!=sid or not authorization.get('admin_id') or not authorization.get('reason','').strip():
            raise ValueError('Direct emergency seats require a recorded administrator authorization.')
        found=[p for p in clean['positions'] if p.get('sid')==sid]
        if len(found)!=1 or found[0]['seat_id']!=target or found[0].get('blocked'):
            raise ValueError('An emergency student moved away from their confirmed available seat.')
        seat=found[0]
        if any(seat.get(k)!=person[k] for k in ('block_no','subject_code','subject_name')):
            raise ValueError('Emergency student metadata does not match the authorized roster.')
        seat.update(sid=None,block_no=None,subject_code=None,subject_name=None)
    # Empty slots remain in the same physical grid: capacity, unique cells and
    # room availability apply to everyone. Normal blocks retain all GTU rules.
    return _verify_regular(regular,clean)


def allocate(config):
    fixed=config.get('emergency_seats',{})
    if not fixed:return _allocate_regular(config)
    regular=regular_input(config)
    preview=_allocate_regular(regular)
    people={p['sid']:p for p in config['students']}
    cells={p['seat_id']:p for p in preview['positions']}
    for sid,target in fixed.items():
        if target not in cells or cells[target]['sid']:
            raise ValueError('Regeneration conflicts with a confirmed emergency seat. The previous arrangement is preserved.')
        person=people[sid]
        cells[target].update(sid=sid,emergency=True,**{k:person[k] for k in ('block_no','subject_code','subject_name')})
    verify(config,preview)
    return preview


def edit_blocks(config,previous,operation,source,target):
    """Rearrange regular blocks while preserving every confirmed emergency seat."""
    import copy
    verify(config,previous)
    fixed=config.get('emergency_seats',{})
    regular=regular_input(config) if fixed else config
    settings,blocks=grouped_blocks(regular)
    rooms=room_sequence(settings,config.get('disabled_rooms',[]))
    groups={r['id']:[] for r in rooms}
    for seat in sorted(previous['positions'],key=lambda p:p['seat_number']):
        if seat['sid'] and seat['sid'] not in fixed and seat['block_no'] not in groups[seat['room']]:
            groups[seat['room']].append(seat['block_no'])
    if operation=='swap_blocks':
        if source not in blocks or target not in blocks or source==target:
            raise ValueError('Choose two different regular GTU blocks. Emergency admissions stay fixed.')
        origin=next(key for key,values in groups.items() if source in values)
        destination=next(key for key,values in groups.items() if target in values)
        i=groups[origin].index(source);j=groups[destination].index(target)
        groups[origin][i],groups[destination][j]=target,source
    elif operation=='move_block':
        if target not in groups:raise ValueError('Choose a configured, available target room.')
        if source not in blocks:raise ValueError('Choose a regular GTU block. Emergency admissions stay fixed.')
        origin=next(key for key,values in groups.items() if source in values)
        groups[origin].remove(source);groups[target].append(source)
    elif operation=='swap_rooms':
        if source not in groups or target not in groups or source==target:
            raise ValueError('Choose two different available rooms.')
        groups[source],groups[target]=groups[target],groups[source]
    else:raise ValueError('Unsupported GTU arrangement edit.')
    old={p['seat_id']:p for p in previous['positions']}
    reserved=set(fixed.values())
    capacity=settings['room_capacity'];positions=[]
    for room in rooms:
        members=[person for block in groups[room['id']] for person in blocks[block]['students']]
        if len(members)>capacity:raise ValueError(f'Room {room["number"]} would exceed {capacity} students. Move rejected.')
        for number in range(1,capacity+1):
            key=f'{room["id"]}/{number}'
            person=members[number-1] if number<=len(members) else None
            if key in reserved:
                if person:
                    raise ValueError(f'Room {room["number"]}, seat {number} is reserved for an emergency student. Choose a different block or room; no assignments were changed.')
                positions.append(copy.deepcopy(old[key]));continue
            positions.append({'seat_id':key,'room':room['id'],'seat_number':number,
                              'sid':person['sid'] if person else None,
                              'block_no':person['block_no'] if person else None,
                              'subject_code':person['subject_code'] if person else None,
                              'subject_name':person['subject_name'] if person else None,'locked':False,'blocked':False})
    result={**previous,'method':'gtu_verified_manual_blocks','positions':positions,
            'manual_room_selection':True,
            'room_selection_change':{'operation':operation,'source':source,'target':target}}
    verify(config,result)
    return result
