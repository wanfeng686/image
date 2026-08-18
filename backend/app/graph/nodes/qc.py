"""质检节点：知识回答发送前的最后一道闸。

打回重写 ≤2 次（全局上限），超限降级人工（qc_overflow）。
确定性预检（引用/数字）+ LLM 忠实性判定双保险。
"""
from app.agent import qc as qc_agent
from app.services import llm
from app.services.runs import Timer, log_run

MAX_REWRITES = 2  # DESIGN A1：全局最多打回 2 次


def qc_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    question = state["question"]
    answer = state.get("answer")
    chunks = state.get("chunks") or []

    # 拒答/空回答/卡片类回答无需质检（没有事实主张）
    if not answer or not chunks or state.get("card"):
        return {"qc_passed": True, "steps": state.get("steps", []) + ["qc"]}

    problems: list[str] = []
    with Timer() as t:
        det_ok, det_problems = qc_agent.deterministic_check(answer, chunks)
        problems += det_problems
        llm_verdict = None
        if det_ok:  # 确定性检查过了才花 LLM 做忠实性深检
            try:
                raw = llm.chat(qc_agent.build_messages(question, answer, chunks),
                               temperature=0.0, agent="qc")
                llm_verdict = qc_agent.parse_verdict(raw)
            except Exception:  # noqa: BLE001 —— 质检挂了放行原文（降级不阻塞）
                llm_verdict = None
        if llm_verdict is not None and not llm_verdict["pass"]:
            problems += llm_verdict["problems"]

    rewrites = state.get("rewrite_count", 0)
    passed = not problems

    log_run(
        db, session.id if session else None, "qc", "qc",
        input_summary={"answer": answer[:200]},
        output={"pass": passed, "problems": problems, "rewrite_count": rewrites,
                "llm_judged": llm_verdict is not None},
        latency_ms=t.ms, message_id=state.get("message_id"),
        used_llm=llm_verdict is not None,
        status="success" if passed else "rejected",
    )

    if passed:
        return {"qc_passed": True, "steps": state.get("steps", []) + ["qc"]}

    if rewrites < MAX_REWRITES:
        # 打回重写：带着问题清单回知识节点
        return {
            "qc_passed": False,
            "rewrite_count": rewrites + 1,
            "qc_feedback": "；".join(problems[:3]),
            "steps": state.get("steps", []) + ["qc"],
        }

    # 超限：降级人工（DESIGN A1）。qc_passed 置 True 表示"质检流程终结"，
    # 让路由走 respond 结束回环（真实结果已记进 agent_runs.status=rejected）。
    if session is not None:
        session.escalated_reason = "qc_overflow"
    return {
        "qc_passed": True,
        "answer": "抱歉，为确保准确，这个问题我需要转人工处理。",
        "refused": True,
        "chunks": [],
        "steps": state.get("steps", []) + ["qc"],
    }
