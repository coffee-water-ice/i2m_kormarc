"""
500(원저자명 주기)·700(개인명 부출)·710(기관명 부출) 필드 생성 모듈 — STUB

원본: 245/245/app.py 의 저자/원저자 관련 함수군 (docs/INTEGRATION_SURVEY.md 245 섹션 참고).
이식 대상 함수(원본 app.py 기준): build_500(...), build_700(...), build_710(...),
korean_name_reverse(...), english_name_reverse(...).

245와 표제 정보를 공유하므로 core/fields/marc_245.py 의 공통 전처리 함수를 import해서 쓴다
(INTEGRATION_PRINCIPLES.md #9 예외 조항).

이식 시 core/name_data/ 의 이름판별 데이터(korean_surnames, korean_given_names,
korean_real_name_allowlist, japanese_surnames)를 사용해 700/710 지시기호(개인명/단체명,
성 유무)를 판별한다. 데이터 자산은 이미 core/name_data/ 자리에 옮겨져 있다
(README.md 참고, 실제 데이터 파일은 245/245/*.py에서 이식 필요).

적용할 원칙:
  - #6  에러는 (tag, error) 튜플로 반환
  - #7  core.debug_log.dbg/dbg_err + "[700]" 등 프리픽스 사용
"""

from __future__ import annotations


def build_500_700_710(item: dict, authors_hint: list | None = None, secrets: dict | None = None) -> dict:
    """
    500/700/710 MRK 문자열을 dict로 반환한다. 700/710은 여러 건이 나올 수 있어 리스트로 담는다.
    예: {"500": "...", "700": ["...", "..."], "710": ["..."]}
    (미구현 — 245/app.py의 저자/원저자 빌더 이식 필요)
    """
    raise NotImplementedError(
        "245/app.py의 책임표시 계열 빌더(build_500/build_700/build_710)를 이식해야 합니다. "
        "docs/INTEGRATION_SURVEY.md의 245 섹션을 참고하세요."
    )
