"""Catalogue attribution only; department labels never grant access."""
from typing import Literal

from fastapi import HTTPException

Department = Literal['', 'market', 'project', 'policy', 'expert']
DEPARTMENTS = {'market': '市场部', 'project': '项目部', 'policy': '制度文件', 'expert': '专家资料'}


def validate_department(value):
    if value not in ('', *DEPARTMENTS):
        raise HTTPException(422, '请选择有效的所属部门／栏目。')
    return value


def department_label(value):
    return DEPARTMENTS.get(value, '待归类')
