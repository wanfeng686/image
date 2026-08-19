"""RPA 适配器：Playwright 控制浏览器登录商家后台收发消息。

目标切换（settings.channel_rpa_target）：
- simulator（默认）：连本地内置「多多客服工作台」模拟页（static/simulator/），全链路可演示可测试
- real：连真实拼多多商家后台。选择器见 selectors.py —— 真实页面结构未联调验证，
  拿到商家账号后按 PDD_REAL 逐项核对（TODO 标注），逻辑与 simulator 完全同构

凭据仅在内存解密；浏览器 profile 按连接持久化（backend/rpa_profiles/<conn_id>/），
避免每次轮询重复登录。
"""
import time
from urllib.parse import quote

from app.core.config import settings
from app.services.channels.base import ChannelAdapter, InboundMessage, OutboundReply
from app.services.channels.rpa.selectors import SIM, TARGET_URL

POLL_WAIT_MS = 400


class RpaAdapter(ChannelAdapter):
    def __init__(self, conn, creds: dict):
        self.conn = conn
        self.creds = creds
        self.platform = conn.platform
        self.mode = "rpa"
        self._pw = None
        self._context = None
        self.page = None
        self._seen: set[str] = set()   # 已处理的买家消息 data-id

    # ── 生命周期 ──
    def attach(self, pw, profile_dir: str, headless: bool = True):
        """由 worker 注入 playwright 实例并完成登录。"""
        self._pw = pw
        self._context = pw.chromium.launch_persistent_context(
            profile_dir, headless=headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._login()

    def close(self):
        try:
            if self._context:
                self._context.close()
        finally:
            self._context = None
            self.page = None

    def _login(self):
        url = TARGET_URL(self.platform)
        self.page.goto(url, wait_until="domcontentloaded")
        sel = SIM["login"]
        self.page.fill(sel["username"], self.creds.get("username", ""))
        self.page.fill(sel["password"], self.creds.get("password", ""))
        self.page.click(sel["submit"])
        self.page.wait_for_selector(SIM["workbench"], timeout=8000)

    # ── ChannelAdapter 接口 ──
    def test(self) -> dict:
        if self.page is None:
            return {"ok": False, "detail": "浏览器未启动"}
        try:
            visible = self.page.is_visible(SIM["workbench"])
        except Exception:  # noqa: BLE001 —— 页面可能已关闭
            return {"ok": False, "detail": "浏览器会话已失效"}
        return {"ok": visible, "detail": "登录态有效" if visible else "登录态丢失"}

    def fetch_new_messages(self) -> list[InboundMessage]:
        """读会话列表 → 打开有未读的会话 → 收集未见过的买家消息。"""
        out: list[InboundMessage] = []
        items = self.page.eval_on_selector_all(
            SIM["conv_item"],
            """els => els.map(e => ({
                conv: e.dataset.convId, buyer: e.dataset.buyerId,
                unread: e.querySelector('.conv-unread') ? e.querySelector('.conv-unread').textContent : ''
            }))""")
        for it in items:
            if not it.get("conv") or not it.get("buyer"):
                continue
            conv, buyer = it["conv"], it["buyer"]
            # 已读会话也要扫一遍新消息（模拟页不总是亮未读角标）
            self._open_conv(conv)
            msgs = self.page.eval_on_selector_all(
                SIM["buyer_msg"],
                """els => els.map(e => ({
                    id: e.dataset.id,
                    text: (e.querySelector('.msg-text') || {}).textContent || ''
                }))""")
            for m in msgs:
                mid = m.get("id") or ""
                text = (m.get("text") or "").strip()
                if not mid or mid in self._seen or not text:
                    continue
                if m["text"].startswith("会话开始"):   # 系统占位
                    continue
                self._seen.add(mid)
                out.append(InboundMessage(platform=self.platform, conversation_ref=conv,
                                          buyer_id=buyer, text=text,
                                          ts=int(time.time())))
        return out

    def send_reply(self, reply: OutboundReply) -> dict:
        self._open_conv(reply.conversation_ref)
        self.page.fill(SIM["reply_input"], reply.text)
        self.page.click(SIM["send_btn"])
        return {"sent": True}

    # ── 内部 ──
    def _open_conv(self, conv_id: str):
        head = (self.page.text_content(SIM["chat_head"]) or "")
        if conv_id in head and self.page.query_selector(SIM["reply_input"]):
            return
        self.page.click(f'{SIM["conv_item"]}[data-conv-id="{quote(conv_id)}"]')
        self.page.wait_for_timeout(POLL_WAIT_MS)
