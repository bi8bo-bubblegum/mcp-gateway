from sqlalchemy import DateTime
from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

TIMESTAMP = DateTime(timezone=True)