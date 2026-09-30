"""模型服务（管理端）：CRUD + 批量导入。

alias 是对外唯一名（Key 授权、客户端请求都用它），provider_model_name 是上游
真实名，两者都要求全局/组合唯一。导入走"已存在即跳过"而不是报错：拉取-勾选
是幂等操作，重复点一次不该炸。
"""
# 本类有名为 list 的方法，会让类体内的 list[...] 注解解析成方法对象，故延迟求值
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AiModel, AiProvider
from app.schemas.ai import AiModelCreate, AiModelImportRequest, AiModelUpdate
from app.services.revision import bump_revision


class AiModelServiceError(Exception):
    """模型不存在、alias 冲突或所属厂商不存在。"""


class AiModelService:
    async def list(
        self,
        session: AsyncSession,
        *,
        provider_id: int | None = None,
        kind: str | None = None,
    ) -> list[AiModel]:
        query = select(AiModel).order_by(AiModel.id)
        if provider_id is not None:
            query = query.where(AiModel.provider_id == provider_id)
        if kind is not None:
            query = query.where(AiModel.kind == kind)
        rows = await session.execute(query)
        return list(rows.scalars())

    async def get(self, session: AsyncSession, model_id: int) -> AiModel:
        row = await session.get(AiModel, model_id)
        if row is None:
            raise AiModelServiceError(f"模型 {model_id} 不存在")
        return row

    async def create(self, session: AsyncSession, payload: AiModelCreate) -> AiModel:
        await self._ensure_provider(session, payload.provider_id)
        await self._ensure_alias_free(session, payload.alias)
        model = AiModel(
            provider_id=payload.provider_id,
            provider_model_name=payload.provider_model_name,
            alias=payload.alias,
            kind=payload.kind,
            enabled=payload.enabled,
            input_price=payload.input_price,
            output_price=payload.output_price,
        )
        session.add(model)
        await bump_revision(session)
        await session.commit()
        await session.refresh(model)
        return model

    async def update(
        self, session: AsyncSession, model_id: int, payload: AiModelUpdate
    ) -> AiModel:
        model = await self.get(session, model_id)
        if payload.alias is not None and payload.alias != model.alias:
            await self._ensure_alias_free(session, payload.alias)
            model.alias = payload.alias
        if payload.provider_model_name is not None:
            model.provider_model_name = payload.provider_model_name
        if payload.kind is not None:
            model.kind = payload.kind
        if payload.enabled is not None:
            model.enabled = payload.enabled
        if payload.input_price is not None:
            model.input_price = payload.input_price
        if payload.output_price is not None:
            model.output_price = payload.output_price
        await bump_revision(session)
        await session.commit()
        await session.refresh(model)
        return model

    async def delete(self, session: AsyncSession, model_id: int) -> None:
        model = await self.get(session, model_id)
        await session.delete(model)
        await bump_revision(session)
        await session.commit()

    async def import_models(
        self, session: AsyncSession, payload: AiModelImportRequest
    ) -> tuple[int, int, list[AiModel]]:
        """批量导入，返回 (created, skipped, 新建的行)。已存在的静默跳过。"""
        await self._ensure_provider(session, payload.provider_id)

        existing_upstream = set(
            (
                await session.execute(
                    select(AiModel.provider_model_name).where(
                        AiModel.provider_id == payload.provider_id
                    )
                )
            ).scalars()
        )
        existing_aliases = set(
            (await session.execute(select(AiModel.alias))).scalars()
        )

        created: list[AiModel] = []
        skipped = 0
        for item in payload.items:
            alias = item.alias or item.provider_model_name
            if (
                item.provider_model_name in existing_upstream
                or alias in existing_aliases
            ):
                skipped += 1
                continue
            model = AiModel(
                provider_id=payload.provider_id,
                provider_model_name=item.provider_model_name,
                alias=alias,
                kind=item.kind,
                enabled=True,
            )
            session.add(model)
            created.append(model)
            # 同批次内也要去重：否则两条相同候选会各自通过上面的集合判断
            existing_upstream.add(item.provider_model_name)
            existing_aliases.add(alias)

        if created:
            await bump_revision(session)
            await session.commit()
            for model in created:
                await session.refresh(model)
        return len(created), skipped, created

    # ------------------------------------------------------------- 内部
    async def _ensure_provider(self, session: AsyncSession, provider_id: int) -> None:
        if await session.get(AiProvider, provider_id) is None:
            raise AiModelServiceError(f"厂商 {provider_id} 不存在")

    async def _ensure_alias_free(self, session: AsyncSession, alias: str) -> None:
        existing = await session.execute(
            select(AiModel.id).where(AiModel.alias == alias)
        )
        if existing.scalar_one_or_none() is not None:
            raise AiModelServiceError(f"模型别名 '{alias}' 已存在")
