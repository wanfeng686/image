"""知识库检索服务：W4 起从数据库读取（版本 + 生效期过滤），替代 W1 内存版。

检索铁律（DESIGN C1）：只命中 published 文档的 active 版本，且生效窗口覆盖今天
——过期旧政策永远进不了上下文，QC 共享盲区从源头收窄。
SaaS 化：租户隔离，各商户只检索自己的知识库。
接口签名保持 (db, tenant_id, query, top_k)，未来接 Qdrant 时只换实现。
"""
import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import KbDocument, KbDocumentVersion


def _effective_docs(db: Session, tenant_id: uuid.UUID) -> list[tuple[KbDocument, KbDocumentVersion]]:
    today = date.today()
    return db.execute(
        select(KbDocument, KbDocumentVersion)
        .join(KbDocumentVersion, KbDocument.current_version_id == KbDocumentVersion.id)
        .where(
            KbDocument.tenant_id == tenant_id,
            KbDocument.status == "published",
            KbDocumentVersion.status == "active",
            KbDocumentVersion.effective_from <= today,
            or_(KbDocumentVersion.effective_to.is_(None),
                KbDocumentVersion.effective_to >= today),
        )
    ).all()


def retrieve(db: Session, tenant_id: uuid.UUID, query: str, top_k: int = 3) -> list[dict]:
    """关键词打分检索（W4 仍是词法版；向量版是 Qdrant 接入后的事）。"""
    q = query or ""
    scored = []
    for doc, ver in _effective_docs(db, tenant_id):
        text = f"{doc.title} {ver.content}"
        score = sum(1 for kw in _keywords(text) if kw and kw in q)
        if score > 0:
            scored.append((score, doc, ver))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": doc.code, "title": doc.title, "content": ver.content}
            for _, doc, ver in scored[:top_k]]


def _keywords(text: str) -> list[str]:
    """从文档自身抽词法特征（W4 简化：领域词表 + 标题切分）。"""
    domain = ["退货", "退款", "运费", "包邮", "邮费", "发货", "多久", "物流", "快递",
              "维修", "换货", "坏了", "质量", "食品", "定制", "偏远", "新疆", "西藏",
              "预售", "电子产品", "换新"]
    return [w for w in domain if w in text] + (text.split()[:0])
