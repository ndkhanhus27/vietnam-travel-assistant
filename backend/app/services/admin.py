from __future__ import annotations

import logging

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repositories.auth import AuthRepository
from app.security.password import hash_password
from app.services.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, normalize_email


logger = logging.getLogger(__name__)


async def bootstrap_admin(session: AsyncSession) -> None:
    if not settings.admin_bootstrap_enabled:
        return

    email = normalize_email(settings.admin_email)
    password = settings.admin_initial_password.get_secret_value()
    if not email or not password:
        logger.warning(
            "Admin bootstrap enabled but ADMIN_EMAIL or "
            "ADMIN_INITIAL_PASSWORD is missing"
        )
        return
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        logger.warning("Admin bootstrap skipped because ADMIN_EMAIL is invalid")
        return
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        logger.warning(
            "Admin bootstrap skipped because the initial password does not "
            "meet the configured length policy"
        )
        return

    repository = AuthRepository(session)
    try:
        user = await repository.get_user_by_email(email)
        if user is None:
            user = await repository.create_user(
                email=email,
                display_name="Administrator",
                is_verified=False,
            )
        local_account = await repository.get_local_account_for_user(user.id)
        if local_account is None:
            await repository.create_local_account(
                user_id=user.id,
                password_hash=hash_password(password),
            )
        user.is_admin = True
        user.is_active = True
        await session.commit()
        logger.info("Development admin account is ready")
    except Exception:
        await session.rollback()
        raise
