import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str                   # customer | agent | human_operator | system
    content: str | None = None
    content_type: str           # text | card | system
    card_data: dict | None = None
    agent_source: str | None = None
    status: str
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageOut]
    total: int
    page: int
    page_size: int
