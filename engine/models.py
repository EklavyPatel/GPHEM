from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
Pos = Annotated[int, Field(ge=1)]
Count = Annotated[int, Field(ge=0)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Student(Model):
    sid: Name
    branch: Name
    batch: Name


class Room(Model):
    id: Name
    rows: Pos
    columns: Pos
    seats_per_bench: Pos = 1


class Scope(Model):
    room: Name | None = None
    row: Pos | None = None
    column: Pos | None = None
    position: Pos | None = None

    @model_validator(mode='after')
    def check_position(self):
        if self.position and not (self.row and self.column):
            raise ValueError('Seat position requires row and column (one bench).')
        return self


class Rule(Model):
    id: Name
    layer: Literal['exam', 'session'] = 'exam'
    scope: Scope = Field(default_factory=Scope)


class Allow(Rule):
    type: Literal['allow']
    field: Literal['branch', 'batch', 'sid'] = 'branch'
    values: list[Name] = Field(min_length=1)


class Cycle(Rule):
    type: Literal['cycle']
    field: Literal['branch', 'batch'] = 'branch'
    axis: Literal['row', 'column', 'position']
    values: list[Name] = Field(min_length=1)


class Quota(Rule):
    type: Literal['quota']
    field: Literal['branch', 'batch'] = 'branch'
    value: Name
    minimum: Count = 0
    maximum: Count | None = None

    @model_validator(mode='after')
    def bounds(self):
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError('Maximum must be at least minimum.')
        return self


class Group(Rule):
    type: Literal['uniform', 'distinct_neighbors']
    field: Literal['branch', 'batch'] = 'branch'
    axis: Literal['row', 'column', 'bench']


class Block(Rule):
    type: Literal['blocked']


class Order(Rule):
    type: Literal['order']
    priority: int = 0
    mode: Literal['ascending_sid', 'descending_sid', 'random', 'low_high',
                  'round_robin', 'explicit', 'suffix']
    traversal: Literal['column', 'row'] = 'row'
    group_by: Literal['all', 'branch', 'batch'] = 'all'
    sids: list[Name] = Field(default_factory=list)
    suffixes: list[Count] = Field(default_factory=list)

    @model_validator(mode='after')
    def lists(self):
        for name, mode in [('sids', 'explicit'), ('suffixes', 'suffix')]:
            values = getattr(self, name)
            if (values and self.mode != mode) or len(values) != len(set(values)):
                raise ValueError(f'Invalid or repeated {name} for ordering mode.')
        if self.mode == 'explicit' and not self.sids:
            raise ValueError('Explicit ordering requires a nonempty SID sequence.')
        return self


Policy = Annotated[Union[Allow, Cycle, Quota, Group, Block, Order], Field(discriminator='type')]


class Preset(Model):
    version: Literal[1]
    rules: list[Policy]


class Exam(Preset):
    rooms: list[Room] = Field(min_length=1)
    students: list[Student]
    seed: int = 42
    pins: dict[str, Name] = Field(default_factory=dict)
    locks: list[Scope] = Field(default_factory=list)


class Cell(Model):
    room: Name
    row: Pos
    column: Pos
    position: Pos

    @property
    def key(self):
        return f'{self.room}/{self.row}/{self.column}/{self.position}'

    def matches(self, scope):
        return all(value is None or getattr(self, key) == value
                   for key, value in scope.__dict__.items())


class Conflict(ValueError):
    def __init__(self, message, hint):
        self.hint = hint
        super().__init__(message)
