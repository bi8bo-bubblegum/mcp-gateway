from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 必须用绝对路径：相对路径是相对进程 CWD 解析的，换个目录启动就会静默
# 读不到文件，所有配置落回默认值，而进程照常起来——排查起来非常费劲。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# 仓库里公开的默认值。它们能跑通，所以最容易一路带到线上，但代价是：
# secret_key 同时派生 token 的 HMAC 密钥和上游凭证的 Fernet 密钥，用默认值
# 等于凭证以可被任何人解密的形态存库；admin_password 默认值公开，任何人都能
# 登录管理端、签发带 allow_high_risk 的 token。
INSECURE_DEFAULTS = {
    "secret_key": "dev-only-change-me",
    "admin_password": "admin_best",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_prefix="GATEWAY_",
        extra="ignore",
    )

    # 以下三项含明文密钥，统一排除出 repr：否则任何 logger.info("%s", settings)、
    # 未捕获异常的 traceback（富格式化库会展开局部变量）、错误上报 SDK 都会把
    # 它们写进日志。secret_key 同时派生 token 的 HMAC 密钥和上游凭证的 Fernet
    # 密钥，泄露等于凭证全部可解。
    database_url: str = Field(
        default="mysql+aiomysql://root:root@127.0.0.1:3306/mcp_gateway?charset=utf8mb4",
        repr=False,
    )
    db_echo: bool = False
    # 数据库连接池。每个工具调用在关键路径上写两次审计，池子偏小会直接
    # 变成 AuditWriteError -> 拒绝调用，所以不能沿用 SQLAlchemy 的 5+10 默认值。
    db_pool_size: int = 20
    db_max_overflow: int = 20
    db_pool_timeout: float = 10.0
    db_pool_recycle: int = 1800

    host: str = "127.0.0.1"
    port: int = 8800
    mcp_path: str = "/mcp"

    admin_username: str = "admin"
    admin_password: str = Field(default="admin_best", repr=False)

    secret_key: str = Field(default="dev-only-change-me", repr=False)

    policy_cache_ttl: float = 30.0
    # 无效 token 的负缓存。伪造 token 是攻击者完全可控的输入，没有负缓存时
    # 每个都换一次数据库查询。时间要短——token 被重新启用后本进程最多等这么
    # 久才会重新接受它（其他进程还要叠加 revision 广播的延迟）。
    policy_negative_cache_ttl: float = 5.0
    # 上界，防止攻击者用海量唯一伪造 token 把内存撑大
    policy_negative_cache_size: int = 4096
    revision_poll_interval: float = 1.0
    revision_cache_ttl: float = 1.0
    health_interval: float = 30.0
    health_timeout: float = 5.0
    health_failure_threshold: int = 2
    health_max_concurrency: int = 8

    upstream_timeout: float = 30.0
    discovery_timeout: float = 15.0

    # 每个上游服务保持的长连接数
    upstream_pool_size: int = 4
    # 池中连接空闲超过这个秒数就丢弃重连：长连接可能已被上游单方面断开，
    # 复用只会让"长时间空闲后的第一个请求"莫名失败
    upstream_pool_slot_max_idle: float = 60.0
    # 整个连接池（服务被删或凭证改过之后留下的旧池）全空闲多久后回收
    upstream_pool_idle_ttl: float = 300.0

    # ── AI 网关上游调用 ──────────────────────────────────────────
    # 单请求总超时：流式下要覆盖整段 SSE，故比连接超时长很多。
    ai_request_timeout: float = 120.0
    # 仅建立 TCP/TLS 连接的超时，区分于上面的请求超时，避免握手阶段干等。
    ai_connect_timeout: float = 10.0
    # Key 鉴权快照的缓存时长：与 revision 广播双条件失效，TTL 是兜底的本地过期。
    ai_key_cache_ttl: float = 30.0
    # 限流滑动窗口长度：rate_limit_rpm 的含义是"该窗口内最多多少请求"。
    ai_rate_limit_window: float = 60.0

    # 仅限本机开发：默认值只适合跑在 127.0.0.1 上。任何对外可达的部署都必须
    # 覆盖 secret_key 与 admin_password，而不是打开这个开关。
    allow_insecure_defaults: bool = False

    @model_validator(mode="after")
    def _reject_insecure_defaults(self) -> "Settings":
        if self.allow_insecure_defaults:
            return self
        offending = sorted(
            name
            for name, default in INSECURE_DEFAULTS.items()
            if getattr(self, name) == default
        )
        if offending:
            raise ValueError(
                "拒绝启动：以下配置仍是仓库里的公开默认值 —— "
                + "、".join(offending)
                + '。请生成随机值覆盖它们，例如：python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"。'
                "若只是本机开发，可设置 GATEWAY_ALLOW_INSECURE_DEFAULTS=true 放行。"
                "注意：更换 secret_key 后，已加密的上游凭证将无法解密，需要重新录入。"
            )
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()