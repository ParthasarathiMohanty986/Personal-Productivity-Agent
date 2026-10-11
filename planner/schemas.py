from datetime import date, datetime, time
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator

class Window(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: datetime
    end: datetime
    @model_validator(mode='after')
    def valid(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValueError('Time ranges need timezone offsets and end after start.')
        return self

class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='My focused plan', min_length=1, max_length=200)
    plan_type: Literal['daily', 'weekly', 'goal'] = 'daily'
    start_date: date
    end_date: date
    day_start: time
    day_end: time
    daily_minutes: int = Field(ge=1, le=1440)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    task_ids: list[int] | None = Field(default=None, max_length=500)
    busy: list[Window] = Field(default_factory=list, max_length=100)
    @field_validator('weekdays')
    @classmethod
    def days(cls, value):
        if any(d < 0 or d > 6 for d in value):
            raise ValueError('Weekdays must be 0 (Monday) through 6 (Sunday).')
        return sorted(set(value))
    @model_validator(mode='after')
    def valid(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 30:
            raise ValueError('Choose a date range of at most 31 days.')
        if self.day_end <= self.day_start or self.day_start.tzinfo or self.day_end.tzinfo:
            raise ValueError('Daily end must follow daily start; use local clock times.')
        if self.task_ids is not None and any(i < 1 for i in self.task_ids):
            raise ValueError('Task IDs must be positive.')
        return self

class ProposedBlock(Window):
    task_id: int = Field(gt=0)
