"""
api/mois_client.py
행정안전부(MOIS) 출판사 조회 API 클라이언트.

원본: 260+300/api/external_apis.py의 get_mois_publisher_address().
과거 문체부(MCST) 웹크롤링을 대체한 공식 API 경로 (2026-07-08 정리 작업에서
문체부 크롤링 함수 get_mcst_address()는 죽은 코드로 확인되어 삭제됨 — 자세한
내역은 260+300/unnecessary/정리_기록_2026-07-08.md 참고).
"""

from __future__ import annotations

import requests


def get_mois_publisher_address(publisher_name: str, api_key: str) -> tuple[str | None, list[str]]:
    """
    행정안전부 출판사 조회 API로 출판사 주소를 검색한다.

    endpoint: https://apis.data.go.kr/1741000/publishers/info
    cond[SALS_STTS_CD::EQ]=01 로 영업/정상 업체만 필터링한다.

    Args:
        publisher_name: 검색할 출판사명
        api_key:        DATA_GO_KR 환경변수 값 (공공데이터포털 인증키)

    Returns:
        (도로명주소 또는 None, 디버그 메시지 목록)
    """
    debug: list[str] = []
    if not api_key:
        debug.append("[행안부] API 키(DATA_GO_KR) 없음")
        return None, debug
    if not publisher_name:
        debug.append("[행안부] 검색어 없음")
        return None, debug

    url = "https://apis.data.go.kr/1741000/publishers/info"
    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "10",
        "returnType": "json",
        "cond[SALS_STTS_CD::EQ]": "01",
        "cond[BPLC_NM::LIKE]": publisher_name,
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        body = (data.get("response") or {}).get("body") or {}
        raw_items = (body.get("items") or {}).get("item") or []
        # 단일 결과인 경우 dict로 반환될 수 있음
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not raw_items:
            debug.append(f"[행안부] 검색 결과 없음: {publisher_name}")
            return None, debug
        addr = raw_items[0].get("ROAD_NM_ADDR") or raw_items[0].get("LOTNO_ADDR") or ""
        if addr:
            debug.append(f"✅ 행안부 API 매칭 성공: {publisher_name} → {addr}")
            return addr, debug
        debug.append(f"[행안부] 주소 필드 없음: {publisher_name}")
        return None, debug
    except requests.exceptions.Timeout:
        debug.append("[행안부] 요청 시간 초과 (10s)")
        return None, debug
    except Exception as e:
        debug.append(f"[행안부] 예외: {e}")
        return None, debug
