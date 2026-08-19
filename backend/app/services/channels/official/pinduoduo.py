"""拼多多开放平台官方 API 客户端。

签名规则（拼多多开放平台）：所有请求参数按 key ASCII 升序拼成 k1v1k2v2…，
末尾追加 client_secret，取 MD5 小写。网关 POST/GET 均可，响应 JSON 中
出现 error_response 即失败。

消息链路（联调时按商家权限核对 type 名）：
- 会话列表/轮询新消息：pdd.im 相关接口（需商家授权 access_token）
- 发送回复：同上
真实联调前提：商家在拼多多开放平台完成应用授权拿到 access_token 后，
在门户「编辑凭据」里补填。
"""
import hashlib
import time

import httpx

GATEWAY = "https://gw-api.pinduoduo.com/api/router"


def sign(params: dict, client_secret: str) -> str:
    plain = "".join(f"{k}{params[k]}" for k in sorted(params)) + client_secret
    return hashlib.md5(plain.encode("utf-8")).hexdigest().upper()  # noqa: S324 —— 平台规定 MD5


def call(creds: dict, api_type: str, api_params: dict | None = None,
         with_token: bool = True, timeout: float = 15.0) -> tuple[int, dict]:
    """发起一次签名调用。返回 (http_status, 响应 JSON)。creds 需含 client_id/client_secret[/access_token]。"""
    params: dict = {
        "type": api_type,
        "timestamp": str(int(time.time())),
        "client_id": creds["client_id"],
    }
    if with_token:
        token = creds.get("access_token") or ""
        if token:
            params["access_token"] = token
    params.update({k: v for k, v in (api_params or {}).items() if v is not None})
    params["sign"] = sign(params, creds["client_secret"])

    with httpx.Client(timeout=timeout) as client:
        r = client.post(GATEWAY, json=params)
    try:
        body = r.json()
    except ValueError:
        body = {"error_response": {"error_msg": f"非 JSON 响应：HTTP {r.status_code}"}}
    return r.status_code, body


def _err_msg(body: dict) -> str:
    e = body.get("error_response") or {}
    return f"{e.get('sub_code') or e.get('error_code', '')} {e.get('sub_msg') or e.get('error_msg', '')}".strip()


def test_credentials(creds: dict) -> dict:
    """连接测试：
    - 有 access_token：调 pdd.mall.info.get 拉店铺名，成功即 connected
    - 无 access_token：仍发一次签名请求，按错误语义判断 client_id/secret 是否被平台接受
      （「缺少 access_token/授权」类错误 = 签名与凭据有效，只差商家授权）
    """
    if not creds.get("client_id") or not creds.get("client_secret"):
        return {"ok": False, "detail": "缺少 client_id / client_secret"}

    if creds.get("access_token"):
        try:
            status, body = call(creds, "pdd.mall.info.get", {})
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"网络错误：{e}"}
        if "error_response" in body:
            return {"ok": False, "detail": f"调用失败：{_err_msg(body)}"}
        mall = body.get("mall_info_get_response", {}).get("mall_info", {})
        return {"ok": True, "detail": "店铺信息获取成功",
                "shop_name": mall.get("mall_name")}

    # 无 token 的凭据探测
    try:
        status, body = call(creds, "pdd.mall.info.get", {}, with_token=True)
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"网络错误：{e}"}
    if "error_response" not in body:
        return {"ok": True, "detail": "凭据有效（该接口未要求授权）"}
    msg = _err_msg(body)
    lowered = msg.lower()
    if any(k in lowered for k in ("access_token", "token", "授权", "auth")):
        return {"ok": True, "detail": "签名与凭据已被平台接受，请在商家授权后补填 access_token"}
    return {"ok": False, "detail": f"凭据未被接受：{msg}"}


def fetch_new_messages(creds: dict, since_ts: int | None = None) -> dict:
    """轮询新消息。真实 type 名与分页参数在联调时核对（需 access_token）。"""
    status, body = call(creds, "pdd.im.session.list.get",
                        {"page": 1, "page_size": 20})
    return body


def send_reply(creds: dict, conversation_ref: str, text: str) -> dict:
    """发送回复。真实 type 名与参数在联调时核对（需 access_token）。"""
    status, body = call(creds, "pdd.im.message.send",
                        {"conversation_id": conversation_ref, "content": text})
    return body
