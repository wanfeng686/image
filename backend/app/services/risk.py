"""风险评分服务：多维打分 + 分级路由。

铁律（DESIGN §4.2 处置 Agent）：评分与阈值比较在编排层代码里做，不信任 LLM 自评。
阈值全部来自 risk_rules 表，运营台可改。
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MockOrder, RiskRule, User


def load_rules(db: Session) -> dict:
    return {r.rule_key: r.value for r in db.scalars(select(RiskRule))}


def score_refund(db: Session, user: User, order: MockOrder,
                 sentiment: float | None) -> tuple[float, dict, str, int]:
    """返回 (总分, 分维度明细, 等级, 需要审批人数)。

    维度：amount × 频次聚合(30天累计退款) × 用户画像 × 情绪。
    分级：low→自动执行 / medium→1 人审批 / high→双签（2 人）。
    拆单旁路防御（S2）：聚合投影超限直接 high。
    """
    rules = load_rules(db)
    auto_limit = float(rules.get("auto_approve_limit", {}).get("amount", 50))
    queue_limit = float(rules.get("queue_approve_limit", {}).get("amount", 500))
    agg_limit = float(rules.get("aggregate_30d_limit", {}).get("amount", 600))
    w = rules.get("risk_weights", {"amount": 0.4, "freq": 0.3, "profile": 0.2, "sentiment": 0.1})

    amount = float(order.amount)
    refunded_30d = float(user.total_refund_30d or 0)
    projected = refunded_30d + amount  # 聚合投影：这笔批下去后 30 天累计到多少

    # 各维度子分 0~100
    sub_amount = min(100.0, amount / queue_limit * 100) if queue_limit else 100.0
    sub_freq = min(100.0, refunded_30d / agg_limit * 100) if agg_limit else 100.0
    if user.user_tier == "blacklist":
        sub_profile = 100.0
    elif (user.risk_flags or {}).get("wool_party"):
        sub_profile = 60.0
    elif user.user_tier == "vip":
        sub_profile = 0.0
    else:
        sub_profile = 10.0
    sub_sentiment = max(0.0, (4.0 - float(sentiment or 3.0)) * 25)

    breakdown = {
        "amount": round(sub_amount * float(w.get("amount", 0.4))),
        "freq": round(sub_freq * float(w.get("freq", 0.3))),
        "profile": round(sub_profile * float(w.get("profile", 0.2))),
        "sentiment": round(sub_sentiment * float(w.get("sentiment", 0.1))),
    }
    score = round(sum(breakdown.values()), 2)

    # 分级路由（确定性代码）
    if user.user_tier == "blacklist" or projected > agg_limit or amount > queue_limit:
        level, required = "high", 2       # 双签
    elif amount <= auto_limit and sub_profile < 50:
        level, required = "low", 0        # 自动执行
    else:
        level, required = "medium", 1     # 排队等 1 人批

    # Decimal 化以兼容数据库 Numeric 列
    return score, breakdown, level, required


def refund_text(level: str, card: dict, score: float, timeout_hours: float) -> str:
    """分级话术模板（不经 LLM，保证资金类回复确定性）。"""
    if level == "low":
        return (f"经评估，本笔退款 ¥{card['amount']:.2f} 风险较低，已自动通过，"
                f"款项将在 1-7 个工作日原路退回，请注意查收。")
    if level == "high":
        return (f"本笔退款 ¥{card['amount']:.2f} 金额较大或风险较高（风险分 {score}），"
                f"需要两位审批人双重确认后执行，预计 {timeout_hours:.0f} 小时内给出结果，"
                f"处理进展会第一时间同步您。")
    return (f"退款申请已提交人工审核（风险分 {score}），预计 {timeout_hours:.0f} 小时内处理完毕，"
            f"结果将第一时间通知您。")
