from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

class TaskProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    deadline: datetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)
    priority: Literal['low', 'medium', 'high', 'urgent'] = 'medium'
    category: str = Field(default='', max_length=100)
    goal_index: int | None = Field(default=None, ge=0)
    dependency_indices: list[int] = Field(default_factory=list, max_length=50)
    estimate_uncertain: bool = False
    @field_validator('deadline')
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError('A deadline requires a timezone offset.')
        return value

class GoalProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    target_date: date | None = None

class Extraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goals: list[GoalProposal] = Field(default_factory=list, max_length=20)
    tasks: list[TaskProposal] = Field(default_factory=list, max_length=50)
    recurring_requirements: list[str] = Field(default_factory=list, max_length=30)
    availability_constraints: list[str] = Field(default_factory=list, max_length=30)
    clarifications: list[str] = Field(default_factory=list, max_length=20)

class Classification(BaseModel):
    intent: Literal['extract', 'assist']

class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['create_task', 'create_goal', 'update_task', 'complete_task']
    task_id: int | None = Field(default=None, gt=0)
    data: dict = Field(default_factory=dict)
