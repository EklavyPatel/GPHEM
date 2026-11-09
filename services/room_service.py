from engine.models import Room

STATUSES = {'blocked', 'reserved', 'accessible'}


def validate_layout(layout):
    if not isinstance(layout, dict) or set(layout) - {'rows', 'columns', 'seats_per_bench', 'seats'}:
        raise ValueError('Invalid classroom layout fields.')
    room = Room.model_validate({'id': 'layout', **{k:v for k,v in layout.items() if k != 'seats'}})
    if room.rows > 50 or room.columns > 50 or room.seats_per_bench > 6:
        raise ValueError('Use at most 50 rows, 50 columns and 6 seats per bench.')
    capacity = room.rows * room.columns * room.seats_per_bench
    if capacity > 10000:
        raise ValueError('A room may have at most 10,000 physical seats.')
    seats = layout.get('seats', {})
    if not isinstance(seats, dict):
        raise ValueError('Seat states must be an object.')
    for key, status in seats.items():
        try:
            parts = key.split('/')
            r, c, p = map(int, parts)
            valid = key == f'{r}/{c}/{p}' and 1 <= r <= room.rows and 1 <= c <= room.columns and 1 <= p <= room.seats_per_bench
        except (ValueError, AttributeError):
            valid = False
        if not valid or status not in STATUSES:
            raise ValueError(f'Invalid physical seat or state: {key}.')
    return {**room.model_dump(exclude={'id'}), 'seats': seats}


def available(layout):
    return layout['rows'] * layout['columns'] * layout['seats_per_bench'] - sum(
        state in ('blocked', 'reserved') for state in layout.get('seats', {}).values())
