"""Triage 分诊 Agent：提示词构建 + 防御性 JSON 解析 + 关键词兜底。

纯函数无 IO（LLM 调用在服务层/节点层），可单测。
失败策略：解析失败 → keyword_fallback，永不阻塞对话（DESIGN §4.2）。
"""
import json
import re

SYSTEM_PROMPT = """你是电商客服系统的分诊器。只输出一个 JSON 对象，不要输出任何其他文字、解释或代码块标记。

输出格式：
{"intents": ["..."], "sentiment": 3.0, "urgency": "mid", "order_no": null, "risk_keywords": []}

字段说明：
- intents: 数组，从 ["faq", "order_query", "refund", "unknown"] 中选 1-2 个，按相关性排序
  * faq: 问政策/规则/流程（退货政策、运费、发货时效、维修换货）
  * order_query: 查订单/物流/快递状态
  * refund: 要求退款/退货/换货/补偿
- sentiment: 1.0~5.0，1=非常愤怒，3=中性，5=满意
- urgency: "low" | "mid" | "high"
- order_no: 消息中出现的订单号（如 SO-0002），没有则为 null
- risk_keywords: 消息中的施压/威胁/曝光类词汇数组（投诉、曝光、工商、法律、报警等），没有则空数组"""


def build_messages(question: str, summary: str = "", slots: dict | None = None) -> list[dict]:
    """带上滚动摘要与槽位（修复指代消解：'那这个能退吗'）。"""
    context = ""
    if summary:
        context += f"【会话摘要】{summary}\n"
    if slots:
        context += f"【已知槽位】{json.dumps(slots, ensure_ascii=False)}\n"
    context += f"【当前消息】{question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]


def parse_llm_output(text: str) -> dict | None:
    """防御性解析：剥代码块围栏、找最外层花括号、校验字段。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    valid_intents = {"faq", "order_query", "refund", "unknown"}
    intents = [i for i in data.get("intents", []) if i in valid_intents]
    if not intents:
        intents = ["unknown"]
    try:
        sentiment = max(1.0, min(5.0, float(data.get("sentiment", 3.0))))
    except (TypeError, ValueError):
        sentiment = 3.0
    urgency = data.get("urgency", "mid")
    if urgency not in ("low", "mid", "high"):
        urgency = "mid"
    order_no = data.get("order_no")
    if order_no is not None and not isinstance(order_no, str):
        order_no = None
    keywords = [k for k in data.get("risk_keywords", []) if isinstance(k, str)][:5]
    return {"intents": intents, "sentiment": round(sentiment, 1), "urgency": urgency,
            "order_no": order_no, "risk_keywords": keywords}


# ---------- 关键词兜底（LLM 不可用时对话不中断） ----------

_KB_WORDS = ["退货", "退款", "运费", "包邮", "邮费", "发货", "多久", "物流", "快递", "维修", "换货", "政策"]
_ORDER_WORDS = ["订单", "物流", "快递", "到哪", "什么时候到", "发货", "单号"]
_REFUND_WORDS = ["退款", "退货", "换货", "退钱", "换一个", "维修", "补偿"]
_ORDER_NO_RE = re.compile(r"SO-\d{3,}", re.IGNORECASE)


def keyword_fallback(question: str) -> dict:
    q = question or ""
    order_no = _ORDER_NO_RE.search(q)
    intents = []
    if any(w in q for w in _REFUND_WORDS):
        intents.append("refund")
    if any(w in q for w in _ORDER_WORDS):
        intents.append("order_query")
    if any(w in q for w in _KB_WORDS):
        intents.append("faq")
    if not intents:
        intents = ["unknown"]
    return {"intents": intents, "sentiment": 3.0, "urgency": "mid",
            "order_no": order_no.group(0).upper() if order_no else None, "risk_keywords": []}


def pick_primary(intents: list[str]) -> str:
    """多意图时按业务优先级取主意图：退款(资金) > 查单 > FAQ。"""
    for i in ("refund", "order_query", "faq"):
        if i in intents:
            return i
    return "unknown"
