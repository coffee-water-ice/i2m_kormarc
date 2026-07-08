"""
api/aladin_scraper.py
알라딘 상품페이지·저자 프로필 HTML 크롤링 — STUB (041/245의 크롤링 로직이 옮겨올 자리).

원본 1: 041/041.py 의 AladinAuthorScraper 클래스 — 저자 bio 텍스트 크롤링
        (041의 언어 판별에 필요, 041.py:330~586).
원본 2: 245/245/app.py 의 scrape_aladin_product() — 원제/원저자 영문명/한자명/
        동아시아 여부 크롤링 (245.py:1406행 부근).

041/653처럼 크롤링이 필요 없는 필드는 api/aladin_client.get_aladin_item_by_isbn()만
호출하고, 245/300처럼 상세 페이지 크롤링이 필요한 필드만 이 모듈을 추가로 호출한다.
(참고: 300은 이미 core/fields/marc_300.py 안에 자체 크롤링 코드를 갖고 있다 —
골격 우선 원칙에 따라 재구조화하지 않고 원본 그대로 두었다. 041/245 이식 시에는
새로 작성하는 것이므로 처음부터 이 모듈을 쓰도록 구현할 것.)
"""

from __future__ import annotations


def scrape_author_bio(author_id: str) -> str:
    """알라딘 저자 프로필 페이지에서 bio 텍스트를 가져온다. (미구현 — 041.py AladinAuthorScraper 이식 필요)"""
    raise NotImplementedError(
        "041.py의 AladinAuthorScraper.scrape_author_bio_from_overview()를 이식해야 합니다."
    )


def scrape_product_page(item_id: str, orig_title_hint: str | None = None) -> dict:
    """알라딘 상품페이지에서 원제/원저자 영문명/한자명 등을 크롤링한다. (미구현 — 245/app.py scrape_aladin_product 이식 필요)"""
    raise NotImplementedError(
        "245/245/app.py의 scrape_aladin_product()를 이식해야 합니다."
    )
