"""W1 迷你知识库：内存 FAQ 片段 + 关键词检索。
以后升级 Qdrant 向量检索时，retrieve() 的接口签名保持不变。"""

CHUNKS = [
    {"id": "kb-001", "title": "退货政策",
     "content": "自签收之日起7天内可申请无理由退货，商品需保持未使用、吊牌完整。食品、定制品不支持退货。",
     "keywords": ["退货", "退款"]},
    {"id": "kb-002", "title": "运费规则",
     "content": "单笔订单满99元包邮；偏远地区（新疆、西藏等）需补运费15元。",
     "keywords": ["运费", "包邮", "邮费"]},
    {"id": "kb-003", "title": "发货时效",
     "content": "普通订单48小时内发货；预售商品以商品页标注的预售期为准。",
     "keywords": ["发货", "多久", "物流", "快递"]},
    {"id": "kb-004", "title": "维修与换货",
     "content": "电子产品15天内出现质量问题可换新；15天至1年内提供免费维修。",
     "keywords": ["维修", "换货", "坏了", "质量"]},
]


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """关键词打分检索（W1 简化版），返回按相关度排序的片段。"""
    scored = [(sum(1 for kw in c["keywords"] if kw in query), c) for c in CHUNKS]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]