"""新租户默认配置：注册即拷贝一套安全的风控/升级规则，退款三路开箱可用。
（知识库不拷贝——内容必须商户自己的；模型绑定不拷贝——走平台默认。）"""

DEFAULT_RISK_RULES = [
    {"rule_key": "auto_approve_limit", "value": {"amount": 50}},          # 小额自动
    {"rule_key": "queue_approve_limit", "value": {"amount": 500}},        # 中额排队，超过则双签
    {"rule_key": "risk_weights", "value": {"amount": 0.4, "freq": 0.3, "profile": 0.2, "sentiment": 0.1}},
    {"rule_key": "freq_aggregate_window_hours", "value": {"hours": 72}},
    {"rule_key": "approval_timeout_hours", "value": {"hours": 4}},
    {"rule_key": "aggregate_30d_limit", "value": {"amount": 600}},        # 30天累计退款旁路上限
]

DEFAULT_ESCALATION_RULES = [
    {"rule_type": "keyword", "name": "法律与曝光风险词", "priority": 10,
     "config": {"keywords": ["投诉", "曝光", "工商", "法律", "律师", "报警", "媒体", "12315"]}},
    {"rule_type": "keyword", "name": "显式转人工请求", "priority": 20,
     "config": {"keywords": ["转人工", "人工客服", "真人"]}},
    {"rule_type": "condition", "name": "VIP用户直达", "priority": 30,
     "config": {"user_tier": "vip"}},
    {"rule_type": "condition", "name": "情绪阈值", "priority": 40,
     "config": {"sentiment_below": 2.0}},
]


def ensure_default_rules(db, tenant) -> None:
    """给新租户落默认规则（幂等：已有的 key 跳过）。"""
    from sqlalchemy import select

    from app.models import EscalationRule, RiskRule

    for r in DEFAULT_RISK_RULES:
        if db.scalar(select(RiskRule).where(
                RiskRule.tenant_id == tenant.id, RiskRule.rule_key == r["rule_key"])) is None:
            db.add(RiskRule(tenant_id=tenant.id, **r))
    for r in DEFAULT_ESCALATION_RULES:
        if db.scalar(select(EscalationRule).where(
                EscalationRule.tenant_id == tenant.id,
                EscalationRule.name == r["name"])) is None:
            db.add(EscalationRule(tenant_id=tenant.id, **r))
