"""
api/aladin_client.py
알라딘 Open API(ItemLookUp) 클라이언트 — ISBN → 도서 item dict 조회.

원본: 260+300/api/external_apis.py의 get_aladin_item_by_isbn().
통합 원칙(INTEGRATION_PRINCIPLES.md #1)에 따라 OptResult를 041/245/653/260+300
4개 폴더가 각자 필요로 하던 옵션의 합집합(OPT_RESULT_FULL)으로 고정했다.
260+300은 원래 subInfo/authors/Toc/fulldescription 없이 호출했으나, 041(언어코드
판별에 subInfo.authors 필요)·245(700/710에 subInfo.authors 필요)·653(Toc/fulldescription
필요)이 스텁에서 실제 로직으로 채워질 때 동일한 item 하나로 모든 필드를 생성할 수
있도록 미리 전체 옵션을 요청한다.
"""

from __future__ import annotations

import json
import re

import requests

# 041(번역서 판별)·245(700/710 저자정보)·653(목차/책소개)·260+300(기존)이
# 각자 필요로 하던 OptResult의 합집합.
OPT_RESULT_FULL = (
    "authors,subInfo,seriesInfo,Toc,fulldescription,"
    "ebookList,usedList,reviewList,fileFormatList,packing,subbarcode"
)

_TTBKEY_RE = re.compile(r"(ttbkey=)[^&\s]+", re.IGNORECASE)

# 알라딘이 종종 subBarcode 등 필드에 이스케이프 안 된 원문 제어문자(\r\n 등)를
# 그대로 흘려보내 json.loads가 "Invalid control character"로 실패하는 경우가 있다.
# 정상 파싱을 우선 시도하고, 실패할 때만 제어문자를 제거해 재시도한다.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]+")


def _parse_json_lenient(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_CONTROL_CHARS_RE.sub("", text))


def _redact(msg: str) -> str:
    """
    에러 메시지에 실패한 요청의 URL이 그대로 담기는 경우가 있다(예: requests의
    HTTPError는 str(e)에 요청 URL 전체를 포함한다). /api/convert 실패 응답이
    클라이언트에게 그대로 전달되므로, 여기 담긴 ttbkey 값을 마스킹해서 API 키가
    에러 메시지를 통해 외부로 유출되지 않도록 한다.
    """
    return _TTBKEY_RE.sub(r"\1***", msg)


def get_aladin_item_by_isbn(isbn: str, secrets: dict) -> tuple[dict, str | None]:
    """
    알라딘 OpenAPI에서 ISBN으로 도서 item 1건을 조회한다.
    ALADIN_TTB_KEY → ALADIN_TTB_KEY2 → ALADIN_TTB_KEY3 순으로 fallback.

    Returns:
        (item dict, error msg or None)
    """
    s = secrets or {}
    keys = [
        (name, s.get(name) or s.get(name.lower()) or "")
        for name in ("ALADIN_TTB_KEY", "ALADIN_TTB_KEY2", "ALADIN_TTB_KEY3")
    ]
    keys = [(name, k) for name, k in keys if k]

    if not keys:
        return {}, "ALADIN_TTB_KEY가 설정되지 않았습니다."

    # 알라딘 도메인 통합 공지(2026-08, "보안 정책 강화")에 따라 openapi.aladin.co.kr →
    # aladin.co.kr로 이전됐다. www 없는 이 도메인으로 직접 https 호출한다 — http://로
    # 부르면 301로 https://www.aladin.co.kr로 리다이렉트되는데, 그 첫 요청(ttbkey가
    # 쿼리스트링에 담김) 자체가 평문으로 나가는 구간이 생겨 안전하지 않다.
    url = "https://aladin.co.kr/ttb/api/ItemLookUp.aspx"
    base_params = {
        "itemIdType": "ISBN13",
        "ItemId": isbn,
        "output": "js",
        "Version": "20131101",
        "OptResult": OPT_RESULT_FULL,
        "Cover": "Big",
    }

    last_err: str = ""
    for key_name, key in keys:
        try:
            res = requests.get(url, params={"ttbkey": key, **base_params}, timeout=15)
            res.raise_for_status()
            data = _parse_json_lenient(res.text)
            # 알라딘 API 오류 응답 (한도 초과·키 오류 등) → 다음 키로
            if isinstance(data, dict) and data.get("errorCode"):
                last_err = (
                    f"{key_name} 오류 (code={data['errorCode']}): "
                    f"{data.get('errorMessage', '')}"
                )
                continue
            items = data.get("item", []) if isinstance(data, dict) else []
            if not items:
                return {}, f"알라딘 검색 결과 없음: {isbn}"
            return items[0], None
        except Exception as e:
            last_err = _redact(f"{key_name} 예외: {e}")
            continue

    return {}, last_err or f"알라딘 API 조회 실패: {isbn}"
