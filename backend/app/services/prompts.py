"""提示词模板系统（BYOK 配套）：平台提供默认模板，商户可按槽位覆盖。

- 槽位注册表 SLOTS：目前仅开放 knowledge_system（客服人设——唯一生成
  顾客可见文案的 LLM 提示词）；triage/qc/insight 等内部提示词控制着
  JSON 解析与路由，不开放编辑。
- 存储：tenant.prompts JSONB（{slot: 覆盖文本}），空 = 全默认。
- 运行时：effective() 返回覆盖 > 默认；注入点为 knowledge_agent.build_messages。
"""
from sqlalchemy.orm import Session

from app.agent import knowledge as knowledge_agent
from app.models import Tenant

SLOTS: dict[str, dict] = {
    "knowledge_system": {
        "title": "客服人设与回答规则",
        "desc": "AI 回复买家时使用的系统提示词：语气、人设、引用与拒答规则。"
                "建议保留 [kb-xxx] 引用与「知识片段不足只转人工」的约束，否则回答质量可能下降。",
        "default": knowledge_agent.SYSTEM_PROMPT,
        "max_len": 4000,
    },
}

AGENTS = ("triage", "knowledge", "qc", "resolution", "insight")  # 绑定覆盖的 agent 全集


def default(slot: str) -> str:
    return SLOTS[slot]["default"]


def effective(db: Session, tenant_id, slot: str) -> str:
    """租户覆盖 > 平台默认模板。库异常时静默回退默认（提示词永不阻断对话）。"""
    if slot not in SLOTS:
        raise KeyError(slot)
    try:
        tenant = db.get(Tenant, tenant_id)
        override = (tenant.prompts or {}).get(slot) if tenant else None
        return override if isinstance(override, str) and override.strip() else default(slot)
    except Exception:  # noqa: BLE001
        return default(slot)


def set_override(db: Session, tenant: Tenant, slot: str, text: str | None) -> None:
    """写入/清除覆盖（None 或空白 = 回默认）。调用方负责 commit。"""
    if slot not in SLOTS:
        raise KeyError(slot)
    prompts = dict(tenant.prompts or {})
    if text is None or not text.strip():
        prompts.pop(slot, None)
    else:
        max_len = SLOTS[slot]["max_len"]
        if len(text) > max_len:
            raise ValueError(f"模板超过 {max_len} 字")
        prompts[slot] = text
    tenant.prompts = prompts
