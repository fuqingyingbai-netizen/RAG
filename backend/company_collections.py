"""Disjoint research and experience collections, including stored chat scopes."""
EXPERIENCE_CATEGORIES = frozenset(('项目经验', '案例复盘', '方法与模板', '培训分享', '现场照片', '手稿笔记', '影音随记'))
KNOWLEDGE_SCOPES = ('accessible', 'my-projects', 'experience', 'my-experience')


def collection_of_scope(scope):
    if scope not in KNOWLEDGE_SCOPES:
        raise ValueError('Unknown knowledge scope')
    return 'experience' if scope in ('experience', 'my-experience') else 'library'


def collection_of(document):
    return 'experience' if document.category in EXPERIENCE_CATEGORIES else 'library'


def in_scope(document, scope):
    return collection_of(document) == collection_of_scope(scope)


def personal_scope(scope):
    return 'my-experience' if collection_of_scope(scope) == 'experience' else 'my-projects'


def is_personal(scope):
    return scope in ('my-projects', 'my-experience')
