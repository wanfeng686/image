"""拼多多官方 API 适配器 + 适配器注册表。

注册表按 (platform, mode) 分发；本轮拼多多官方 API 完整实现，
RPA 适配器在 services/channels/rpa/（由 worker 使用），其余平台待接入。
"""
from sqlalchemy.orm import Session

from app.models import ChannelConnection
from app.services import crypto
from app.services.channels.base import ChannelAdapter, InboundMessage, OutboundReply
from app.services.channels.official import pinduoduo as pdd


class PddApiAdapter(ChannelAdapter):
    platform = "pinduoduo"
    mode = "official_api"

    def __init__(self, creds: dict):
        self.creds = creds

    def test(self) -> dict:
        return pdd.test_credentials(self.creds)

    def fetch_new_messages(self) -> list[InboundMessage]:
        body = pdd.fetch_new_messages(self.creds)
        if "error_response" in body:
            raise RuntimeError(f"pdd 拉取失败：{body['error_response']}")
        # 联调期按真实响应结构核对字段映射
        sessions = (body.get("im_session_list_get_response", {})
                    .get("data_list", []))
        out = []
        for s in sessions:
            out.append(InboundMessage(
                platform=self.platform,
                conversation_ref=str(s.get("conversation_id", "")),
                buyer_id=str(s.get("user_id", s.get("buyer_id", ""))),
                buyer_name=s.get("user_name"),
                text=s.get("last_message_content", ""),
                ts=s.get("last_message_time"),
            ))
        return [m for m in out if m.text and m.conversation_ref and m.buyer_id]

    def send_reply(self, reply: OutboundReply) -> dict:
        return pdd.send_reply(self.creds, reply.conversation_ref, reply.text)


def get_adapter(db: Session, conn: ChannelConnection) -> ChannelAdapter:
    """按连接构造适配器（凭据仅在内存中解密）。"""
    creds = crypto.unseal(conn.credentials_cipher)
    if conn.platform == "pinduoduo" and conn.mode == "official_api":
        return PddApiAdapter(creds)
    if conn.mode == "rpa":
        from app.services.channels.rpa.adapter import RpaAdapter
        return RpaAdapter(conn, creds)
    raise NotImplementedError(f"{conn.platform}/{conn.mode} 适配器待接入")
