"""
core/fields/marc_260.py
260(발행사항) 필드 생성 규칙 — 실제 동작(260+300 폴더에서 이관).

원본: 260+300/core/field_rules.py 의 260 섹션.
발행지 판정 자체는 api/publisher_db.py의 build_pub_location_bundle()이 담당하며,
이 모듈은 판정된 place_display/publisher_name/pubyear를 MARC 260 형식으로만 조립한다.
"""

from __future__ import annotations

import re

from pymarc import Field

from core.marc_builder import mrk_str_to_field

# 260 $b 표시용 법인격 제거 패턴
# api/publisher_db.normalize_publisher_name()은 비교 전용(소문자·공백 제거) — 표시용은 별도 처리
_PUB_LEGAL_RE = re.compile(
    r"㈜|㈔"
    r"|\(주\)|\(재\)|\(주식회사\)|\(유한회사\)|\(사단법인\)|\(재단법인\)"
    r"|주식회사\s*|유한회사\s*"
    r"|Co\.,?\s*Ltd\.?|Inc\.?"
    r"|\([A-Za-z][^)]*\)",   # 괄호 영문명 (MinumSa) 등
    flags=re.IGNORECASE,
)


def _clean_pub_name(name: str) -> str:
    """260 $b 표시용: 법인격 표기(㈜·(주식회사)·주식회사·Co.,Ltd. 등) 제거."""
    return _PUB_LEGAL_RE.sub("", name or "").strip(" ,.")


def build_260(
    place_display: str, publisher_name: str, pubyear: str, publisher_name2: str = ""
) -> str:
    """
    260 MRK 문자열을 생성한다.

    publisher_name2: 임프린트·KPIPA 등에서 알라딘 출판사명과 다른 발행처가
                     확인된 경우 두 번째 $b로 추가된다.
                     예) "=260  \\\\$a파주 :$b요요 :$b다산북스,$c2022"
    """
    place = place_display or "발행지 미상"
    pub   = _clean_pub_name(publisher_name) or "발행처 미상"
    year  = pubyear or "발행년 미상"
    if publisher_name2:
        pub2 = _clean_pub_name(publisher_name2)
        if pub2:
            return f"=260  \\\\$a{place} :$b{pub} :$b{pub2},$c{year}"
    return f"=260  \\\\$a{place} :$b{pub},$c{year}"


def build_260_field(
    place_display: str, publisher_name: str, pubyear: str, publisher_name2: str = ""
) -> tuple[str, Field | None]:
    """
    260 MRK 문자열과 pymarc.Field 객체를 함께 반환한다.

    Returns:
        (mrk_str, Field 객체)  — Field 변환 실패 시 (mrk_str, None)
    """
    tag_260 = build_260(place_display, publisher_name, pubyear, publisher_name2)
    f_260 = mrk_str_to_field(tag_260)
    return tag_260, f_260
