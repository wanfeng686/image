import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    channel: str
    status: str
    slots: dict
    step_budget: int
    steps_used: int
    escalated_reason: str | None = None
    satisfaction: int | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    closed_at: datetime | None = None