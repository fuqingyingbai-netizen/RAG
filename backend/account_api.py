"""Company account lifecycle, independent of research/model services."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from auth import (authenticate_user, create_access_token, get_current_user, get_db,
                  get_password_hash, require_admin, validate_new_password, verify_password)
from models import AccountAudit, AccountInvitation, AdminActionConfirmation, User
from account_lifecycle import archive_expired_invitations, remove_invitation
from account_audit import ACTION_LABELS, audit_summary, invitation_number
from account_security import (check_limit, consume_confirmation, consume_ip_attempt, managed_account,
                              management_lock, protect_last_admin, throttle_row)
from schemas import AuthResponse, CurrentUserResponse, LoginRequest, RegisterRequest

router = APIRouter(tags=["Accounts"])


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in_hours: int = Field(default=6, ge=1, le=168)
    role: Literal["user", "admin"] = "user"


class InviteCheck(BaseModel):
    invitation: str = Field(min_length=1, max_length=2048)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool | None = None
    knowledge_access: bool | None = None


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=1000)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)


class AdminConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=128)
    action: Literal["promote_user", "demote_user", "reset_password", "disable_admin", "enable_admin", "create_admin_invitation"]
    target_user_id: int | None = Field(default=None, gt=0)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def timestamp(value):
    return value.isoformat(timespec="seconds") + "Z" if value else None


def token_hash(value):
    value = value.strip()
    if value.startswith(("http://", "https://")):
        try:
            url = urlsplit(value)
            value = (parse_qs(url.fragment).get("invite") or parse_qs(url.query).get("invite") or [""])[0]
        except ValueError:
            value = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise HTTPException(400, "邀请码无效、已过期、已撤销或已使用")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def valid_invitation(db, value):
    invitation = db.scalar(select(AccountInvitation).where(AccountInvitation.token_hash == token_hash(value)))
    if (not invitation or invitation.used_at or invitation.revoked_at or invitation.expires_at <= utcnow()):
        raise HTTPException(400, "邀请码无效、已过期、已撤销或已使用")
    return invitation


def audit(db, actor_id, action, *, target_id=None, invitation_id=None, details=None):
    db.add(AccountAudit(actor_id=actor_id, action=action, target_user_id=target_id,
                        invitation_id=invitation_id, details=details or {}))


def auth_response(user):
    return AuthResponse(access_token=create_access_token(user.username, user.role, user.token_version),
                        username=user.username, role=user.role, must_change_password=user.must_change_password)


def ordinary_account(db, user_id):
    user = managed_account(db, user_id)
    if not user or user.role != "user":
        raise HTTPException(404, "普通账号不存在")
    return user


@router.post("/auth/invitations/validate")
def check_invitation(request: InviteCheck, db: Session = Depends(get_db)):
    invitation = valid_invitation(db, request.invitation)
    return {"valid": True, "expires_at": timestamp(invitation.expires_at), "role": invitation.role}


@router.post("/auth/register", response_model=AuthResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    username = request.username.strip()
    if not username or any(c.isspace() or ord(c) < 32 for c in username):
        raise HTTPException(400, "用户名不能为空或包含空白、控制字符")
    validate_new_password(request.password)
    if request.password != request.confirm_password:
        raise HTTPException(400, "两次输入的密码不一致")
    invitation = valid_invitation(db, request.invitation)
    invitation_id, inviter_id = invitation.id, invitation.created_by_id
    password_hash = get_password_hash(request.password)
    try:
        # Atomic conditional claim works on both PostgreSQL and SQLite. Rollback
        # also releases the invitation if username insertion fails.
        claimed = db.execute(update(AccountInvitation).where(
            AccountInvitation.id == invitation_id, AccountInvitation.used_at.is_(None),
            AccountInvitation.revoked_at.is_(None), AccountInvitation.expires_at > utcnow(),
        ).values(used_at=utcnow()).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(400, "邀请链接无效、已过期、已撤销或已使用")
        if invitation.expires_at <= utcnow():
            db.rollback()
            raise HTTPException(400, "邀请链接已过期")
        user = User(username=username, password_hash=password_hash, role=invitation.role, knowledge_access=False)
        db.add(user)
        db.flush()
        db.execute(update(AccountInvitation).where(AccountInvitation.id == invitation_id).values(used_by_id=user.id))
        audit(db, user.id, "invitation_used", target_id=user.id, invitation_id=invitation_id,
              details={"invited_by_id": inviter_id, "role": invitation.role})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    return auth_response(user)


@router.post("/auth/login", response_model=AuthResponse)
def login(request: LoginRequest, http_request: Request, db: Session = Depends(get_db)):
    consume_ip_attempt(db, http_request)
    failures = throttle_row(db, "login-account", request.username.strip(), 300)
    check_limit(db, failures, 5, 300)
    user = authenticate_user(db, request.username.strip(), request.password)
    if not user:
        failures.attempts += 1
        check_limit(db, failures, 5, 300)
        db.commit()
        raise HTTPException(401, "用户名或密码错误，或账号已停用")
    failures.attempts = 0
    user.last_login_at = utcnow()
    db.commit()
    return auth_response(user)


@router.post("/auth/confirm-admin")
def confirm_admin(request: AdminConfirmation, http_request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    consume_ip_attempt(db, http_request)
    failures = throttle_row(db, "admin-confirm", str(admin.id), 300)
    check_limit(db, failures, 5, 300)
    if not verify_password(request.password.get_secret_value(), admin.password_hash):
        failures.attempts += 1
        check_limit(db, failures, 5, 300)
        db.commit()
        raise HTTPException(400, "管理员密码错误")
    failures.attempts = 0
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=5)
    db.add(AdminActionConfirmation(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=admin.id,
                                  token_version=admin.token_version, action=request.action,
                                  target_user_id=request.target_user_id, expires_at=expires))
    db.commit()
    return {"confirmation_token": token, "expires_at": timestamp(expires)}


@router.get("/auth/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)):
    return CurrentUserResponse(username=current_user.username, role=current_user.role,
                               must_change_password=current_user.must_change_password)


@router.post("/auth/change-password", response_model=AuthResponse)
def change_password(request: PasswordChange, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    validate_new_password(request.new_password)
    if request.new_password != request.confirm_password:
        raise HTTPException(400, "两次输入的密码不一致")
    if request.new_password == request.current_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    failures = throttle_row(db, "password-change", str(current_user.id), 300)
    check_limit(db, failures, 5, 300)
    version = current_user.token_version
    user = db.scalar(select(User).where(User.id == current_user.id).with_for_update().execution_options(populate_existing=True))
    if not user.is_active or version != user.token_version:
        raise HTTPException(401, "登录已失效，请重新登录")
    if not verify_password(request.current_password, user.password_hash):
        failures.attempts += 1
        check_limit(db, failures, 5, 300)
        db.commit()
        raise HTTPException(400, "原密码错误")
    failures.attempts = 0
    user.password_hash = get_password_hash(request.new_password)
    user.must_change_password = False
    user.token_version += 1
    audit(db, user.id, "password_changed", target_id=user.id)
    db.commit()
    return auth_response(user)


@router.post("/admin/invitations", status_code=201)
def create_invitation(request: InviteCreate, http_request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    if request.role == "admin":
        consume_confirmation(db, http_request, admin, "create_admin_invitation")
    token = secrets.token_urlsafe(32)
    invitation = AccountInvitation(token_hash=token_hash(token), created_by_id=admin.id, role=request.role,
                                   expires_at=utcnow() + timedelta(hours=request.expires_in_hours))
    db.add(invitation)
    db.flush()
    audit(db, admin.id, "invitation_created", invitation_id=invitation.id,
          details={"expires_in_hours": request.expires_in_hours, "role": request.role})
    db.commit()
    # Only this response contains the secret; the UI displays a code, not a URL.
    return {"id": invitation.id, "token": token, "expires_at": timestamp(invitation.expires_at), "role": invitation.role}


@router.get("/admin/invitations")
def list_invitations(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     db: Session = Depends(get_db), _: User = Depends(require_admin)):
    archive_expired_invitations(db)
    db.commit()
    now = utcnow()
    visible = AccountInvitation.expires_at > now
    creator, recipient = aliased(User), aliased(User)
    rows = db.execute(select(AccountInvitation, creator.username, recipient.username)
                      .join(creator, creator.id == AccountInvitation.created_by_id)
                      .outerjoin(recipient, recipient.id == AccountInvitation.used_by_id)
                      .where(visible)
                      .order_by(AccountInvitation.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for invitation, created_by, used_by in rows:
        state = ("used" if invitation.used_at else "revoked" if invitation.revoked_at
                 else "expired" if invitation.expires_at <= now else "active")
        items.append({"id": invitation.id, "created_by": created_by, "used_by": used_by, "role": invitation.role,
                      "created_at": timestamp(invitation.created_at), "expires_at": timestamp(invitation.expires_at),
                      "used_at": timestamp(invitation.used_at), "status": state})
    return {"items": items, "total": db.scalar(select(func.count()).select_from(AccountInvitation).where(visible))}


@router.post("/admin/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    result = db.execute(update(AccountInvitation).where(
        AccountInvitation.id == invitation_id, AccountInvitation.used_at.is_(None),
        AccountInvitation.revoked_at.is_(None), AccountInvitation.expires_at > utcnow(),
    ).values(revoked_at=utcnow()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "邀请已失效或已使用，请刷新列表")
    audit(db, admin.id, "invitation_revoked", invitation_id=invitation_id)
    db.commit()
    return {"message": "邀请已撤销"}


@router.delete("/admin/invitations/{invitation_id}")
def delete_invitation(invitation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    invitation = db.scalar(select(AccountInvitation).where(AccountInvitation.id == invitation_id)
                           .with_for_update().execution_options(populate_existing=True))
    if not invitation:
        raise HTTPException(404, "邀请已不存在，请刷新列表")
    if not invitation.used_at and not invitation.revoked_at:
        raise HTTPException(409, "只能删除已撤销或已使用的邀请，请先撤销仍可使用的邀请")
    remove_invitation(db, invitation, actor_id=admin.id, action="invitation_deleted")
    db.commit()
    return {"message": "邀请已删除，历史记录保留在操作日志中"}


@router.get("/admin/users")
def list_users(q: str = Query("", max_length=100), state: str = Query("all", pattern="^(all|active|disabled|archived)$"),
               role: Literal["user", "admin", "all"] = "user",
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    filters = [] if role == "all" else [User.role == role]
    if q.strip():
        filters.append(or_(*(column.contains(q.strip(), autoescape=True) for column in
                             (User.username, User.display_name, User.notes))))
    filters.append(User.archived_at.is_not(None) if state == "archived" else User.archived_at.is_(None))
    if state in {"active", "disabled"}:
        filters.append(User.is_active.is_(state == "active"))
    creator = aliased(User)
    rows = db.execute(select(User, AccountInvitation.id, creator.username)
                      .outerjoin(AccountInvitation, AccountInvitation.used_by_id == User.id)
                      .outerjoin(creator, creator.id == AccountInvitation.created_by_id)
                      .where(*filters).order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"id": user.id, "username": user.username, "is_active": user.is_active, "role": user.role,
              "display_name": user.display_name, "notes": user.notes,
              "is_self": user.id == admin.id,
              "knowledge_access": user.knowledge_access, "must_change_password": user.must_change_password,
              "created_at": timestamp(user.created_at), "last_login_at": timestamp(user.last_login_at), "archived_at": timestamp(user.archived_at),
              "invitation_id": invitation_id, "invited_by": invited_by}
             for user, invitation_id, invited_by in rows]
    missing = [item["id"] for item in items if item["invitation_id"] is None]
    if missing:
        history = db.scalars(select(AccountAudit).where(AccountAudit.action.in_(["invitation_expired", "invitation_deleted"]),
                             AccountAudit.target_user_id.in_(missing)).order_by(AccountAudit.id.desc()))
        sources = {}
        for entry in history:
            sources.setdefault(entry.target_user_id, entry.details)
        for item in items:
            if item["invitation_id"] is None and item["id"] in sources:
                item["invitation_id"] = sources[item["id"]]["invitation_id"]
                item["invited_by"] = sources[item["id"]]["created_by"]
    return {"items": items, "total": db.scalar(select(func.count()).select_from(User).where(*filters)),
            "active_admin_count": db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True), User.archived_at.is_(None)))}


@router.post("/admin/users/{user_id}/archive")
def archive_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = managed_account(db, user_id)
    if user.id == admin.id:
        raise HTTPException(409, "不能归档当前登录账号")
    protect_last_admin(db, user)
    if user.is_active:
        raise HTTPException(409, "请先停用该账号，再归档")
    user.archived_at = utcnow()
    user.token_version += 1
    audit(db, admin.id, "account_archived", target_id=user.id)
    db.commit()
    return {"message": "账号已归档，历史资料已保留"}


@router.post("/admin/users/{user_id}/restore")
def restore_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = managed_account(db, user_id, include_archived=True)
    if not user.archived_at:
        raise HTTPException(409, "账号未归档，请刷新列表")
    user.archived_at = None
    user.is_active = False
    user.token_version += 1
    audit(db, admin.id, "account_restored", target_id=user.id)
    db.commit()
    return {"message": "账号已恢复，仍保持停用，请按需单独启用"}


@router.patch("/admin/users/{user_id}/profile")
def update_profile(user_id: int, request: ProfileUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    values = {field: value.strip() for field, value in request.model_dump(exclude_unset=True).items()}
    if not values:
        raise HTTPException(400, "请填写姓名或备注")
    for field, value in values.items():
        allowed_controls = "\n\r\t" if field == "notes" else ""
        if any((ord(char) < 32 and char not in allowed_controls) or ord(char) == 127 for char in value):
            raise HTTPException(400, "姓名或备注包含不支持的控制字符")
    management_lock(db, admin)
    user = managed_account(db, user_id)
    changed = []
    for field, value in values.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if changed:
        # Record which fields changed, without duplicating private notes in logs.
        audit(db, admin.id, "account_profile_updated", target_id=user.id, details={"fields": sorted(changed)})
    db.commit()
    return {"message": "账号资料已保存", "display_name": user.display_name, "notes": user.notes}


@router.get("/admin/audits")
def list_audits(actor: str = Query("", max_length=100), target: str = Query("", max_length=100),
                action: str = Query("all", max_length=50), start: datetime | None = None, end: datetime | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if action != "all" and action not in ACTION_LABELS:
        raise HTTPException(400, "不支持的操作类型")
    start = start.astimezone(timezone.utc).replace(tzinfo=None) if start and start.tzinfo else start
    end = end.astimezone(timezone.utc).replace(tzinfo=None) if end and end.tzinfo else end
    if start and end and start >= end:
        raise HTTPException(400, "结束时间须晚于开始时间")
    operator, recipient = aliased(User), aliased(User)
    filters = []
    if action != "all":
        filters.append(AccountAudit.action == action)
    if actor.strip() == "系统":
        filters.append(AccountAudit.action == "invitation_expired")
    elif actor.strip():
        filters.append(or_(operator.username.contains(actor.strip(), autoescape=True),
                           operator.display_name.contains(actor.strip(), autoescape=True)))
    if target.strip():
        filters.append(or_(recipient.username.contains(target.strip(), autoescape=True),
                           recipient.display_name.contains(target.strip(), autoescape=True)))
    if start:
        filters.append(AccountAudit.created_at >= start)
    if end:
        filters.append(AccountAudit.created_at < end)
    query = (select(AccountAudit, operator, recipient).join(operator, operator.id == AccountAudit.actor_id)
             .outerjoin(recipient, recipient.id == AccountAudit.target_user_id).where(*filters))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(AccountAudit.created_at.desc(), AccountAudit.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    items = []
    for entry, performed_by, affected in rows:
        items.append({
            "id": entry.id, "action": entry.action, "action_label": ACTION_LABELS.get(entry.action, "其他操作"),
            "actor_username": performed_by.username, "actor_name": performed_by.display_name,
            "is_system": entry.action == "invitation_expired",
            "target_username": affected.username if affected else None,
            "target_name": affected.display_name if affected else None,
            "invitation_id": invitation_number(entry), "summary": audit_summary(entry),
            "created_at": timestamp(entry.created_at),
        })
    return {"items": items, "total": total, "actions": [{"value": value, "label": label} for value, label in ACTION_LABELS.items()]}


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, request: UserUpdate, http_request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = managed_account(db, user_id)
    changes = {}
    if request.is_active is not None and user.is_active != request.is_active:
        if user.role == "admin":
            if not request.is_active:
                protect_last_admin(db, user)
            consume_confirmation(db, http_request, admin, "enable_admin" if request.is_active else "disable_admin", user.id)
        user.is_active = request.is_active
        user.token_version += 1
        changes["is_active"] = user.is_active
    if request.knowledge_access is not None and user.knowledge_access != request.knowledge_access:
        if user.role == "admin":
            raise HTTPException(400, "管理员按角色拥有公司知识库权限")
        user.knowledge_access = request.knowledge_access
        changes["knowledge_access"] = user.knowledge_access
    if changes:
        audit(db, admin.id, "account_updated", target_id=user.id, details=changes)
    db.commit()
    return {"message": "账号已更新", "requires_relogin": user.id == admin.id and "is_active" in changes}


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, http_request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = managed_account(db, user_id)
    if user.id == admin.id:
        raise HTTPException(409, "请使用个人菜单中的修改密码功能")
    consume_confirmation(db, http_request, admin, "reset_password", user.id)
    temporary = "Aa1-" + secrets.token_urlsafe(15)
    user.password_hash = get_password_hash(temporary)
    user.must_change_password = True
    user.token_version += 1
    audit(db, admin.id, "password_reset", target_id=user.id)
    db.commit()
    return {"temporary_password": temporary, "message": "临时密码仅展示一次，用户登录后须修改密码"}


@router.post("/admin/users/{user_id}/promote")
def promote_user(user_id: int, http_request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = ordinary_account(db, user_id)
    if not user.is_active:
        raise HTTPException(409, "请先启用该普通账号，再提升为管理员")
    consume_confirmation(db, http_request, admin, "promote_user", user.id)
    user.role = "admin"
    user.token_version += 1
    audit(db, admin.id, "account_promoted", target_id=user.id, details={"from_role": "user", "to_role": "admin"})
    db.commit()
    return {"message": "已提升为管理员，该账号需从管理员入口重新登录"}


@router.post("/admin/users/{user_id}/demote")
def demote_user(user_id: int, http_request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    management_lock(db, admin)
    user = managed_account(db, user_id)
    if user.role != "admin":
        raise HTTPException(409, "该账号已不是管理员，请刷新列表")
    protect_last_admin(db, user)
    consume_confirmation(db, http_request, admin, "demote_user", user.id)
    user.role = "user"
    user.token_version += 1
    audit(db, admin.id, "account_demoted", target_id=user.id, details={"from_role": "admin", "to_role": "user"})
    db.commit()
    return {"message": "已降为普通账号，该账号需重新登录", "requires_relogin": user.id == admin.id}
