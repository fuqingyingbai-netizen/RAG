"""Read-only help location: resolve permitted metadata, never document contents."""
import json
from pathlib import Path
import re


def loaded_release():
    try:
        manifest = json.loads((Path(__file__).resolve().parents[1] / 'release-manifest.json').read_text())
        commit = manifest.get('commit', '')
        return commit[:12] if re.fullmatch('[a-f0-9]{40}', commit) else ''
    except (OSError, ValueError, TypeError):
        return ''


LOADED_RELEASE = loaded_release()


def resolve_location(db, user, request):
    """No project locks, cloud calls, edits, document text or private draft text."""
    ctx = request.knowledge_context
    if request.current_page != 'company-knowledge' or ctx is None:
        return {}
    import company_knowledge as kb
    from company_catalog import CompanyProject, CompanyFolder, can_read, can_manage
    from company_collections import EXPERIENCE_CATEGORIES
    result = {'mode': ctx.mode, 'dialog': ctx.dialog, 'collection': ctx.collection}
    if not kb.has_access(user):
        return result | {'unavailable': True}
    try:
        index_id = kb.settings()['index_id']
    except kb.KnowledgeError:
        return result | {'unavailable': True}
    project_id, folder_id = ctx.project_id, ctx.folder_id
    if ctx.dialog == 'capture':
        # Quick capture intentionally uses an inbox, even inside another project.
        return result | {'capture': True}
    if ctx.note_id:
        from company_notes import CompanyNote, editable
        note = db.get(CompanyNote, ctx.note_id)
        if not note or note.index_id != index_id or not editable(note, user):
            return result | {'unavailable': True}
        project_id, folder_id = note.project_id, note.folder_id
    if not project_id:
        return result
    project = db.get(CompanyProject, project_id)
    if not project or project.index_id != index_id or not can_read(project, user):
        return result | {'unavailable': True}
    names, seen = [], set()
    while folder_id:
        if folder_id in seen or len(seen) >= 64:
            return result | {'unavailable': True}
        seen.add(folder_id)
        folder = db.get(CompanyFolder, folder_id)
        if not folder or folder.project_id != project.id:
            return result | {'unavailable': True}
        names.insert(0, folder.name)
        folder_id = folder.parent_id
    return result | {'path': [project.name, *names], 'can_manage': can_manage(project, user),
                     'experience': project.category in EXPERIENCE_CATEGORIES}


def location_text(location):
    if not location:
        return ''
    if location.get('unavailable'):
        return '当前目录或笔记未能通过访问权限核验，请回到项目确认权限；不能确认保存位置。'
    if location.get('capture'):
        return '当前打开的是「随手记录」：会归入你自己的「随手记录 · 待整理」项目，不会跟随当前浏览目录。'
    path = location.get('path')
    if not path:
        return '当前没有进入具体项目目录；新建图文笔记会归入你自己的「随手记录 · 待整理」。上传文件请先创建或打开项目。'
    label = json.dumps(' / '.join(path), ensure_ascii=False)
    where = '项目根目录' if len(path) == 1 else '子目录'
    text = f'当前目录：{label}（{where}）。'
    if location.get('dialog') == 'note':
        return text + ' 这篇图文笔记的实际归档位置已按后端记录核对；保存只更新草稿，发布并完成索引后才能用于问答。'
    if not location.get('can_manage'):
        return text + ' 当前账号不能在此修改项目、创建目录或上传；新建图文笔记会转入自己的「随手记录 · 待整理」。'
    text += ' 「上传文件」保存在这里；'
    if location.get('experience'):
        text += '「新建图文笔记」也保存在这里。'
    else:
        text += '图文笔记仅在经验沉淀中创建，不能创建到资料库项目。'
    return text + ' 「随手记录」则固定归入自己的「随手记录 · 待整理」。'
