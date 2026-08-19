"""邮件发送：邮箱验证码经 SMTP 发出（stdlib smtplib，无新增依赖）。

- 未配置 SMTP 时返回 (False, None)：调用方按 mail_dev_mode 决定是否走本地联调回退。
- 生产要求配置真实 SMTP（见 docs/DEPLOY.md）；发送失败不吞异常细节，返回错误说明。
"""
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from app.core.config import settings


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


def send_mail(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """返回 (成功, 错误信息)。"""
    if not smtp_configured():
        return False, None   # 未配置：交由调用方决定 dev 回退或报错
    sender = settings.smtp_from or settings.smtp_user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("SmartSupport", "utf-8")), sender))
    msg["To"] = to
    try:
        if settings.smtp_port == 465:
            srv = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
        else:
            srv = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            srv.starttls()
        with srv:
            srv.login(settings.smtp_user, settings.smtp_pass)
            srv.sendmail(sender, [to], msg.as_string())
        return True, None
    except Exception as e:  # noqa: BLE001 —— 发信失败要给用户可读原因
        return False, f"{type(e).__name__}: {e}"
