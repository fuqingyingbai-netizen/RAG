"""Database-backed safeguards shared by account mutations and authentication."""
import hashlib
import hmac
import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

import auth
from models import AccountManagementLock, AdminActionConfirmation, AuthThrottle, User


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def throttle_row(db, scope, value, seconds):
    # Neither IPs nor account names are stored as throttle keys.
    key = hmac.new(auth.SECRET_KEY.encode(), (scope + ":" + value).encode(), hashlib.sha256).hexdigest()
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(AuthThrottle).values(key=key, window_started_at=now(), attempts=0)
               .on_conflict_do_nothing(index_elements=[AuthThrottle.key]))
    row = db.scalar(select(AuthThrottle).where(AuthThrottle.key == key).with_for_update()
                    .execution_options(populate_existing=True))
    if row.window_started_at + timedelta(seconds=seconds) <= now():
        row.window_started_at, row.attempts = now(), 0
    return row


def check_limit(db, row, maximum, seconds):
    if row.attempts >= maximum:
        retry = max(1, math.ceil((row.window_started_at + timedelta(seconds=seconds) - now()).total_seconds()))
        db.commit()
        raise HTTPException(429, "尝试次数过多，请稍后再试", headers={"Retry-After": str(retry)})


def consume_ip_attempt(db, request):
    # Forwarding headers are intentionally not trusted as client identity.
    row = throttle_row(db, "login-ip", request.client.host if request.client else "unknown", 60)
    check_limit(db, row, 60, 60)
    row.attempts += 1
    db.commit()


def management_lock(db, actor):
    actor_version = actor.token_version
    locked = db.execute(update(AccountManagementLock).where(AccountManagementLock.id == 1)
                        .values(revision=AccountManagementLock.revision + 1))
    if locked.rowcount != 1:
        raise HTTPException(503, "账号管理暂不可用，请检查数据库迁移")
    db.refresh(actor)
    if not actor.is_active or actor.archived_at or actor.role != "admin" or actor.token_version != actor_version or actor.must_change_password:
        raise HTTPException(401, "登录已失效，请重新登录")


def managed_account(db, user_id, *, include_archived=False):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not user:
        raise HTTPException(404, "账号不存在")
    if user.archived_at and not include_archived:
        raise HTTPException(409, "账号已归档，请先恢复后再操作")
    return user


def protect_last_admin(db, user):
    if user.role == "admin" and user.is_active:
        count = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
        if count <= 1:
            raise HTTPException(409, "至少须保留一个启用的管理员，无法停用或降级最后一个管理员")


def consume_confirmation(db, request, actor, action, target_id=None):
    digest = hashlib.sha256(request.headers.get("X-Admin-Confirmation", "").encode()).hexdigest()
    result = db.execute(update(AdminActionConfirmation).where(
        AdminActionConfirmation.token_hash == digest,
        AdminActionConfirmation.user_id == actor.id,
        AdminActionConfirmation.token_version == actor.token_version,
        AdminActionConfirmation.action == action,
        AdminActionConfirmation.target_user_id == target_id,
        AdminActionConfirmation.used_at.is_(None), AdminActionConfirmation.expires_at > now(),
    ).values(used_at=now()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(403, "请验证管理员密码后重试")


def cleanup_security_records(db):
    db.execute(delete(AdminActionConfirmation).where(AdminActionConfirmation.expires_at <= now()))
    db.execute(delete(AuthThrottle).where(AuthThrottle.window_started_at < now() - timedelta(days=1)))
