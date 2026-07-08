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

import requests

# 041(번역서 판별)·245(700/710 저자정보)·653(목차/책소개)·260+300(기존)이
# 각자 필요로 하던 OptResult의 합집합.
OPT_RESULT_FULL = (
    "authors,subInfo,seriesInfo,Toc,fulldescription,"
    "ebookList,usedList,reviewList,fileFormatList,packing,subbarcode"
)


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

    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
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
            data = res.json()
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
            last_err = f"{key_name} 예외: {e}"
            continue

    return {}, last_err or f"알라딘 API 조회 실패: {isbn}"
