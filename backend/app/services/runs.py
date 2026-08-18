"""轨迹记账：每个节点把执行过程写入 agent_runs（W3 轨迹时间线的数据源）。"""
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentRun


def log_run(
    db: Session | None,
    session_id,
    agent_name: str,
    graph_node: str,
    input_summary: dict | None,
    output: dict | None,
    status: str = "success",
    latency_ms: int | None = None,
    error: str | None = None,
    message_id: uuid.UUID | None = None,
    used_llm: bool = False,
) -> None:
    """失败不抛错：轨迹记账挂了不能影响主流程。"""
    if db is None:
        return
    try:
        db.add(AgentRun(
            session_id=session_id,
            message_id=message_id,
            agent_name=agent_name,
            graph_node=graph_node,
            provider_name="deepseek" if used_llm else None,
            model_name=settings.llm_model if used_llm else None,
            input=input_summary,
            output=output,
            status=status,
            error=error,
            latency_ms=latency_ms,
        ))
        db.flush()
    except Exception:  # noqa: BLE001 —— 记账失败静默，主流程继续
        pass


class Timer:
    """with Timer() as t: ... 之后 t.ms 即耗时毫秒数。"""

    def __enter__(self):
        self.t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.t0) * 1000)
