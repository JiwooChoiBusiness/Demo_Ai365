"""LLM 스모크 테스트 — generate / stream / embed 실동작 확인.

사용법: .venv\\Scripts\\python.exe scripts\\smoke_llm.py
키 값은 출력하지 않는다(로테이션 로그는 키 인덱스만).
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app import llm  # noqa: E402


def main() -> None:
    print("=== 1/3 generate ===")
    text = llm.generate("대한민국의 수도를 한 단어로 답해줘.")
    print(f"응답: {text.strip()}")
    assert text.strip(), "generate 응답이 비어 있음"

    parsed = llm.generate(
        "사과, 바나나를 {\"items\": [...]} 형태의 JSON 배열로 만들어줘.",
        json_mode=True,
    )
    print(f"json_mode 응답 타입: {type(parsed).__name__}, 내용: {parsed}")
    assert isinstance(parsed, dict), "json_mode 파싱 실패"

    print("\n=== 2/3 stream ===")
    chunks = 0
    for token in llm.stream("1부터 5까지 한 줄로 세어줘."):
        print(token, end="", flush=True)
        chunks += 1
    print(f"\n(청크 {chunks}개 수신)")
    assert chunks > 0, "stream 청크가 없음"

    print("\n=== 3/3 embed ===")
    vecs = llm.embed(["회사 휴가 규정", "월별 매출 추이"])
    print(f"벡터 {len(vecs)}개, 차원 {len(vecs[0])}")
    assert len(vecs) == 2 and len(vecs[0]) > 0, "embed 결과 이상"

    print("\n모든 스모크 테스트 성공")


if __name__ == "__main__":
    main()
