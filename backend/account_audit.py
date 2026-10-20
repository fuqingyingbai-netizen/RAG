"""Readable account audit summaries; never expose arbitrary stored details."""

ACTION_LABELS = {
    "invitation_created": "创建邀请",
    "invitation_revoked": "撤销邀请",
    "invitation_used": "邀请注册",
    "invitation_expired": "清理过期邀请",
    "invitation_deleted": "删除邀请",
    "account_archived": "归档账号",
    "account_restored": "恢复归档账号",
    "account_updated": "调整账号权限",
    "account_promoted": "提升管理员",
    "account_demoted": "降为普通账号",
    "password_reset": "重置密码",
    "password_changed": "修改密码",
    "account_profile_updated": "编辑账号资料",
}


def invitation_number(entry):
    details = entry.details if isinstance(entry.details, dict) else {}
    value = entry.invitation_id or details.get("invitation_id")
    return value if type(value) is int and value > 0 else None


def audit_summary(entry):
    details = entry.details if isinstance(entry.details, dict) else {}
    invitation_id = invitation_number(entry)
    invitation = f"邀请码 #{invitation_id}" if invitation_id else "邀请码"
    role = "管理员" if details.get("role") == "admin" else "普通账号"
    if entry.action == "invitation_created":
        hours = details.get("expires_in_hours")
        duration = f"，有效期 {hours} 小时" if type(hours) is int and 1 <= hours <= 168 else ""
        return f"创建{role}{invitation}{duration}"
    if entry.action == "invitation_revoked":
        return f"撤销{invitation}"
    if entry.action == "invitation_used":
        return f"通过{invitation}注册{role}"
    if entry.action == "invitation_expired":
        previous = details.get("previous_status")
        status = {"used": "已使用", "revoked": "已撤销", "expired": "未使用"}.get(previous) if isinstance(previous, str) else None
        return f"自动清理过期{invitation}" + (f"（原状态：{status}）" if status else "")
    if entry.action == "invitation_deleted":
        status = {"used": "已使用", "revoked": "已撤销"}.get(details.get("previous_status")) if isinstance(details.get("previous_status"), str) else None
        return f"删除{role}{invitation}" + (f"（原状态：{status}）" if status else "")
    if entry.action == "account_updated":
        changes = []
        if type(details.get("is_active")) is bool:
            changes.append("账号状态：" + ("启用" if details["is_active"] else "停用"))
        if type(details.get("knowledge_access")) is bool:
            changes.append("公司知识库：" + ("授权" if details["knowledge_access"] else "撤销授权"))
        return "；".join(changes) or "更新账号权限"
    if entry.action == "account_profile_updated":
        fields = details.get("fields")
        fields = fields if isinstance(fields, list) else []
        labels = [label for field, label in [("display_name", "姓名"), ("notes", "备注")] if field in fields]
        return "修改" + "、".join(labels) if labels else "编辑账号资料"
    return {
        "account_promoted": "普通账号 → 管理员",
        "account_demoted": "管理员 → 普通账号",
        "password_reset": "重置登录密码，下次登录须修改",
        "password_changed": "修改自己的登录密码",
        "account_archived": "归档停用账号，保留历史资料",
        "account_restored": "恢复归档账号，仍保持停用，需单独启用",
    }.get(entry.action, "操作已记录")
