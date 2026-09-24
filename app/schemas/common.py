from typing import Literal

RiskLevel = Literal["low", "medium", "high"]
ServiceHealth = Literal["unknown", "healthy", "unhealthy"]
AuditStatus = Literal["started", "succeeded", "failed", "denied"]

SLUG_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"