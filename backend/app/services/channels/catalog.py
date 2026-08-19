"""电商平台目录：支持的平台、接入方式、凭据表单 schema。

本轮只开放拼多多（available=True，官方 API + RPA 双模）；其余平台占位
（available=False，向导中灰显「即将支持」，不建连接）。
"""

PLATFORMS: dict[str, dict] = {
    "pinduoduo": {
        "name": "拼多多",
        "icon": "🛒",
        "available": True,
        "modes": ["official_api", "rpa"],
        "login_url": "https://mms.pinduoduo.com/",
        "api_base": "https://gw-api.pinduoduo.com/api/router",
        "desc": "拼多多商家店铺，支持官方开放平台 API 与托管浏览器两种接入",
        "api_fields": [
            {"key": "client_id", "label": "Client ID", "type": "text",
             "placeholder": "拼多多开放平台应用的 client_id", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password",
             "placeholder": "开放平台应用的 client_secret", "required": True},
            {"key": "access_token", "label": "商家授权 Access Token", "type": "text",
             "placeholder": "商家授权后获得，可稍后在「编辑凭据」补充", "required": False},
        ],
        "rpa_fields": [
            {"key": "username", "label": "店铺账号（手机号）", "type": "text",
             "placeholder": "拼多多商家后台登录账号", "required": True},
            {"key": "password", "label": "店铺密码", "type": "password",
             "placeholder": "将由托管浏览器登录使用，AES 加密存储", "required": True},
        ],
    },
    "taobao": {"name": "淘宝/天猫", "icon": "🟠", "available": False,
               "modes": ["official_api", "rpa"], "login_url": "https://myseller.taobao.com/",
               "desc": "即将支持：淘宝开放平台 API 与千牛后台托管"},
    "douyin": {"name": "抖音小店", "icon": "🎵", "available": False,
               "modes": ["official_api", "rpa"], "login_url": "https://fxg.jinritemai.com/",
               "desc": "即将支持：抖店开放平台 API 与后台托管"},
    "jd": {"name": "京东", "icon": "🔴", "available": False,
           "modes": ["official_api", "rpa"], "login_url": "https://item.jd.com/",
           "desc": "即将支持：京东宙斯开放平台"},
    "kuaishou": {"name": "快手小店", "icon": "⚡", "available": False,
                 "modes": ["official_api", "rpa"], "login_url": "https://s.kwaixiaodian.com/",
                 "desc": "即将支持：快手电商开放平台"},
    "xhs": {"name": "小红书", "icon": "📕", "available": False,
            "modes": ["official_api", "rpa"], "login_url": "https://ark.xiaohongshu.com/",
            "desc": "即将支持：小红书蒲公英/商家后台"},
    "weixin": {"name": "微信小店", "icon": "💬", "available": False,
               "modes": ["official_api", "rpa"], "login_url": "https://store.weixin.qq.com/",
               "desc": "即将支持：微信小店开放接口"},
}


def get_platform(code: str) -> dict | None:
    return PLATFORMS.get(code)


def fields_for(code: str, mode: str) -> list[dict]:
    p = PLATFORMS.get(code) or {}
    return p.get("api_fields" if mode == "official_api" else "rpa_fields", [])


def public_catalog() -> list[dict]:
    """目录的对外形态（向导用，含凭据表单 schema）。"""
    items = []
    for code, p in PLATFORMS.items():
        items.append({
            "code": code, "name": p["name"], "icon": p.get("icon", "🏪"),
            "available": p.get("available", False),
            "modes": p.get("modes", []), "desc": p.get("desc", ""),
            "login_url": p.get("login_url", ""),
            "api_fields": p.get("api_fields", []),
            "rpa_fields": p.get("rpa_fields", []),
        })
    return items
