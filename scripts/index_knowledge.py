"""data/knowledge/ PDF 인덱싱 스크립트 (증분식 — 변경 없는 문서는 스킵).

사용법: .venv\\Scripts\\python.exe scripts\\index_knowledge.py
중단해도 다음 실행에서 완료되지 않은 문서부터 다시 처리된다.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)

from app import db, kb  # noqa: E402

if __name__ == "__main__":
    db.init_db()
    stats = kb.index_all()
    print(f"\n결과: 인덱싱 {stats['indexed']} / 스킵 {stats['skipped']} / 제거 {stats['removed']} / 실패 {stats['failed']}")
