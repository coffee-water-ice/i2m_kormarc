"""
api/kpipa_client.py
KPIPA(한국출판문화산업진흥원) 공식 OpenAPI 클라이언트.

원본: 260+300/api/external_apis.py의 get_kpipa_book_detail(), _extract_kpipa_publisher_name().
653 필드용 ONIX 목차(TextType 04) 추출은 653/backend/app/kpipa_client.py에서
이식(extract_kpipa_toc_only) — 동일 엔드포인트 응답을 재사용해 별도 호출 없이
목차만 뽑아낸다. 기본은 비활성(core.config.Settings.kpipa_enable_653=False)이며
원본도 opt-in 기능이었다.
"""

from __future__ import annotations

import re
from typing import Any

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


def _extract_kpipa_book_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    """getBookDetail ONIX JSON에서 Product 1건 dict 추출(response.body.items.Product)."""
    if not isinstance(raw, dict):
        return None
    resp = raw.get("response")
    if not isinstance(resp, dict):
        return None
    body = resp.get("body")
    if not isinstance(body, dict):
        return None
    items = body.get("items")
    if not isinstance(items, dict):
        return None
    prod = items.get("Product")
    if isinstance(prod, list):
        return next((p for p in prod if isinstance(p, dict)), None)
    if isinstance(prod, dict):
        return prod
    return None


def _strip_html_simple(text: str) -> str:
    if "<" not in (text or ""):
        return text or ""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", text or "")


def extract_kpipa_toc_only(raw: dict[str, Any]) -> str:
    """
    KPIPA ONIX Product에서 목차(CollateralDetail.TextContent, TextType=04)만 추출한다.
    653(자유주제어) 필드가 알라딘 목차 보강용으로 사용 — 다른 필드는 사용하지 않는다.
    """
    product = _extract_kpipa_book_payload(raw)
    if not product:
        return ""
    cd = product.get("CollateralDetail")
    if not isinstance(cd, dict):
        return ""
    blocks = cd.get("TextContent")
    if not isinstance(blocks, list):
        return ""
    plain: list[str] = []
    fallback: list[str] = []
    for b in blocks:
        if not isinstance(b, dict) or str(b.get("TextType")) != "04":
            continue
        aud = b.get("ContentAudience")
        aud0 = str(aud[0]) if isinstance(aud, list) and aud else ""
        texts = b.get("Text")
        if isinstance(texts, str):
            text_list = [texts]
        elif isinstance(texts, list):
            text_list = texts
        else:
            text_list = []
        merged = "\n".join(t.strip() for t in text_list if isinstance(t, str) and t.strip())
        if not merged:
            continue
        cleaned = _strip_html_simple(merged)
        (plain if aud0 == "02" else fallback).append(cleaned)
    if plain:
        return max(plain, key=len)
    if fallback:
        return max(fallback, key=len)
    return ""
