"""Persist completed generation stages without treating a checkpoint as a report.

The object-store journal contains genuine native packages. Every resumed package
still passes its own current input, literal, routing and semantic validators.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

VERSION = 'company-generation-checkpoint-v1'
PACKAGES = {'company_corpus_analysis_cache': 'company_source_review_package',
            'company_event_review_cache': 'company_event_review_package',
            'company_information_usage_cache': 'company_information_usage_package',
            'company_presentation_cache': 'company_presentation_package',
            'company_main_focus_cache': 'company_main_focus_package',
            'company_editorial_cache': 'company_editorial_package'}


def source_fingerprint(sources):
    digest = hashlib.sha256()
    for source in sorted(sources, key=lambda item: (str(getattr(item, 'id', '')), str(getattr(item, 'url', '')))):
        record = {key: getattr(source, key, None) for key in
                  ('id', 'url', 'title', 'content', 'summary', 'source_type', 'source_metadata', 'credibility_score')}
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def scope(project):
    from .company_corpus import research_context
    return {'as_of_date': str((getattr(project, 'company_research_intake', {}) or {}).get('as_of_date') or ''),
            **research_context(project)}


def prefix(project):
    pid = getattr(project, 'id', None)
    return f'projects/{pid}/company_generation_checkpoint' if type(pid) is int and pid > 0 else ''


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def save_generation_checkpoint(project, *, store=None, report_version=''):
    """Called only after a phase returns its entire result, including failures."""
    folder = prefix(project)
    if store is None or not folder:
        return None
    packages = {}
    for key, name in PACKAGES.items():
        value = getattr(project, name, None) or getattr(project, key, None)
        if isinstance(value, dict) and value.get('version'):
            packages[key] = value
    if not packages:
        return None
    payload = {'version': VERSION, 'project_id': project.id, 'target_name': str(project.target_name),
        'scope': scope(project), 'source_fingerprint': source_fingerprint(project.sources),
        'source_report_version': report_version, 'packages': packages}
    text = encode(payload)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if getattr(project, '_company_checkpoint_sha256', '') == digest:
        return None
    key = folder + '/' + digest + '.json'
    # Write the immutable package first. A crash during a local write cannot
    # publish a partial package as the latest resumable state.
    store.put_text(key, text, 'application/json; charset=utf-8')
    pointer = {'version': VERSION, 'key': key, 'sha256': digest,
               'saved_at': datetime.now(timezone.utc).isoformat()}
    store.put_text(folder + '/current.json', encode(pointer), 'application/json; charset=utf-8')
    project._company_checkpoint_sha256 = digest
    return pointer


def read_generation_checkpoint(project, *, store):
    folder = prefix(project)
    if not folder:
        return {}
    try:
        pointer = json.loads(store.get_text(folder + '/current.json'))
    except FileNotFoundError:
        return _merge_editorial_journal(project,store,{})
    except Exception as exc:
        if getattr(exc, 'code', '') in {'NoSuchKey', 'NoSuchObject', 'NoSuchBucket'}:
            return _merge_editorial_journal(project,store,{})
        raise
    if not isinstance(pointer, dict):
        raise ValueError('invalid_company_checkpoint_pointer')
    digest = pointer.get('sha256', '')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('invalid_company_checkpoint_pointer')
    key = folder + '/' + digest + '.json'
    if pointer.get('version') != VERSION or len(digest) != 64 or pointer.get('key') != key:
        raise ValueError('invalid_company_checkpoint_pointer')
    text = store.get_text(key)
    if hashlib.sha256(text.encode()).hexdigest() != digest:
        raise ValueError('company_checkpoint_hash_mismatch')
    payload = json.loads(text)
    if (payload.get('version') != VERSION or payload.get('project_id') != project.id
            or payload.get('target_name') != str(project.target_name)
            or payload.get('scope') != scope(project)
            or payload.get('source_fingerprint') != source_fingerprint(project.sources)):
        return {}
    packages = payload.get('packages')
    if not isinstance(packages, dict):
        raise ValueError('invalid_company_checkpoint_packages')
    caches = {name: packages[name] for name in PACKAGES if isinstance(packages.get(name), dict)}
    usage = caches.get('company_information_usage_cache')
    if usage and not usage.get('review_scope'):
        from .company_information_usage import bind_legacy_routing_scope
        caches['company_information_usage_cache'] = bind_legacy_routing_scope(
            usage, str(project.target_name), scope(project), caches.get('company_corpus_analysis_cache', {}),
            payload.get('source_report_version', ''))
    return _merge_editorial_journal(project,store,caches)


def _merge_editorial_journal(project,store,caches):
    journal=read_editorial_journal(project,store=store)
    if journal:
        prior=caches.get('company_editorial_cache') or {}
        from .company_editorial import VERSION as EDITORIAL_VERSION
        if prior.get('version')!=EDITORIAL_VERSION:prior={}
        batches={b.get('input_sha256'):b for b in prior.get('batches',[]) if isinstance(b,dict) and b.get('accepted')}
        batches.update({b['input_sha256']:b for b in journal})
        caches['company_editorial_cache']={'version':EDITORIAL_VERSION,'target_name':str(project.target_name),
            'batches':list(batches.values())}
    from .company_presentation import read_journal,VERSION as PRESENTATION_VERSION,presentation_scope
    presentation=read_journal(project,store)
    if presentation:
        prior=caches.get('company_presentation_cache') or {}
        batches={b.get('input_sha256'):b for b in prior.get('batches',[]) if isinstance(b,dict) and b.get('accepted')}
        batches.update({b['input_sha256']:b for b in presentation})
        caches['company_presentation_cache']={'version':PRESENTATION_VERSION,'target_name':str(project.target_name),
            'scope':presentation_scope(project),'batches':list(batches.values())}
    from .company_main_focus import read_journal as read_focus,VERSION as FOCUS_VERSION
    focused=read_focus(project,store)
    if focused:
        prior=caches.get('company_main_focus_cache') or {}
        batches={b.get('input_sha256'):b for b in prior.get('batches',[]) if isinstance(b,dict) and b.get('accepted')}
        batches.update({b['input_sha256']:b for b in focused})
        caches['company_main_focus_cache']={'version':FOCUS_VERSION,'target_name':str(project.target_name),
            'scope':presentation_scope(project),'batches':list(batches.values())}
    return caches


def _editorial_binding(project):
    from .company_editorial import VERSION as EDITORIAL_VERSION
    return {'version':VERSION,'editorial_version':EDITORIAL_VERSION,'project_id':project.id,
            'target_name':str(project.target_name),'scope':scope(project),
            'source_fingerprint':source_fingerprint(project.sources)}


def _editorial_index(project,store,binding):
    try:
        index=json.loads(store.get_text(prefix(project)+'/editorial-current.json'))
    except (FileNotFoundError,ValueError,TypeError):
        return {**binding,'entries':{}}
    except Exception as exc:
        if getattr(exc,'code','') in {'NoSuchKey','NoSuchObject','NoSuchBucket'}:
            return {**binding,'entries':{}}
        raise
    if not isinstance(index,dict) or any(index.get(k)!=v for k,v in binding.items()) or not isinstance(index.get('entries'),dict):
        return {**binding,'entries':{}}
    return index


def read_editorial_journal(project, *, store):
    """Return candidates; the writer still reruns proposal/audit validation."""
    folder=prefix(project)
    if not folder:return []
    try:index=_editorial_index(project,store,_editorial_binding(project))
    except Exception:return []
    batches=[]
    for input_hash,digest in index['entries'].items():
        if not all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in (input_hash,digest)):continue
        try:
            text=store.get_text(folder+'/editorial/'+digest+'.json')
            if hashlib.sha256(text.encode()).hexdigest()!=digest:continue
            batch=json.loads(text)
            if isinstance(batch,dict) and batch.get('input_sha256')==input_hash and batch.get('accepted') is True:
                batches.append(batch)
        except Exception:
            continue
    return batches


def checkpoint_editorial_batch(project,batch,emit,trace_emit=None):
    """Journal each finished accepted batch, without publishing a partial report."""
    store=getattr(project,'company_generation_checkpoint_store',None)
    if store is None or not prefix(project) or batch.get('accepted') is not True:return
    input_hash=batch.get('input_sha256','')
    if not isinstance(input_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',input_hash):return
    try:
        index=getattr(project,'_company_editorial_journal_index',None)
        if index is None:
            index=_editorial_index(project,store,_editorial_binding(project))
            project._company_editorial_journal_index=index
        text=encode({k:v for k,v in batch.items() if k!='reused'})
        digest=hashlib.sha256(text.encode()).hexdigest()
        if index['entries'].get(input_hash)==digest:return
        store.put_text(prefix(project)+'/editorial/'+digest+'.json',text,'application/json; charset=utf-8')
        updated={**index,'entries':{**index['entries'],input_hash:digest}}
        store.put_text(prefix(project)+'/editorial-current.json',encode(updated),'application/json; charset=utf-8')
        project._company_editorial_journal_index=updated
    except Exception as exc:
        emit(trace_emit,'report','company_checkpoint','已通过批次的恢复回执保存失败',
             type(exc).__name__+'；本轮审稿结果保留，不把未保存回执当作可恢复缓存。',status='warning')


def checkpoint_generation_stage(project, emit, trace_emit=None):
    store = getattr(project, 'company_generation_checkpoint_store', None)
    if store is None:
        return
    try:
        pointer = save_generation_checkpoint(project, store=store,
            report_version=getattr(project, 'company_generation_checkpoint_report_version', ''))
        if pointer:
            emit(trace_emit, 'report', 'company_checkpoint', '已保存可恢复的生成检查点',
                 '只保存真实阶段结果；恢复时重新校验原文、主体、研究范围及各项质量回执。', status='done')
    except Exception as exc:
        emit(trace_emit, 'report', 'company_checkpoint', '生成检查点保存失败',
             type(exc).__name__ + '；继续本轮生成，不将未保存状态当作可恢复结果。', status='warning')
