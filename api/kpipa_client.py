"""
api/kpipa_client.py
KPIPA(한국출판문화산업진흥원) 공식 OpenAPI 클라이언트.

원본: 260+300/api/external_apis.py의 get_kpipa_book_detail(), _extract_kpipa_publisher_name().
(참고: 653 폴더의 kpipa_client.py는 동일 엔드포인트에서 ONIX 목차(TextType 04)를
추출하는 파서를 갖고 있었다 — 653 필드를 스텁에서 실제 로직으로 채울 때
이 파일에 목차 추출 함수를 추가하면 된다.)
"""

from __future__ import annotations

import re

import requests

_APIKEY_RE = re.compile(r"(apiKey=)[^&\s]+", re.IGNORECASE)


def _redact(msg: str) -> str:
    """실패한 요청 URL이 그대로 담기는 에러 메시지(str(e))에서 KPIPA 키를 가린다."""
    return _APIKEY_RE.sub(r"\1***", msg)


def get_kpipa_book_detail(isbn: str, api_key: str) -> tuple[dict, str | None]:
    """
    KPIPA 공식 OpenAPI로 ISBN 도서 상세 정보를 조회한다.

    Args:
        isbn:    ISBN-13 문자열
        api_key: KPIPA 서비스키 (KPIPA_API_KEY 환경변수)

    Returns:
        (response_dict, error_msg or None)
        오류 시 response_dict = {}, error_msg = 설명 문자열
    """
    if not api_key:
        return {}, "KPIPA_API_KEY가 설정되지 않았습니다."

    url = "https://bnk.kpipa.or.kr/api/openApi/metaInfoSvc/getBookDetail"
    params = {"apiKey": api_key, "isbn": isbn}
    headers = {"Accept": "application/json"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=8)
        res.raise_for_status()
        data = res.json()
        return data, None
    except requests.exceptions.Timeout:
        return {}, "KPIPA API 요청 시간 초과 (8s)"
    except requests.exceptions.HTTPError as e:
        return {}, _redact(f"KPIPA API HTTP 오류: {e}")
    except Exception as e:
        return {}, _redact(f"KPIPA API 예외: {e}")


def extract_kpipa_publisher_name(data: dict) -> str | None:
    """
    KPIPA API 응답 dict에서 PublisherName 값을 추출한다.

    실제 응답 경로:
      response → body → items → Product → PublishingDetail → Publisher → PublisherName
    ImprintName은 PublisherName 부재 시 보조로 사용한다.

    NOTE: `or {}` 패턴을 사용해 값이 null인 키도 안전하게 처리한다.
    (.get("key", {}) 는 키가 없을 때만 {} 반환; 키가 있고 값이 None이면 None 반환)
    """
    if not data:
        return None

    try:
        response = data.get("response") or {}
        body     = response.get("body") or {}
        items    = body.get("items") or {}

        # 실제 응답에서 items가 리스트로 오는 경우 대응
        if isinstance(items, list):
            items = items[0] if items else {}

        product = items.get("Product") or {}

        # Product도 리스트로 오는 경우 대응
        if isinstance(product, list):
            product = product[0] if product else {}

        publishing_detail = product.get("PublishingDetail") or {}

        # Publisher와 Imprint도 실제 응답에서 리스트로 옴: [{...}]
        publisher = publishing_detail.get("Publisher") or {}
        if isinstance(publisher, list):
            publisher = publisher[0] if publisher else {}
        publisher_name = publisher.get("PublisherName") if isinstance(publisher, dict) else None
        if publisher_name:
            return str(publisher_name)

        imprint = publishing_detail.get("Imprint") or {}
        if isinstance(imprint, list):
            imprint = imprint[0] if imprint else {}
        imprint_name = imprint.get("ImprintName") if isinstance(imprint, dict) else None
        if imprint_name:
            return str(imprint_name)

    except (AttributeError, TypeError, IndexError, KeyError):
        pass

    return None
