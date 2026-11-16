"""Account-owned honor ledger. No model calls and no changes to document permissions."""
import asyncio
import copy
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from weakref import WeakSet

from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, case, delete, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, SessionLocal
from models import User

log = logging.getLogger(__name__)
initialized = WeakSet()
SHANGHAI = timezone(timedelta(hours=8))
KINDS = {'read': '有效阅读', 'upload': '新资料入库', 'note': '首次发布笔记', 'adjust': '人工纠正'}
DEFAULT = {'enabled': True, 'leaderboard_enabled': True, 'read_seconds': 30,
           'read_points': 2, 'read_limit': 5, 'upload_points': 10, 'upload_limit': 3,
           'note_points': 15, 'note_limit': 2,
           'levels': [{'threshold': 0, 'name': '初识'}, {'threshold': 100, 'name': '探索'},
                      {'threshold': 300, 'name': '同行'}, {'threshold': 800, 'name': '共建'},
                      {'threshold': 2000, 'name': '领航'}]}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def day(value=None):
    return (value or now()).replace(tzinfo=timezone.utc).astimezone(SHANGHAI).date().isoformat()


def key(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def iso(value):
    return value.isoformat() + 'Z' if value else None


class PointsRule(Base):
    __tablename__ = 'knowledge_points_rules'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    policy: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default='初始规则')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PointsAccount(Base):
    __tablename__ = 'knowledge_points_accounts'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint('total >= 0', name='ck_knowledge_points_total_nonnegative'),)


class PointsEvent(Base):
    __tablename__ = 'knowledge_points_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    kind: Mapped[str] = mapped_column(String(20))
    reward_key: Mapped[str] = mapped_column(String(64), default='')
    content_key: Mapped[str] = mapped_column(String(64), default='', index=True)
    rule_id: Mapped[int] = mapped_column(Integer)
    policy: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    business_day: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    reason: Mapped[str] = mapped_column(String(100), default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index('ix_points_pending', 'status', 'retry_at'),
                      Index('ix_points_kind_document', 'kind', 'document_id'))


class PointsEntry(Base):
    __tablename__ = 'knowledge_points_ledger'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    unique_key: Mapped[str] = mapped_column(String(64), unique=True)
    event_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    document_id: Mapped[str] = mapped_column(String(64), default='')
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[int] = mapped_column(Integer)
    business_day: Mapped[str] = mapped_column(String(10), index=True)
    original_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index('ix_points_user_day_kind', 'user_id', 'business_day', 'kind'),)


class PointsReadSession(Base):
    __tablename__ = 'knowledge_points_read_sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    lineage: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[int] = mapped_column(Integer)
    policy: Mapped[dict] = mapped_column(JSON)
    token_version: Mapped[int] = mapped_column(Integer)
    business_day: Mapped[str] = mapped_column(String(10))
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    interacted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index('ix_points_read_user_time', 'user_id', 'last_at'),)


class PointsSource(Base):
    __tablename__ = 'knowledge_points_sources'
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lineage: Mapped[str] = mapped_column(String(64), index=True)


TABLES = [m.__table__ for m in (PointsRule, PointsAccount, PointsEvent, PointsEntry, PointsReadSession, PointsSource)]


def insert_ignore(db, model, values, columns):
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return db.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=columns))


def initialize(engine):
    with engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            from sqlalchemy import text
            connection.execute(text('SELECT pg_advisory_xact_lock(2026111601)'))
        Base.metadata.create_all(connection, tables=TABLES)
    with SessionLocal(bind=engine) as db:
        insert_ignore(db, PointsRule, {'id': 1, 'effective_at': now(), 'policy': copy.deepcopy(DEFAULT),
                                     'reason': '启用后开始计分，不追溯历史行为'}, ['id'])
        db.commit()
    initialized.add(engine)


def available(db):
    if db.bind not in initialized:
        raise HTTPException(503, '积分暂不可用，资料阅读和上传仍可正常使用。')


def current_rule(db, at=None):
    return db.scalar(select(PointsRule).where(PointsRule.cancelled_at.is_(None),
        PointsRule.effective_at <= (at or now())).order_by(PointsRule.effective_at.desc(), PointsRule.id.desc()).limit(1))


def account(db, user_id):
    insert_ignore(db, PointsAccount, {'user_id': user_id, 'total': 0, 'excluded': False, 'revision': 0}, ['user_id'])
    # A real write serializes SQLite too; PostgreSQL retains this row lock until commit.
    db.execute(update(PointsAccount).where(PointsAccount.user_id == user_id).values(revision=PointsAccount.revision + 1))
    return db.scalar(select(PointsAccount).where(PointsAccount.user_id == user_id).execution_options(populate_existing=True))


def valid_user(user):
    return user and user.is_active and not user.archived_at and not user.must_change_password


def document(db, doc_id, user):
    from company_catalog import CompanyDocument, can_read, is_owner, media_kind
    import company_knowledge as kb
    doc = db.get(CompanyDocument, doc_id)
    if not doc or doc.index_id != kb.settings()['index_id'] or not can_read(doc, user):
        raise HTTPException(404, '资料不存在或没有阅读权限。')
    if doc.state != 'ready' or not doc.is_current or doc.confidentiality != 'internal' or doc.visibility != 'members' or media_kind(doc):
        raise HTTPException(409, '该资料当前不参与阅读积分，仍可按原权限阅读。')
    if is_owner(doc, user):
        raise HTTPException(409, '阅读本人资料不计积分。')
    return doc


def lineage(db, doc):
    from company_catalog import CompanyDocument
    saved = db.get(PointsSource, doc.id)
    if saved:
        return saved.lineage
    if doc.note_id:
        identity = key('note', doc.note_id)
    else:
        # Persist the identity before metadata can change; it is independent of filename thereafter.
        siblings = list(db.scalars(select(CompanyDocument.id).where(CompanyDocument.index_id == doc.index_id,
            CompanyDocument.owner == doc.owner, CompanyDocument.knowledge_project_id == doc.knowledge_project_id,
            CompanyDocument.folder_id == doc.folder_id, CompanyDocument.title == doc.title)
            .order_by(CompanyDocument.version, CompanyDocument.created_at, CompanyDocument.id)))
        existing = db.scalar(select(PointsSource.lineage).where(PointsSource.document_id.in_(siblings)).limit(1))
        identity = existing or key('file', siblings[0] if siblings else doc.id)
    insert_ignore(db, PointsSource, {'document_id': doc.id, 'lineage': identity}, ['document_id'])
    return identity


def capture_ready(db, doc_id):
    """Called inside the ingestion transaction; failure cannot roll back the original business write."""
    if db.bind not in initialized:
        return
    try:
        with db.begin_nested():
            from company_catalog import CompanyDocument, media_kind
            doc = db.get(CompanyDocument, doc_id)
            started = db.scalar(select(func.min(PointsRule.effective_at)))
            if not doc or doc.state != 'ready' or doc.created_at < started:
                return
            lineage(db, doc)
            event_id = key('ready', doc.id)
            if db.get(PointsEvent, event_id):
                return
            at = doc.updated_at or now()
            rule = current_rule(db, at)
            if not rule:
                return
            kind, user_id = ('note', doc.owner_user_id) if doc.note_id else ('upload', doc.uploaded_by_user_id)
            user = db.get(User, user_id) if user_id else None
            reason = ''
            digest = doc.sha256
            if doc.note_id:
                from company_notes import CompanyNote, CompanyNotePublication
                note = db.get(CompanyNote, doc.note_id)
                author = db.scalar(select(User).where(User.username == note.created_by)) if note else None
                user_id = author.id if author else None
                user = author
                publication = db.get(CompanyNotePublication, doc.id)
                if publication:
                    digest = key(publication.content)
            if not rule.policy['enabled']:
                reason = '积分已暂停'
            elif not valid_user(user):
                reason = '账号当前不可计分'
            elif (not doc.note_id and doc.version != 1) or not doc.is_current:
                reason = '后续版本不重复奖励'
            elif (kind != 'upload' and (doc.confidentiality != 'internal' or doc.visibility != 'members')) or not doc.object_key or not doc.size or not digest or media_kind(doc):
                reason = '该资料不符合共享贡献奖励条件'
            elif not doc.note_id and db.scalar(select(CompanyDocument.id).where(
                    CompanyDocument.sha256 == doc.sha256, CompanyDocument.id != doc.id,
                    CompanyDocument.created_at < started).limit(1)):
                reason = '已有资料不重复奖励'
            insert_ignore(db, PointsEvent, {'id': event_id, 'user_id': user_id, 'document_id': doc.id,
                'kind': kind, 'reward_key': key(user_id, kind, doc.note_id or digest),
                'content_key': key(user_id, kind, digest), 'rule_id': rule.id,
                'policy': copy.deepcopy(rule.policy), 'occurred_at': at, 'business_day': day(at),
                'status': 'ignored' if reason else 'pending', 'reason': reason, 'attempts': 0}, ['id'])
    except Exception:
        log.exception('knowledge_points_capture_failed document_id=%s', doc_id)


def award_event(db, event):
    user = db.get(User, event.user_id) if event.user_id else None
    if not valid_user(user):
        event.status, event.reason = 'ignored', '账号当前不可计分'
        return 0
    row = account(db, user.id)
    if row.excluded:
        event.status, event.reason = 'ignored', '该账号不参与积分'
        return 0
    if db.scalar(select(PointsEntry.id).where(PointsEntry.unique_key == event.reward_key)):
        event.status, event.reason = 'ignored', '同一行为或内容不重复奖励'
        return 0
    if event.content_key and db.scalar(select(PointsEvent.id).where(PointsEvent.id != event.id,
            PointsEvent.user_id == user.id, PointsEvent.content_key == event.content_key,
            PointsEvent.status == 'awarded').limit(1)):
        event.status, event.reason = 'ignored', '相同内容不重复奖励'
        return 0
    amount = event.policy[event.kind + '_points']
    count = db.scalar(select(func.count()).select_from(PointsEntry).where(PointsEntry.user_id == user.id,
        PointsEntry.kind == event.kind, PointsEntry.business_day == event.business_day, PointsEntry.amount > 0))
    if count >= event.policy[event.kind + '_limit'] or amount == 0:
        event.status, event.reason = 'ignored', '当日该类奖励已达上限或未启用'
        return 0
    db.add(PointsEntry(user_id=user.id, unique_key=event.reward_key, event_id=event.id,
        document_id=event.document_id, kind=event.kind, amount=amount, rule_id=event.rule_id,
        business_day=event.business_day, reason=KINDS[event.kind]))
    row.total += amount
    event.status, event.reason = 'awarded', '已入账'
    db.flush()
    return amount


def process_pending(factory=None, limit=50):
    factory = factory or SessionLocal
    with factory() as db:
        if db.bind not in initialized:
            return
        ids = list(db.scalars(select(PointsEvent.id).where(PointsEvent.status.in_(['pending', 'failed']),
            (PointsEvent.retry_at.is_(None) | (PointsEvent.retry_at <= now())))
            .order_by(PointsEvent.occurred_at, PointsEvent.id).limit(limit)))
    for event_id in ids:
        try:
            with factory() as db:
                event = db.scalar(select(PointsEvent).where(PointsEvent.id == event_id,
                    PointsEvent.status.in_(['pending', 'failed'])).with_for_update(skip_locked=True))
                if not event:
                    continue
                # Claim by a database write before loading cached ORM state (also on SQLite).
                changed = db.execute(update(PointsEvent).where(PointsEvent.id == event_id,
                    PointsEvent.status.in_(['pending', 'failed'])).values(status='processing'))
                if changed.rowcount != 1:
                    continue
                db.refresh(event)
                from company_catalog import CompanyDocument, can_read
                doc, user = db.get(CompanyDocument, event.document_id), db.get(User, event.user_id)
                # Upload credit belongs to the actor, independently of document ownership and ACL.
                # Reading/notes retain their existing shared-knowledge eligibility.
                if (not doc or not valid_user(user) or doc.state != 'ready'
                        or (event.kind != 'upload' and (not can_read(doc, user)
                            or doc.confidentiality != 'internal' or doc.visibility != 'members'))):
                    event.status, event.reason = 'ignored', '资料或账号状态已变化'
                else:
                    award_event(db, event)
                db.commit()
        except Exception:
            log.exception('knowledge_points_award_failed event_id=%s', event_id)
            with factory() as db:
                event = db.get(PointsEvent, event_id)
                if event and event.status in ('pending', 'failed'):
                    event.attempts += 1
                    event.status, event.reason = 'failed', '积分结算失败，系统会自动重试'
                    event.retry_at = now() + timedelta(seconds=min(3600, 5 * 2 ** min(event.attempts, 9)))
                    db.commit()


def reconcile(factory=None):
    """Recover an outbox missed during a transient points failure without touching old material."""
    from company_catalog import CompanyDocument
    factory = factory or SessionLocal
    with factory() as db:
        if db.bind not in initialized:
            return
        started = db.scalar(select(func.min(PointsRule.effective_at)))
        recorded = select(PointsEvent.document_id).where(PointsEvent.kind.in_(['upload', 'note']))
        docs = db.scalars(select(CompanyDocument).where(CompanyDocument.created_at >= started,
            CompanyDocument.state == 'ready', ~CompanyDocument.id.in_(recorded))
            .order_by(CompanyDocument.updated_at, CompanyDocument.id).limit(50))
        for doc in docs:
            capture_ready(db, doc.id)
        expired = list(db.scalars(select(PointsReadSession.id).where(
            PointsReadSession.expires_at < now() - timedelta(days=30)).limit(500)))
        if expired:
            db.execute(delete(PointsReadSession).where(PointsReadSession.id.in_(expired)))
        db.commit()


async def worker():
    iteration = 0
    while True:
        try:
            if iteration % 6 == 0:
                await asyncio.to_thread(reconcile)
            await asyncio.to_thread(process_pending)
        except Exception:
            log.exception('knowledge_points_worker_failed')
        iteration += 1
        await asyncio.sleep(5)


def start_read(db, user, doc_id):
    available(db)
    doc = document(db, doc_id, user)
    from company_catalog import CompanyAuditEvent
    delivered = db.scalar(select(CompanyAuditEvent.id).where(CompanyAuditEvent.actor_id == user.id,
        CompanyAuditEvent.target_type == 'document', CompanyAuditEvent.target_id == doc.id,
        CompanyAuditEvent.action == 'document.preview', CompanyAuditEvent.created_at >= now() - timedelta(minutes=5)).limit(1))
    if not delivered:
        raise HTTPException(409, '请先成功打开资料正文，再开始阅读计分。')
    row = account(db, user.id)
    rule = current_rule(db)
    if not rule.policy['enabled'] or row.excluded:
        raise HTTPException(409, '积分当前已暂停或该账号不参与积分。')
    recent = db.scalar(select(func.count()).select_from(PointsReadSession).where(
        PointsReadSession.user_id == user.id, PointsReadSession.last_at >= now() - timedelta(minutes=1)))
    if recent >= 20:
        raise HTTPException(429, '阅读计分会话创建过于频繁，请稍后重试。', headers={'Retry-After': '60'})
    today = day()
    identity = lineage(db, doc)
    reward_key = key(user.id, 'read', identity, today)
    prior = db.scalar(select(PointsEntry.id).where(PointsEntry.unique_key == reward_key))
    if prior:
        db.commit()
        return {'eligible': False, 'reason': '今日已获得该资料的阅读积分'}
    db.execute(update(PointsReadSession).where(PointsReadSession.user_id == user.id,
        PointsReadSession.closed.is_(False)).values(closed=True))
    stamp = now()
    session = PointsReadSession(user_id=user.id, document_id=doc.id, lineage=identity,
        rule_id=rule.id, policy=copy.deepcopy(rule.policy), token_version=user.token_version,
        business_day=today, last_at=stamp, expires_at=stamp + timedelta(minutes=15))
    db.add(session)
    db.commit()
    return {'eligible': True, 'session_id': session.id, 'heartbeat_seconds': 10,
            'required_seconds': rule.policy['read_seconds'], 'seconds': 0}


def note_preview(db, user, doc, references):
    if db.bind not in initialized or not any(row.get('text', '').strip() for row in references):
        return
    try:
        from company_audit import record
        with db.begin_nested():
            record(db, user, 'document.preview', doc, details={'kind': 'text_excerpts'})
        db.commit()
    except Exception:
        db.rollback()
        log.exception('knowledge_points_preview_receipt_failed')


def heartbeat(db, user, session_id, sequence, active, interacted):
    available(db)
    # Lock the account first for both start and heartbeat to serialize multiple devices.
    account(db, user.id)
    session = db.scalar(select(PointsReadSession).where(PointsReadSession.id == session_id,
        PointsReadSession.user_id == user.id).execution_options(populate_existing=True))
    stamp = now()
    if not session:
        raise HTTPException(404, '阅读会话不存在。')
    if session.awarded:
        db.commit()
        return {'complete': True, 'awarded': 0, 'reason': '已完成，不重复计分'}
    if session.closed or session.expires_at < stamp or session.business_day != day(stamp) or session.token_version != user.token_version:
        raise HTTPException(409, '阅读会话已结束，请重新打开资料。')
    document(db, session.document_id, user)
    if not current_rule(db).policy['enabled']:
        raise HTTPException(409, '积分当前已暂停。')
    if sequence <= session.sequence:
        db.commit()
        return {'complete': False, 'seconds': session.seconds, 'awarded': 0}
    if sequence != session.sequence + 1:
        raise HTTPException(409, '阅读心跳顺序无效，请重新打开资料。')
    elapsed = (stamp - session.last_at).total_seconds()
    if elapsed < 5:
        raise HTTPException(429, '阅读心跳过于频繁。', headers={'Retry-After': '5'})
    # Gaps cannot be reported as accumulated time; hidden tabs report inactive heartbeats.
    if active and 5 <= elapsed <= 20:
        session.seconds += min(10, int(elapsed))
    session.sequence = sequence
    session.last_at = stamp
    session.interacted = session.interacted or (active and interacted)
    session.expires_at = stamp + timedelta(minutes=15)
    amount = 0
    complete = session.seconds >= session.policy['read_seconds'] and session.interacted
    reason = ''
    if complete:
        identity = key(user.id, 'read', session.lineage, session.business_day)
        event = db.get(PointsEvent, identity)
        if not event:
            event = PointsEvent(id=identity, user_id=user.id, document_id=session.document_id,
                kind='read', reward_key=identity, rule_id=session.rule_id, policy=session.policy,
                occurred_at=stamp, business_day=session.business_day)
            db.add(event)
        amount = award_event(db, event)
        session.awarded = True
        reason = event.reason
    db.commit()
    return {'complete': complete, 'seconds': session.seconds, 'awarded': amount, 'reason': reason}


def period_start(period):
    today = datetime.fromisoformat(day()).date()
    if period == 'week':
        return (today - timedelta(days=today.weekday())).isoformat()
    if period == 'month':
        return today.replace(day=1).isoformat()
    return '0001-01-01'


def level(policy, total):
    items = policy['levels']
    index = max(i for i, item in enumerate(items) if item['threshold'] <= total)
    return {'number': index + 1, **items[index], 'next': items[index + 1] if index + 1 < len(items) else None}


def leaderboard(db, period, page=1, page_size=20, user_id=None):
    rule = current_rule(db)
    if not rule.policy['leaderboard_enabled']:
        return {'items': [], 'total': 0, 'me': None, 'enabled': False, 'page': page}
    scores = (select(PointsEntry.user_id, func.sum(PointsEntry.amount).label('score'),
        func.sum(case((PointsEntry.kind == 'read', PointsEntry.amount), else_=0)).label('reading'))
        .where(PointsEntry.business_day >= period_start(period)).group_by(PointsEntry.user_id).subquery())
    # Admin-only display_name and notes are intentionally never serialized.
    query = (select(User.id, User.username, scores.c.score, scores.c.reading, PointsAccount.total)
        .join(scores, scores.c.user_id == User.id).join(PointsAccount, PointsAccount.user_id == User.id)
        .where(User.role == 'user', User.is_active.is_(True), User.archived_at.is_(None),
               User.must_change_password.is_(False), PointsAccount.excluded.is_(False), scores.c.score > 0))
    base = query.subquery()
    ranked = select(base, func.dense_rank().over(order_by=base.c.score.desc()).label('rank')).subquery()
    total = db.scalar(select(func.count()).select_from(ranked))

    def serialize(row):
        return {'user_id': row.id, 'username': row.username, 'score': row.score,
                'reading': row.reading or 0, 'contribution': row.score - (row.reading or 0),
                'rank': row.rank, 'level': level(rule.policy, row.total)}
    rows = db.execute(select(ranked).order_by(ranked.c.rank, ranked.c.id).offset((page - 1) * page_size).limit(page_size))
    me = db.execute(select(ranked).where(ranked.c.id == user_id)).first() if user_id else None
    return {'items': [serialize(row) for row in rows], 'total': total, 'me': serialize(me) if me else None,
            'enabled': True, 'page': page, 'page_size': page_size}


def summary(db, user):
    available(db)
    rule = current_rule(db)
    row = db.get(PointsAccount, user.id)
    total = row.total if row else 0
    earned = {kind: 0 for kind in ('read', 'upload', 'note')}
    for kind, count in db.execute(select(PointsEntry.kind, func.count()).where(PointsEntry.user_id == user.id,
            PointsEntry.business_day == day(), PointsEntry.amount > 0).group_by(PointsEntry.kind)):
        if kind in earned:
            earned[kind] = count
    def score(start):
        return db.scalar(select(func.coalesce(func.sum(PointsEntry.amount), 0)).where(
            PointsEntry.user_id == user.id, PointsEntry.business_day >= start))
    return {'total': total, 'today': score(day()), 'month': score(period_start('month')),
            'level': level(rule.policy, total), 'policy': rule.policy, 'rule_id': rule.id,
            'effective_at': iso(rule.effective_at), 'earned': earned, 'excluded': bool(row and row.excluded),
            'rank': leaderboard(db, 'month', user_id=user.id)['me'], 'server_day': day()}
