from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthAccount, RefreshToken, User


class AuthRepository:
    """Async persistence operations for users and authentication records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_id(self, user_id: uuid.UUID, *, for_update: bool = False) -> User | None:
        return await self.session.get(User, user_id, with_for_update=for_update)

    async def get_user_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        statement = select(User).where(User.email == email)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(
            statement
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        email: str,
        display_name: str | None = None,
        avatar_url: str | None = None,
        is_verified: bool = False,
    ) -> User:
        user = User(
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            is_verified=is_verified,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_user_profile(
        self,
        user: User,
        *,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> User:
        if display_name is not None:
            user.display_name = display_name
        if avatar_url is not None:
            user.avatar_url = avatar_url
        await self.session.flush()
        return user

    async def set_user_display_name(
        self,
        user: User,
        display_name: str | None,
    ) -> User:
        user.display_name = display_name
        await self.session.flush()
        return user

    async def set_user_verified(
        self,
        user: User,
        verified: bool = True,
    ) -> User:
        user.is_verified = verified
        await self.session.flush()
        return user

    async def set_user_active(self, user: User, active: bool) -> User:
        user.is_active = active
        await self.session.flush()
        return user

    async def get_local_account_for_user(
        self,
        user_id: uuid.UUID,
    ) -> AuthAccount | None:
        result = await self.session.execute(
            select(AuthAccount).where(
                AuthAccount.user_id == user_id,
                AuthAccount.provider == "local",
            )
        )
        return result.scalar_one_or_none()

    async def get_google_account(
        self,
        provider_user_id: str,
    ) -> AuthAccount | None:
        return await self.get_auth_account("google", provider_user_id)

    async def get_auth_account(
        self,
        provider: str,
        provider_user_id: str,
    ) -> AuthAccount | None:
        result = await self.session.execute(
            select(AuthAccount).where(
                AuthAccount.provider == provider,
                AuthAccount.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_local_account(
        self,
        *,
        user_id: uuid.UUID,
        password_hash: str,
    ) -> AuthAccount:
        account = AuthAccount(
            user_id=user_id,
            provider="local",
            provider_user_id=None,
            password_hash=password_hash,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def create_google_account(
        self,
        *,
        user_id: uuid.UUID,
        provider_user_id: str,
    ) -> AuthAccount:
        account = AuthAccount(
            user_id=user_id,
            provider="google",
            provider_user_id=provider_user_id,
            password_hash=None,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def list_auth_accounts_for_user(
        self,
        user_id: uuid.UUID,
    ) -> list[AuthAccount]:
        result = await self.session.execute(
            select(AuthAccount)
            .where(AuthAccount.user_id == user_id)
            .order_by(AuthAccount.created_at, AuthAccount.id)
        )
        return list(result.scalars().all())

    async def create_refresh_token(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token_by_hash(
        self,
        token_hash: str,
    ) -> RefreshToken | None:
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(
        self,
        token: RefreshToken,
        revoked_at: datetime,
    ) -> RefreshToken:
        token.revoked_at = revoked_at
        await self.session.flush()
        return token

    async def rotate_refresh_token(
        self,
        old_token: RefreshToken,
        *,
        new_token_hash: str,
        new_expires_at: datetime,
        now: datetime,
    ) -> RefreshToken:
        new_token = RefreshToken(
            user_id=old_token.user_id,
            token_hash=new_token_hash,
            expires_at=new_expires_at,
        )
        self.session.add(new_token)
        await self.session.flush()

        old_token.revoked_at = now
        old_token.replaced_by_token_id = new_token.id
        old_token.last_used_at = now
        await self.session.flush()
        return new_token

    async def revoke_all_refresh_tokens_for_user(
        self,
        user_id: uuid.UUID,
        revoked_at: datetime,
    ) -> int:
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def mark_refresh_token_used(
        self,
        token: RefreshToken,
        used_at: datetime,
    ) -> RefreshToken:
        token.last_used_at = used_at
        await self.session.flush()
        return token
