from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, field_serializer

RiskLevel = Literal["low", "medium", "high"]
ServiceHealth = Literal["unknown", "healthy", "unhealthy"]
AuditStatus = Literal["started", "succeeded", "failed", "denied"]

SLUG_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"


class UTCTimestampModel(BaseModel):
    """响应模型基类：给库里的 naive UTC 时间补上时区标记再输出。

    MySQL 的 DATETIME 不存时区，`utcnow()` 写入的是 naive UTC，读出来同样是
    naive datetime。直接序列化会得到 "2026-09-29T05:41:47" 这种**缺时区标记**
    的串，而浏览器按 ECMAScript 规范会把它当成本地时间来解释，东八区下展示
    的时间会比真实时间早 8 小时。

    这里统一在 JSON 序列化时把 naive 时间标记为 UTC，输出 "2026-09-29T05:41:47Z"，
    前端 `new Date()` 即可正确转成本地时间。Python 模式（model_dump）不受影响。
    """

    @field_serializer("*", when_used="json")
    def _mark_utc(self, value: Any) -> Any:
        # 只处理 naive datetime；带时区的原样返回，其余类型（int/str/list 等）不碰
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value