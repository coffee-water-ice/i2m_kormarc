"""
041(언어코드)/546(언어주기) 필드 생성 모듈 — STUB

원본: 041/041.py 의 LangFieldBuilder 클래스 (1976줄, docs/INTEGRATION_SURVEY.md 041 섹션 참고).
이식 대상: LangFieldBuilder.get_kormarc_tags(item, detail) -> (tag_041, tag_546, orig_title)

적용할 원칙 (docs/INTEGRATION_PRINCIPLES.md):
  - #3  OpenAI 클라이언트는 함수 인자로 주입 (원본이 이미 이 방식 — 그대로 유지)
  - #6  예외를 "성공 값 자리에 문자열로 섞어 반환"하는 원본의 안티패턴을 고쳐서
        (tag, error) 튜플 형태로 반환할 것
  - #7  디버그 로깅은 core.debug_log.dbg/dbg_err를 사용하고 "[041]" 프리픽스를 붙일 것
  - #9  이 모듈은 041/546 필드 생성에만 책임진다. 알라딘 저자 bio 크롤링(AladinAuthorScraper)은
        api/aladin_scraper.py로 분리한다 (041.py 원본은 크롤링을 이 모듈 안에서 직접 했음)

알려진 이슈 (docs/INTEGRATION_SURVEY.md 참고):
  - 041.py 원본 1780행 부근에 item.get("categoryText", "") 단독 호출 버그가 있다.
    실제 알라딘 API 필드명은 categoryName이므로, 이식 시
    item.get("categoryName") or item.get("categoryText", "") 로 수정해야 한다.
  - api/aladin_client.OPT_RESULT_FULL이 이미 subInfo/authors/fulldescription/Toc를
    요청하므로, 이 모듈은 별도 알라딘 재호출 없이 app.py가 넘겨주는 item을 그대로 쓴다.
"""

from __future__ import annotations


def build_041_546(item: dict, detail: dict, openai_client) -> tuple[str | None, str | None]:
    """041/546 MRK 문자열을 반환한다. (미구현 — 041.py의 LangFieldBuilder 이식 필요)"""
    raise NotImplementedError(
        "041.py의 LangFieldBuilder.get_kormarc_tags()를 이식해야 합니다. "
        "docs/INTEGRATION_SURVEY.md의 041 섹션을 참고하세요."
    )
