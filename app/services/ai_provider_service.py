"""厂商服务（管理端）：CRUD + 上游密钥加密 + 健康检查 + 拉取模型清单。

密钥复用 MCP 上游凭证那套 SecretBox 加密落库（同一个 GATEWAY_SECRET_KEY 更换
即全量失效）；健康检查只问"上游 /v1/models 能不能通"，不逐个模型探测——清单
接口无计费，用它做存活探针最省成本。

写操作一律 bump_revision：AiRuntimeRegistry 的快照按 revision 失效，不加这一下
改了 base_url/启停也要等 TTL 才生效。健康检查例外，见 check_health 注释。
"""
# 本类有名为 list 的方法，会让类体内的 list[...] 注解解析成方法对象，故延迟求值
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.upstream import AiUpstreamPool
from app.core.security import SecretBox
from app.db.base import utcnow
from app.db.models import (
    PROVIDER_HEALTH_HEALTHY,
    PROVIDER_HEALTH_UNHEALTHY,
    AiProvider,
)
from app.schemas.ai import AiProviderCreate, AiProviderUpdate
from app.services.revision import bump_revision

# last_error 是给人看的短摘要，上游返回一页 HTML 时不能整段塞进库
_MAX_ERROR_LEN = 2000


class AiProviderServiceError(Exception):
    """厂商不存在、slug 冲突或上游拉取失败。"""


class AiProviderService:
    def __init__(self, *, secret_box: SecretBox, pool: AiUpstreamPool) -> None:
        self._secret_box = secret_box
        self._pool = pool

    # ------------------------------------------------------------- CRUD
    async def list(self, session: AsyncSession) -> list[AiProvider]:
        rows = await session.execute(select(AiProvider).order_by(AiProvider.id))
        return list(rows.scalars())

    async def get(self, session: AsyncSession, provider_id: int) -> AiProvider:
        row = await session.get(AiProvider, provider_id)
        if row is None:
            raise AiProviderServiceError(f"厂商 {provider_id} 不存在")
        return row

    async def create(
        self, session: AsyncSession, payload: AiProviderCreate
    ) -> AiProvider:
        existing = await session.execute(
            select(AiProvider.id).where(AiProvider.slug == payload.slug)
        )
        if existing.scalar_one_or_none() is not None:
            raise AiProviderServiceError(f"slug '{payload.slug}' 已存在")
        provider = AiProvider(
            slug=payload.slug,
            name=payload.name,
            base_url=payload.base_url.rstrip("/"),
            enabled=payload.enabled,
            api_key_ciphertext=self._encrypt_key(payload.api_key),
        )
        session.add(provider)
        await bump_revision(session)
        await session.commit()
        await session.refresh(provider)
        return provider

    async def update(
        self, session: AsyncSession, provider_id: int, payload: AiProviderUpdate
    ) -> AiProvider:
        provider = await self.get(session, provider_id)
        if payload.name is not None:
            provider.name = payload.name
        if payload.base_url is not None:
            provider.base_url = payload.base_url.rstrip("/")
        if payload.enabled is not None:
            provider.enabled = payload.enabled
        # api_key 缺省表示"不修改"：Read 模型从不回显密文，前端拿不到原值，
        # 若把 None 当作"清空凭证"就会在每次编辑名称时顺手抹掉上游密钥。
        if payload.api_key is not None:
            provider.api_key_ciphertext = self._encrypt_key(payload.api_key)
        await bump_revision(session)
        await session.commit()
        await session.refresh(provider)
        return provider

    async def delete(self, session: AsyncSession, provider_id: int) -> None:
        provider = await self.get(session, provider_id)
        await session.delete(provider)
        await bump_revision(session)
        await session.commit()

    async def set_enabled(
        self, session: AsyncSession, provider_id: int, enabled: bool
    ) -> AiProvider:
        provider = await self.get(session, provider_id)
        provider.enabled = enabled
        await bump_revision(session)
        await session.commit()
        await session.refresh(provider)
        return provider

    # --------------------------------------------------------- 健康检查
    async def check_health(self, session: AsyncSession, provider_id: int) -> AiProvider:
        """探活一次并落库。

        刻意不 bump_revision：数据面快照只按 enabled 过滤、不看 health，health
        变化对路由结果没有影响，bump 只会白白让所有 worker 重建快照。
        """
        provider = await self.get(session, provider_id)
        try:
            client = await self._pool.get_client(
                base_url=provider.base_url,
                api_key=self._decrypt_key(provider.api_key_ciphertext),
            )
            response = await client.get("/models")
            if response.status_code >= 400:
                raise RuntimeError(f"上游返回 HTTP {response.status_code}")
        except Exception as error:  # noqa: BLE001 - 任何异常都等价于"不可用"
            provider.health = PROVIDER_HEALTH_UNHEALTHY
            provider.consecutive_failures += 1
            provider.last_error = str(error)[:_MAX_ERROR_LEN]
        else:
            provider.health = PROVIDER_HEALTH_HEALTHY
            provider.consecutive_failures = 0
            provider.last_error = None
        provider.last_checked_at = utcnow()
        await session.commit()
        await session.refresh(provider)
        return provider

    # ------------------------------------------------------- 拉取模型清单
    async def pull_models(
        self, session: AsyncSession, provider_id: int
    ) -> list[dict[str, str | None]]:
        """调上游 GET /v1/models，返回 [{id, owned_by}] 供管理端勾选导入。"""
        provider = await self.get(session, provider_id)
        try:
            client = await self._pool.get_client(
                base_url=provider.base_url,
                api_key=self._decrypt_key(provider.api_key_ciphertext),
            )
            response = await client.get("/models")
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as error:
            raise AiProviderServiceError(
                f"拉取上游模型列表失败：{error}"
            ) from error

        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise AiProviderServiceError("上游 /models 返回格式不符合 OpenAI 约定")
        return [
            {"id": str(item["id"]), "owned_by": item.get("owned_by")}
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]

    # ------------------------------------------------------------- 内部
    def _encrypt_key(self, api_key: str | None) -> str | None:
        if api_key is None:
            return None
        return self._secret_box.encrypt({"bearer_token": api_key})

    def _decrypt_key(self, ciphertext: str | None) -> str:
        if not ciphertext:
            return ""
        return str(self._secret_box.decrypt(ciphertext).get("bearer_token") or "")
