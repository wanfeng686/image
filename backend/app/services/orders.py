"""订单服务：只读查询 + 归属断言（防 IDOR，DESIGN S3）。

铁律：任何查询都强制带 user_id 过滤——Agent 层根本无法指定"查别人的订单"。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MockOrder, MockProduct, MockShipment

STATUS_CN = {
    "paid": "已支付待发货",
    "shipped": "已发货",
    "delivered": "已签收",
    "refunding": "退款处理中",
    "refunded": "已退款",
}


def get_order(db: Session, user_id, order_no: str | None = None) -> MockOrder | None:
    """归属断言查询。无单号时返回该用户最近一单。"""
    q = select(MockOrder).where(MockOrder.user_id == user_id)
    if order_no:
        q = q.where(MockOrder.order_no == order_no)
    else:
        q = q.order_by(MockOrder.paid_at.desc().nullslast()).limit(1)
    return db.scalar(q)


def order_card(db: Session, order: MockOrder) -> dict:
    """订单卡片结构化数据（数据走卡片渲染，减少幻觉面）。"""
    product = db.get(MockProduct, order.product_id)
    shipment = db.scalar(select(MockShipment).where(MockShipment.order_id == order.id))
    return {
        "type": "order",
        "order_no": order.order_no,
        "product": product.name if product else "未知商品",
        "amount": float(order.amount),
        "status": order.status,
        "status_cn": STATUS_CN.get(order.status, order.status),
        "carrier": shipment.carrier if shipment else None,
        "tracking_no": shipment.tracking_no if shipment else None,
        "eta": str(shipment.estimated_delivery) if shipment and shipment.estimated_delivery else None,
    }


def order_text(card: dict) -> str:
    """卡片配套的一句话摘要（纯模板拼接，不经过 LLM）。"""
    text = (f"为您查询到订单 {card['order_no']}：{card['product']}，"
            f"金额 ¥{card['amount']:.2f}，当前状态：{card['status_cn']}。")
    if card.get("carrier"):
        text += f" 物流：{card['carrier']} {card['tracking_no']}"
        if card.get("eta"):
            text += f"，预计 {card['eta']} 送达。"
    else:
        text += " 尚无物流信息。"
    return text
