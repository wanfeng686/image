"""测试共用工具：邮箱注册流程（send-code → register）与结果统计。

本地未配 SMTP 时 mail_dev_mode=True，send-code 响应携带 dev_code，测试直接用它注册。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def register_tenant(client, tenant_name: str, email: str, password: str = "pass123456",
                    base: str = "http://127.0.0.1:8000", with_ai: bool = False):
    """走完整邮箱注册流程，返回 (注册响应, 响应体)。

    with_ai=True 时顺手用平台 .env 的模型配置补 BYOK（否则聊天会被 409 闸门拦）。
    """
    r = client.post(f"{base}/api/portal/email/send-code", json={"email": email})
    code = r.json().get("dev_code")
    if code is None:
        raise RuntimeError(f"send-code 未返回 dev_code（检查 MAIL_DEV_MODE）：{r.text[:200]}")
    r2 = client.post(f"{base}/api/portal/register", json={
        "tenant_name": tenant_name, "email": email, "code": code, "password": password})
    body = r2.json()
    if with_ai and r2.status_code == 201:
        configure_ai(client, body["token"], base=base)
    return r2, body


def configure_ai(client, token: str, base: str = "http://127.0.0.1:8000"):
    """用平台 .env 的模型服务给新注册商户补 BYOK 配置（测试辅助）。"""
    from app.core.config import settings

    r = client.put(f"{base}/api/portal/ai-config",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"base_url": settings.llm_base_url,
                         "api_key": settings.llm_api_key,
                         "model": settings.llm_model})
    if r.status_code != 200:
        raise RuntimeError(f"configure_ai 失败：{r.text[:200]}")
    return r.json()


class Tally:
    def __init__(self):
        self.passed = self.failed = 0

    def check(self, name, cond, detail=""):
        print(("✅" if cond else "❌") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))
        self.passed += 1 if cond else 0
        self.failed += 0 if cond else 1

    def done(self, label: str) -> int:
        print(f"\n{label}：{self.passed} 通过，{self.failed} 失败")
        return 1 if self.failed else 0
