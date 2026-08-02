"""
core/fields/marc_020_950.py
KORMARC 020(ISBN)·950(가격) 필드 생성 모듈.

원본: 2025년 코드(1215_main.py, 단일 파일 5284줄)의
  - _build_020_from_item_and_nlk() / fetch_additional_code_from_nlk() (020)
  - _extract_price_kr() / build_950_from_item_and_price() / crawl_aladin_original_and_price() (950)

GPT 호출 없는 순수 규칙 기반 필드다.

이식 시 적용한 원칙(docs/INTEGRATION_PRINCIPLES.md):
  - #7  core.debug_log.dbg를 "[020]"/"[950]" 프리픽스로 사용.
  - #9  NLK Seoji 조회는 api/nlk_client.py에, 알라딘 정가 크롤링 폴백은
        api/aladin_scraper.py에 두고 이 모듈은 조립만 담당한다(041/653 선례와 동일).

원본과 다르게 이식한 부분:
  - 950 서브필드 값: 원본 f"=950  0\\$b\\{price}"는 $b 값 앞에 의도치 않은
    백슬래시가 그대로 섞여 나가는 표기였다(사용자 확인 결과 "0_ $b + 원화기호 +
    가격"이 맞는 표기) — 이식하며 "=950  0\\$b₩{price}"(원화기호, 스트레이
    백슬래시 없음)로 바로잡았다.
  - NLK Seoji 조회는 원본의 4-URL 순차 시도(도메인 이전 대응) 대신, 이 프로젝트의
    다른 NLK 호출들과 동일하게 단일 URL + requests 동기 호출로 단순화했다
    (api/nlk_client.fetch_isbn_addendum_from_nlk).
"""

from __future__ import annotations

import re

from core.debug_log import dbg
from api.nlk_client import fetch_isbn_addendum_from_nlk
from api.aladin_scraper import crawl_aladin_price


# ═══════════════════════════════════════════════════════════════
# 1. 020 — ISBN(+ 부가기호 + 가격, 세트 ISBN)
# ═══════════════════════════════════════════════════════════════

def build_020_fields(item: dict, isbn: str, *, nlk_cert_key: str = "") -> list[str]:
    """
    020 MRK 문자열 목록을 반환한다("=020  \\\\$a{ISBN}$g{부가기호}:$c{가격}").
    NLK에 SET_ISBN(세트 ISBN)이 있으면 "=020  1\\$a{set_isbn} (set)" 한 줄을 더 붙인다.

    Args:
        item: 알라딘 API item dict.
        isbn: ISBN-13.
        nlk_cert_key: 국립중앙도서관 OpenAPI 인증키(core.config.Settings.nlk_cert_key).
                      비어 있으면 부가기호/세트ISBN/NLK가격 조회를 건너뛴다(041/245와
                      동일하게 별도 opt-in 플래그 없이 키 유무로만 판단).
    """
    price = str((item or {}).get("priceStandard", "") or "").strip()

    nlk = fetch_isbn_addendum_from_nlk(isbn, nlk_cert_key) if nlk_cert_key else {}
    add_code = nlk.get("add_code", "")
    price = price or nlk.get("price", "")

    parts = [f"=020  \\\\$a{isbn}"]
    if add_code:
        parts.append(f"$g{add_code}")
    if price:
        parts.append(f":$c{price}")
    dbg(f"[020] isbn={isbn} add_code={add_code!r} price={price!r}")

    tags = ["".join(parts)]

    set_isbn = nlk.get("set_isbn", "")
    if set_isbn:
        tags.append(f"=020  1\\$a{set_isbn} (set)")
        dbg(f"[020] 세트 ISBN 발견: {set_isbn}")

    return tags


# ═══════════════════════════════════════════════════════════════
# 2. 950 — 가격
# ═══════════════════════════════════════════════════════════════

def _extract_price_kr(item: dict, isbn: str) -> str:
    """알라딘 표준가 우선, 없으면 알라딘 상품페이지 크롤링으로 폴백. 숫자만 반환."""
    raw = str((item or {}).get("priceStandard", "") or "").strip()
    if not raw:
        raw = crawl_aladin_price(isbn)
    return re.sub(r"[^\d]", "", raw)


def build_950_field(item: dict, isbn: str) -> str | None:
    """
    950 MRK 문자열("=950  0\\$b₩{가격}")을 반환한다. 가격을 못 찾으면 None(필드 생략).
    """
    price = _extract_price_kr(item, isbn)
    if not price:
        dbg("[950] 가격 정보 없음 → 필드 생략")
        return None
    dbg(f"[950] price={price}")
    return f"=950  0\\$b₩{price}"
