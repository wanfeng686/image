"""质检 Agent（QC）：三段式蕴含检查（DESIGN §4.2 / C1 C2 C3）。

① 引用存在（代码判定，确定性）  ② 条件覆盖·数字核对（代码判定）
③ 忠实性 NLI 式蕴含检查（LLM 判定）
纯函数无 IO，可单测。
"""
import json
import re

SYSTEM_PROMPT = """你是客服系统的质检员，对【回答】做发送前最后一道检查。只输出 JSON，不要输出其他文字。

输出格式：{"pass": true, "problems": []}

检查三项，任何一项不过就 pass=false 并在 problems 里给出具体问题：
1. 引用存在：回答里的 [kb-xxx] 编号必须真实存在于【知识片段】中
2. 条件覆盖：知识片段中的关键数字、时限、限定条件（如"7天""吊牌完整""食品不支持"）在回答中不缺失、不曲解、不反向
3. 忠实性：回答中的每一个论断都必须能被【知识片段】直接支持，不允许出现片段里没有的信息"""


def build_messages(question: str, answer: str, chunks: list[dict]) -> list[dict]:
    context = "\n\n".join(f"[{c['id']}] {c['title']}：{c['content']}" for c in chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【顾客问题】\n{question}\n\n【知识片段】\n{context}\n\n【待检回答】\n{answer}"},
    ]


def parse_verdict(text: str) -> dict | None:
    """防御性解析 LLM 判定；失败视为不通过（宁严勿松）。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    problems = [p for p in data.get("problems", []) if isinstance(p, str)][:5]
    return {"pass": bool(data.get("pass")), "problems": problems}


# ---------- 确定性预检（代码判定，不花 LLM） ----------

_CITE_RE = re.compile(r"\[?(kb-\d+)\]?", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def citation_ok(answer: str, chunks: list[dict]) -> tuple[bool, list[str]]:
    """① 引用存在：回答引用的编号必须在检索片段里。"""
    valid = {c["id"].lower() for c in chunks}
    cited = {c.lower() for c in _CITE_RE.findall(answer or "")}
    ghost = [c for c in cited if c not in valid]
    return (not ghost), [f"引用了不存在的片段 {c}" for c in ghost]


def number_coverage(answer: str, chunks: list[dict]) -> tuple[bool, list[str]]:
    """② 条件覆盖（数字维度）：被引片段中的关键数字必须出现在回答里。

    仅核对被引用片段（未被引用的片段条件不算数），避免过度苛求转述。
    """
    cited = {c.lower() for c in _CITE_RE.findall(answer or "")}
    problems = []
    for c in chunks:
        if c["id"].lower() not in cited:
            continue
        nums = _NUM_RE.findall(c["content"])
        nums = [n for n in nums if n not in c["id"]]  # 剔除编号自身数字
        missing = [n for n in dict.fromkeys(nums) if n not in (answer or "")]
        if missing:
            problems.append(f"[{c['id']}] 的关键数字 {missing} 未在回答中体现")
    return (not problems), problems


def deterministic_check(answer: str, chunks: list[dict]) -> tuple[bool, list[str]]:
    ok1, p1 = citation_ok(answer, chunks)
    ok2, p2 = number_coverage(answer, chunks)
    return (ok1 and ok2), (p1 + p2)
