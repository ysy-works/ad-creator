"""
템플릿 라이브러리 점검 스크립트.

12개 카테고리 폴더에 사진이 몇 장씩 들어있는지 확인하고,
비어있는 폴더를 경고한다.

실행:
  python scripts/check_library.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import template_library as tl
from configs import config


def main():
    status = tl.library_status()
    total = sum(s["count"] for s in status)
    empty = [s for s in status if s["count"] == 0]

    print(f"템플릿 라이브러리 현황 ({config.TEMPLATES_DIR})\n")
    print(f"{'스타일':22} {'구도':20} 장수")
    print("-" * 50)
    for s in status:
        sn = config.STYLE_NAMES.get(s["style_id"], s["style_id"])
        cn = config.COMPOSITION_NAMES.get(s["composition_id"], s["composition_id"])
        mark = "  ⚠ 비어있음" if s["count"] == 0 else ""
        print(f"{sn:20} {cn:18} {s['count']:>3}{mark}")

    print("-" * 50)
    print(f"총 {total}장, 카테고리 {len(status)}개 중 빈 폴더 {len(empty)}개")
    if empty:
        print("\n⚠ 아래 카테고리는 템플릿이 없어 요청 시 에러가 납니다:")
        for s in empty:
            print(f"  templates_lib/{s['style_id']}/{s['composition_id']}/")


if __name__ == "__main__":
    main()
