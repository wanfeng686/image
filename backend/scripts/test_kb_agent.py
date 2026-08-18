import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import knowledge
from app.services import kb, llm


def main():
    questions = [
        "你们退货政策是什么？",   # 能答：命中 kb-001
        "买完多久能发货？",       # 能答：命中 kb-003
        "今天天气怎么样？",       # 该拒答：什么都没命中
    ]
    for q in questions:
        chunks = kb.retrieve(q)
        print(f"\n问题: {q}")
        print(f"检索到 {len(chunks)} 个片段: {[c['id'] for c in chunks]}")
        answer = llm.chat(knowledge.build_messages(q, chunks))
        print(f"回答: {answer}")
        print(f"拒答判定: {knowledge.is_refusal(answer)}")


if __name__ == "__main__":
    main()