"""渠道 RPA Worker：轮询已启用的 RPA 连接，登录商家后台收发消息。

职责：发现 pending/connected 的 RPA 连接 → 每连接一个持久化浏览器 profile
→ 拉新买家消息 → 经渠道桥跑 AI 引擎 → 回复发回页面。异常写回 status/last_error。

用法：
  python scripts/channel_worker.py              # 常驻轮询（每 3s 一个周期）
  python scripts/channel_worker.py --once       # 跑一个周期（测试用）
  python scripts/channel_worker.py --headed     # 有头模式（演示看得到浏览器操作）
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import ChannelConnection  # noqa: E402
from app.services import crypto  # noqa: E402
from app.services.channels import bridge  # noqa: E402
from app.services.channels.rpa.adapter import RpaAdapter  # noqa: E402

PROFILE_ROOT = Path(__file__).resolve().parent.parent / "rpa_profiles"


def run_cycle(pw, adapters: dict, headless: bool = True) -> list[dict]:
    """一个轮询周期：同步连接状态 → 处理活跃连接的新消息。返回本周期动作日志。"""
    actions: list[dict] = []
    with SessionLocal() as db:
        rows = db.scalars(select(ChannelConnection).where(
            ChannelConnection.mode == "rpa",
            ChannelConnection.status.in_(["pending", "connected"]))).all()
        active_ids = set()
        for conn in rows:
            active_ids.add(str(conn.id))
            entry = adapters.get(str(conn.id))
            if entry is None:
                # 启动浏览器 + 登录（pending → connected）
                adapter = RpaAdapter(conn, crypto.unseal(conn.credentials_cipher))
                profile = PROFILE_ROOT / str(conn.id)
                profile.mkdir(parents=True, exist_ok=True)
                try:
                    adapter.attach(pw, str(profile), headless=headless)
                except Exception as e:  # noqa: BLE001
                    conn.status = "error"
                    conn.last_error = f"RPA 登录失败：{e}"[:500]
                    db.commit()
                    continue
                conn.status = "connected"
                conn.last_error = None
                db.commit()
                adapters[str(conn.id)] = adapter
                entry = adapter
            # 处理新消息
            try:
                for m in entry.fetch_new_messages():
                    reply = bridge.process_channel_message(db, conn, m)
                    if reply is None:  # BYOK 未配置等场景：跳过不回，不崩 worker
                        actions.append({"conn": str(conn.id), "conv": m.conversation_ref,
                                        "inbound": m.text[:60], "reply": "(skipped: 模型未配置)"})
                        continue
                    entry.send_reply(reply)
                    actions.append({"conn": str(conn.id), "conv": m.conversation_ref,
                                    "inbound": m.text[:60], "reply": reply.text[:60]})
            except Exception as e:  # noqa: BLE001 —— 会话级异常降级为连接错误
                conn.status = "error"
                conn.last_error = f"RPA 处理失败：{e}"[:500]
                db.commit()
                entry.close()
                adapters.pop(str(conn.id), None)
        # 数据库里消失/停用的连接 → 关浏览器
        for cid in list(adapters.keys()):
            if cid not in active_ids:
                adapters[cid].close()
                adapters.pop(cid, None)
    return actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑一个周期（测试）")
    ap.add_argument("--poll", type=float, default=3.0, help="轮询间隔秒")
    ap.add_argument("--headed", action="store_true", help="有头模式（演示）")
    args = ap.parse_args()

    adapters: dict = {}
    with sync_playwright() as pw:
        while True:
            acts = run_cycle(pw, adapters, headless=not args.headed)
            for a in acts:
                print(f"💬 [{a['conv']}] 买家: {a['inbound']}  →  AI: {a['reply']}", flush=True)
            if args.once:
                break
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
