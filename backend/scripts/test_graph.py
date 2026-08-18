import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.supervisor import supervisor


def main():
    for q in ["退货政策是什么", "帮我查下天气", "运费怎么算"]:
        result = supervisor.invoke({"question": q, "history": [], "steps": []})
        print(f"\n问题: {q}")
        print(f"意图: {result['intent']}")
        print(f"轨迹: {' -> '.join(result['steps'])}")
        print(f"回答: {result['answer']}")
        print(f"拒答: {result['refused']}")


if __name__ == "__main__":
    main()