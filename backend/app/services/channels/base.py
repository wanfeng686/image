"""渠道适配器抽象：所有平台接入（官方 API / RPA）实现同一接口。

worker / bridge 只面向 InboundMessage 与 OutboundReply，不关心平台细节：
- 官方 API 适配器：HTTP 调平台开放接口收发消息（见 official/）
- RPA 适配器：Playwright 控制浏览器读写商家后台（见 rpa/）
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    platform: str                 # pinduoduo | taobao | ...
    conversation_ref: str         # 平台侧会话标识（external_ref 映射用）
    buyer_id: str                 # 买家 ID（绑定 User.external_id，按平台加前缀防串号）
    buyer_name: str | None = None
    text: str = ""
    ts: int | None = None         # epoch 秒（去重）


@dataclass
class OutboundReply:
    conversation_ref: str
    text: str
    card: dict | None = None
    session_id: str | None = None


class ChannelAdapter(ABC):
    """一个连接对应一个适配器实例（持有解密后的凭据，仅存在于内存）。"""

    platform: str = ""
    mode: str = ""

    @abstractmethod
    def test(self) -> dict:
        """连接测试：{ok, detail, shop_name?}。"""

    @abstractmethod
    def fetch_new_messages(self) -> list[InboundMessage]:
        """拉取新消息（worker 轮询调用）。"""

    @abstractmethod
    def send_reply(self, reply: OutboundReply) -> dict:
        """把回复发回平台会话。"""
