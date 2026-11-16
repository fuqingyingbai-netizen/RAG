"""Personal and administrator points endpoints; client inputs never specify an earned reward."""
import copy
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth import get_knowledge_current_user
from database import SessionLocal
from models import User
import company_points as points
from company_points import PointsAccount, PointsEntry, PointsEvent, PointsRule

class PointsRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except SQLAlchemyError as exc:
                points.log.warning('knowledge_points_database_unavailable kind=%s', type(exc).__name__)
                return JSONResponse({'detail': '积分服务暂时繁忙，请稍后重试；不影响资料阅读和上传。'},
                    status_code=503, headers={'Retry-After': '5'})
        return handler


router = APIRouter(tags=['Knowledge points'], route_class=PointsRoute)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Level(StrictBody):
    threshold: int = Field(ge=0, le=100000000, strict=True)
    name: str = Field(min_length=1, max_length=20)


class Policy(StrictBody):
    enabled: bool = Field(strict=True)
    leaderboard_enabled: bool = Field(strict=True)
    read_seconds: int = Field(ge=10, le=600, strict=True)
    read_points: int = Field(ge=0, le=1000, strict=True)
    read_limit: int = Field(ge=0, le=100, strict=True)
    upload_points: int = Field(ge=0, le=1000, strict=True)
    upload_limit: int = Field(ge=0, le=100, strict=True)
    note_points: int = Field(ge=0, le=1000, strict=True)
    note_limit: int = Field(ge=0, le=100, strict=True)
    levels: list[Level] = Field(min_length=2, max_length=10)

    @field_validator('levels')
    @classmethod
    def ordered_levels(cls, value):
        thresholds = [row.threshold for row in value]
        if thresholds[0] != 0 or thresholds != sorted(set(thresholds)):
            raise ValueError('等级门槛必须从0开始并严格递增')
        return value


class RuleEdit(StrictBody):
    expected_version: int = Field(gt=0, strict=True)
    policy: Policy
    reason: str = Field(min_length=2, max_length=500)
    immediate_pause: bool = False

    @model_validator(mode='after')
    def pause_only(self):
        if self.immediate_pause and self.policy.enabled:
            raise ValueError('立即生效仅用于紧急暂停积分')
        return self


class ReadStart(StrictBody):
    document_id: str = Field(min_length=1, max_length=64)


class Heartbeat(StrictBody):
    sequence: int = Field(ge=1, le=10000, strict=True)
    active: bool = Field(strict=True)
    interacted: bool = Field(strict=True)


class Participation(StrictBody):
    excluded: bool = Field(strict=True)
    reason: str = Field(min_length=2, max_length=500)


class Adjustment(StrictBody):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    amount: int = Field(ge=-1000, le=1000, strict=True)
    reason: str = Field(min_length=2, max_length=500)
    original_id: str = Field(default='', max_length=64)

    @model_validator(mode='after')
    def nonzero(self):
        if not self.amount or (self.amount < 0 and not self.original_id):
            raise ValueError('撤回必须关联原奖励；调整分数不能为0')
        return self


def administrator(user=Depends(get_knowledge_current_user)):
    if user.role != 'admin':
        raise HTTPException(403, '仅管理员可管理积分。')
    return user


def serialize_rule(rule):
    return {'version': rule.id, 'policy': rule.policy, 'effective_at': points.iso(rule.effective_at),
            'cancelled_at': points.iso(rule.cancelled_at), 'reason': rule.reason,
            'actor_id': rule.actor_id, 'created_at': points.iso(rule.created_at)}


def title_for(db, doc_id, user):
    from company_catalog import CompanyDocument, can_read
    import company_knowledge as kb
    doc = db.get(CompanyDocument, doc_id) if doc_id else None
    if doc and doc.index_id == kb.settings()['index_id'] and can_read(doc, user):
        return doc.title
    return '关联资料已不可访问' if doc_id else ''


@router.get('/points/me')
def my_points(user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        return points.summary(db, user)


@router.get('/points/rules')
def rules(user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        points.available(db)
        current = points.current_rule(db)
        upcoming = db.scalars(select(PointsRule).where(PointsRule.cancelled_at.is_(None),
            PointsRule.effective_at > points.now()).order_by(PointsRule.effective_at, PointsRule.id))
        return {'current': serialize_rule(current), 'upcoming': [serialize_rule(row) for row in upcoming],
                'timezone': 'Asia/Shanghai', 'honor_only': True}


def ledger_rows(db, actor, user_id, page, page_size, kind='', start=None, end=None):
    query = select(PointsEntry, User.username).join(User, User.id == PointsEntry.user_id)
    if user_id is not None:
        query = query.where(PointsEntry.user_id == user_id)
    if kind:
        query = query.where(PointsEntry.kind == kind)
    if start:
        query = query.where(PointsEntry.business_day >= start.isoformat())
    if end:
        query = query.where(PointsEntry.business_day <= end.isoformat())
    if start and end and start > end:
        raise HTTPException(422, '开始日期不能晚于结束日期。')
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(PointsEntry.created_at.desc(), PointsEntry.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for entry, username in rows:
        items.append({key: getattr(entry, key) for key in ('id', 'user_id', 'kind', 'amount', 'rule_id',
            'business_day', 'original_id', 'actor_id', 'reason')} | {'username': username,
            'created_at': points.iso(entry.created_at), 'title': title_for(db, entry.document_id, actor)})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/points/ledger')
def my_ledger(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              kind: Literal['', 'read', 'upload', 'note', 'adjust'] = '', start: date | None = None,
              end: date | None = None, user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        points.available(db)
        return ledger_rows(db, user, user.id, page, page_size, kind, start, end)


@router.get('/points/leaderboard')
def leaderboard(period: Literal['week', 'month', 'all'] = 'month', page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100), user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        points.available(db)
        return points.leaderboard(db, period, page, page_size, user.id)


@router.post('/points/read-sessions')
def start_read(body: ReadStart, user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        return points.start_read(db, user, body.document_id)


@router.post('/points/read-sessions/{session_id}/heartbeat')
def heartbeat(session_id: str, body: Heartbeat, user=Depends(get_knowledge_current_user)):
    with SessionLocal() as db:
        return points.heartbeat(db, user, session_id, body.sequence, body.active, body.interacted)


@router.get('/admin/points/users')
def users(q: str = Query('', max_length=100), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        query = select(User, PointsAccount).outerjoin(PointsAccount, PointsAccount.user_id == User.id)
        if q.strip():
            query = query.where(User.username.contains(q.strip(), autoescape=True))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(User.id).offset((page - 1) * page_size).limit(page_size))
        return {'items': [{'user_id': user.id, 'username': user.username, 'role': user.role,
            'active': points.valid_user(user), 'excluded': bool(account and account.excluded),
            'can_adjust': user.id != admin.id and not user.archived_at,
            'total': account.total if account else 0} for user, account in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/admin/points/ledger')
def admin_ledger(user_id: int | None = Query(None, gt=0), page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100), kind: Literal['', 'read', 'upload', 'note', 'adjust'] = '',
                 start: date | None = None, end: date | None = None, admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        return ledger_rows(db, admin, user_id, page, page_size, kind, start, end)


@router.get('/admin/points/events')
def events(status: Literal['pending', 'failed', 'ignored', 'awarded'] = 'failed',
           page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        query = select(PointsEvent).where(PointsEvent.status == status)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(PointsEvent.occurred_at.desc(), PointsEvent.id).offset((page - 1) * page_size).limit(page_size))
        return {'items': [{'id': row.id, 'user_id': row.user_id, 'kind': row.kind, 'status': row.status,
            'reason': row.reason, 'attempts': row.attempts, 'business_day': row.business_day,
            'title': title_for(db, row.document_id, admin)} for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/admin/points/events/{event_id}/retry')
def retry_event(event_id: str, admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        event = db.get(PointsEvent, event_id)
        if not event:
            raise HTTPException(404, '积分事件不存在。')
        if event.status != 'failed':
            raise HTTPException(409, '仅失败的积分结算可以重试。')
        event.retry_at = points.now()
        db.commit()
        return {'message': '已安排重试，同一奖励不会重复发放。'}


@router.get('/admin/points/rules')
def admin_rules(admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        rows = list(db.scalars(select(PointsRule).order_by(PointsRule.id.desc()).limit(30)))
        return {'current': serialize_rule(points.current_rule(db)), 'latest_version': rows[0].id,
                'history': [serialize_rule(row) for row in rows]}


@router.put('/admin/points/rules')
def change_rules(body: RuleEdit, admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        latest = db.scalar(select(PointsRule).order_by(PointsRule.id.desc()).limit(1).with_for_update())
        if latest.id != body.expected_version:
            raise HTTPException(409, '积分规则已被其他管理员修改，请重新加载。')
        stamp = points.now()
        effective = stamp if body.immediate_pause else datetime.combine(
            date.fromisoformat(points.day(stamp)) + timedelta(days=1), time()) - timedelta(hours=8)
        db.execute(update(PointsRule).where(PointsRule.cancelled_at.is_(None),
            PointsRule.effective_at > stamp).values(cancelled_at=stamp))
        policy = body.policy.model_dump()
        if body.immediate_pause:
            policy = copy.deepcopy(points.current_rule(db).policy)
            policy['enabled'] = False
        row = PointsRule(id=latest.id + 1, effective_at=effective, policy=policy,
            actor_id=admin.id, reason=body.reason)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, '积分规则已变化，请重新加载。') from None
        return serialize_rule(row)


@router.get('/points/activity')
def activity(user=Depends(get_knowledge_current_user)):
    from company_catalog import CompanyDocument, can_read
    import company_knowledge as kb
    with SessionLocal() as db:
        points.available(db)
        policy = points.current_rule(db).policy
        started = db.scalar(select(func.min(PointsRule.effective_at)))
        query = select(CompanyDocument).where(CompanyDocument.index_id == kb.settings()['index_id'],
            CompanyDocument.created_at >= started, CompanyDocument.is_current == 1,
            CompanyDocument.state.in_(['queued', 'uploading', 'parsing', 'indexing', 'failed']),
            or_(CompanyDocument.uploaded_by_user_id == user.id,
                (CompanyDocument.owner_user_id == user.id) & (CompanyDocument.note_id != '')))
        items = []
        for doc in db.scalars(query.order_by(CompanyDocument.updated_at.desc()).limit(10)):
            if doc.note_id and (not can_read(doc, user) or doc.confidentiality != 'internal' or doc.visibility != 'members'):
                continue
            kind = 'note' if doc.note_id else 'upload'
            if not doc.note_id and doc.version != 1:
                continue
            items.append({'title': title_for(db, doc.id, user), 'kind': kind, 'status': 'waiting',
                'reason': '资料处理失败，修复后再判断奖励' if doc.state == 'failed' else '等待解析与索引完成；实际以奖励条件和当日额度为准',
                'expected': policy[kind + '_points'] if policy['enabled'] else 0})
        for event in db.scalars(select(PointsEvent).where(PointsEvent.user_id == user.id,
                PointsEvent.status.in_(['pending', 'failed', 'ignored'])).order_by(PointsEvent.created_at.desc()).limit(10)):
            items.append({'title': title_for(db, event.document_id, user), 'kind': event.kind,
                'status': event.status, 'reason': event.reason or '等待积分结算',
                'expected': event.policy[event.kind + '_points'] if event.status in ('pending', 'failed') else 0})
        return {'items': items[:15]}


@router.patch('/admin/points/users/{user_id}/participation')
def participation(user_id: int, body: Participation, admin=Depends(administrator)):
    with SessionLocal() as db:
        points.available(db)
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, '账号不存在。')
        row = points.account(db, user_id)
        row.excluded = body.excluded
        # Persist participation changes independently of expiring account audits.
        stamp = points.now()
        db.add(PointsEntry(user_id=user_id, unique_key=points.key('participation', user_id, row.revision),
            kind='adjust', amount=0, rule_id=points.current_rule(db).id, business_day=points.day(stamp),
            actor_id=admin.id, reason=('暂停参与：' if body.excluded else '恢复参与：') + body.reason))
        db.commit()
        return {'excluded': row.excluded, 'message': '参与设置已保存，历史积分保留。'}


@router.post('/admin/points/users/{user_id}/adjustments')
def adjust(user_id: int, body: Adjustment, request: Request, admin=Depends(administrator)):
    from account_security import consume_confirmation
    with SessionLocal() as db:
        points.available(db)
        if user_id == admin.id:
            raise HTTPException(403, '不能给本人调整积分，请其他管理员处理。')
        target = db.get(User, user_id)
        if not target or target.archived_at:
            raise HTTPException(404, '账号不存在或已归档。')
        row = points.account(db, user_id)
        unique = points.key('adjustment', admin.id, user_id, body.request_id)
        prior = db.scalar(select(PointsEntry).where(PointsEntry.unique_key == unique))
        if prior:
            if (prior.amount, prior.original_id, prior.reason) != (body.amount, body.original_id, body.reason):
                raise HTTPException(409, '请求编号已用于另一笔调整。')
            return {'id': prior.id, 'amount': prior.amount, 'message': '该调整已完成，未重复记账。'}
        if row.total + body.amount < 0:
            raise HTTPException(409, '撤回后积分不能小于0。')
        original = None
        if body.original_id:
            original = db.get(PointsEntry, body.original_id)
            if not original or original.user_id != user_id or original.amount <= 0 or body.amount != -original.amount:
                raise HTTPException(422, '撤回必须完整对应本账号的一笔正向奖励。')
            if db.scalar(select(PointsEntry.id).where(PointsEntry.original_id == original.id)):
                raise HTTPException(409, '该奖励已被撤回，不能重复撤回。')
        consume_confirmation(db, request, admin, 'points_adjust', user_id)
        entry = PointsEntry(user_id=user_id, unique_key=unique, kind=original.kind if original else 'adjust',
            amount=body.amount, rule_id=original.rule_id if original else points.current_rule(db).id,
            business_day=original.business_day if original else points.day(), original_id=body.original_id,
            document_id=original.document_id if original else '', actor_id=admin.id, reason=body.reason)
        db.add(entry)
        row.total += body.amount
        db.commit()
        return {'id': entry.id, 'amount': entry.amount, 'message': '积分调整已记账。'}
