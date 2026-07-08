"""
api/nlk_client.py
국립중앙도서관(NLK) 연동 — STUB. 이름은 하나지만 완전히 다른 두 용도가 합류할 자리다.

원본 1 (653): backend/app/nlk_client.py, nlk_metadata.py — Seoji API로 ISBN 부가기호
              (KDC 분류코드)만 조회. 앱 본선 파이프라인에서 제한적으로 사용.
              이식 대상: fetch_kdc_content_code_by_isbn(), fetch_nlk_hint_by_isbn()
원본 2 (245): 245/245/nlk_opac.py — NLK OPAC 검색 + MARC 뷰 폴백 조회로 원서명/책임표시 보강.
              이식 대상: fetch_nlk_orig_info(isbn13, title), fetch_nlk_responsibility_statement(isbn13)

두 용도를 한 파일에 함수명으로 구분해 공존시킨다(같은 기관의 다른 API 엔드포인트이므로
파일을 억지로 나누지 않는다).
"""

from __future__ import annotations


def fetch_kdc_content_code_by_isbn(isbn: str, api_key: str) -> str | None:
    """Seoji API로 ISBN 부가기호(KDC 내용분류코드)를 조회한다. (미구현 — 653 nlk_client.py 이식 필요)"""
    raise NotImplementedError("653/backend/app/nlk_client.py의 Seoji 조회 함수를 이식해야 합니다.")


def fetch_nlk_orig_info(isbn13: str, title: str) -> dict:
    """NLK OPAC에서 원서명/원저자 정보를 조회한다. (미구현 — 245/nlk_opac.py 이식 필요)"""
    raise NotImplementedError("245/245/nlk_opac.py의 fetch_nlk_orig_info()를 이식해야 합니다.")


def fetch_nlk_responsibility_statement(isbn13: str) -> str | None:
    """NLK MARC 뷰에서 책임표시(700/710 폴백)를 조회한다. (미구현 — 245/nlk_opac.py 이식 필요)"""
    raise NotImplementedError("245/245/nlk_opac.py의 책임표시 조회 함수를 이식해야 합니다.")
