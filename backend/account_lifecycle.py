"""Expire live invitation records while retaining a secret-free audit history."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from database import SessionLocal
from models import AccountAudit, AccountInvitation, User
from account_security import cleanup_security_records

logger = logging.getLogger(__name__)


def remove_invitation(db, invitation, *, actor_id, action):
    """Retain source attribution and audit history in the same deletion transaction."""
    creator = db.get(User, invitation.created_by_id)
    recipient = db.get(User, invitation.used_by_id) if invitation.used_by_id else None
    def stamp(value):
        return value.isoformat(timespec="seconds") + "Z" if value else None
    snapshot = {
        "performed_by": "system" if action == "invitation_expired" else "admin",
        "invitation_id": invitation.id, "role": invitation.role,
        "created_by_id": invitation.created_by_id, "created_by": creator.username,
        "created_at": stamp(invitation.created_at), "expires_at": stamp(invitation.expires_at),
        "used_at": stamp(invitation.used_at), "used_by_id": invitation.used_by_id,
        "used_by": recipient.username if recipient else None,
        "revoked_at": stamp(invitation.revoked_at),
        "previous_status": "used" if invitation.used_at else "revoked" if invitation.revoked_at else "expired",
    }
    for entry in db.scalars(select(AccountAudit).where(AccountAudit.invitation_id == invitation.id)):
        details = entry.details if isinstance(entry.details, dict) else {}
        entry.details = {**details, "invitation_id": invitation.id}
        entry.invitation_id = None
    db.add(AccountAudit(actor_id=actor_id, target_user_id=invitation.used_by_id,
                        action=action, details=snapshot))
    # Remove audit foreign-key references before deleting the invitation itself.
    db.flush()
    db.delete(invitation)
    db.flush()


def archive_expired_invitations(db, batch_size=200):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = db.scalars(select(AccountInvitation).where(AccountInvitation.expires_at <= cutoff)
                         .order_by(AccountInvitation.id).limit(batch_size).with_for_update(skip_locked=True)).all()
    count = 0
    for invitation in expired:
        # This conditional write also serializes cleanup on SQLite, where row
        # locks are unavailable. Another worker may already have deleted it.
        claimed = db.execute(update(AccountInvitation).where(
            AccountInvitation.id == invitation.id, AccountInvitation.expires_at <= cutoff,
        ).values(expires_at=AccountInvitation.expires_at).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            continue
        db.refresh(invitation)
        remove_invitation(db, invitation, actor_id=invitation.created_by_id, action="invitation_expired")
        count += 1
    return count


def cleanup_once():
    with SessionLocal() as db:
        count = archive_expired_invitations(db)
        cleanup_security_records(db)
        db.commit()
        return count


async def invitation_cleanup_loop(interval=60):
    while True:
        try:
            await asyncio.to_thread(cleanup_once)
        except Exception:
            logger.exception("Invitation expiry cleanup failed; retrying on next interval")
        await asyncio.sleep(interval)
