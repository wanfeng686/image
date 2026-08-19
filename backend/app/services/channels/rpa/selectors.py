"""RPA 目标页面选择器。

SIM：内置模拟后台（static/simulator/index.html）——稳定可用，测试/演示基线。
PDD_REAL：真实拼多多商家后台（mms.pinduoduo.com）骨架——未经真实联调，
拿到商家账号后逐项核对（TODO）。逻辑同构：核对选择器即可切换真实环境。
"""
from app.core.config import settings

SIM = {
    "login": {"username": "#username", "password": "#password", "submit": "#loginBtn"},
    "workbench": "#workView",
    "conv_item": ".conv-item",
    "buyer_msg": '.msg[data-sender="buyer"]',
    "reply_input": "#replyInput",
    "send_btn": "#sendBtn",
    "chat_head": "#chatHead",
}

PDD_REAL = {
    # TODO：真实后台联调时核对（iframe/影子 DOM/动态 class 都要确认）
    "login": {"username": "#usernameId", "password": "#passwordId", "submit": "button.login-btn"},
    "workbench": ".workbench-container",
    "conv_item": ".session-list .session-item",
    "buyer_msg": ".message-item.from-customer",
    "reply_input": ".chat-input textarea",
    "send_btn": ".chat-input .send-btn",
    "chat_head": ".chat-panel-header",
}


def TARGET_URL(platform: str) -> str:
    if settings.channel_rpa_target == "real":
        from app.services.channels.catalog import get_platform
        return (get_platform(platform) or {}).get("login_url", "")
    return settings.channel_sim_url
