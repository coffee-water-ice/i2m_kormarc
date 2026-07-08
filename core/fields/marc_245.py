"""
245(표제/책임표시)·246(원서명)·900(원저자 한글명) 필드 생성 모듈 — STUB

원본: 245/245/app.py (3404줄, docs/INTEGRATION_SURVEY.md 245 섹션 참고).
이식 대상 함수(원본 app.py 기준): build_245(...), build_246(...), build_900(...),
scrape_aladin_product(item_id) — 단, 크롤링 부분은 api/aladin_scraper.py로 분리 이관.

245와 500/700/710은 authors, orig_title 등을 강하게 공유하므로(INTEGRATION_PRINCIPLES.md #9
예외 조항), 공통 전처리 함수(원본의 parse_authors, collect_orig_info 등)는 이 파일에 두고
core/fields/marc_500_700_710.py 가 이 파일에서 import해서 쓴다.

적용할 원칙:
  - #1  api/aladin_client.OPT_RESULT_FULL이 이미 subInfo/authors를 포함하므로
        245/app.py 원본처럼 authors,subInfo,seriesInfo만 별도로 재요청할 필요 없음
  - #5  245/app.py 원본의 ALADIN_API_KEY 하드코딩 기본값("ttbboyeong09010919001")은
        이식하지 말 것 — core.config.Settings.aladin_ttb_key로 대체
  - #6  에러는 (tag, error) 튜플로 반환
  - #7  core.debug_log.dbg/dbg_err + "[245]" 프리픽스 사용
"""

from __future__ import annotations


def build_245_family(item: dict, orig_title_hint: str = "", secrets: dict | None = None) -> dict:
    """
    245/246/900 MRK 문자열을 dict로 반환한다.
    예: {"245": "...", "246": "...", "900": "..."}
    (미구현 — 245/app.py의 build_245/build_246/build_900 이식 필요)
    """
    raise NotImplementedError(
        "245/app.py의 표제 계열 빌더(build_245/build_246/build_900)를 이식해야 합니다. "
        "docs/INTEGRATION_SURVEY.md의 245 섹션을 참고하세요."
    )
