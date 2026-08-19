"""测试共用工具：邮箱注册流程（send-code → register）与结果统计。

本地未配 SMTP 时 mail_dev_mode=True，send-code 响应携带 dev_code，测试直接用它注册。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def register_tenant(client, tenant_name: str, email: str, password: str = "pass123456",
                    base: str = "http://127.0.0.1:8000"):
    """走完整邮箱注册流程，返回 (注册响应, 响应体)。"""
    r = client.post(f"{base}/api/portal/email/send-code", json={"email": email})
    code = r.json().get("dev_code")
    if code is None:
        raise RuntimeError(f"send-code 未返回 dev_code（检查 MAIL_DEV_MODE）：{r.text[:200]}")
    r2 = client.post(f"{base}/api/portal/register", json={
        "tenant_name": tenant_name, "email": email, "code": code, "password": password})
    return r2, r2.json()


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
