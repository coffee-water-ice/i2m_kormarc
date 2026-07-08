"""
api/publisher_db.py
Google Sheets 기반 "출판사 DB" 조회 + 발행지 통합 판단(build_pub_location_bundle).

원본: 260+300/api/external_apis.py 중 발행지/출판사 DB 관련 부분 전체.
알라딘/KPIPA/행안부 클라이언트는 각각 api/aladin_client.py, api/kpipa_client.py,
api/mois_client.py로 분리했고, 이 모듈은 그 결과들을 Google Sheets 출판사 DB와
결합해 최종 발행지를 판단하는 오케스트레이션(build_pub_location_bundle)을 담당한다.
"""

from __future__ import annotations

import re

import pandas as pd

from api.kpipa_client import get_kpipa_book_detail, extract_kpipa_publisher_name
from api.mois_client import get_mois_publisher_address

# 전역 캐시 변수 (매 요청마다 구글 시트를 다시 읽지 않도록 방지)
# isbn_prefix_dict: {isbn_prefix(str) → 발행지(str)} — iterrows 대신 O(1) dict 조회용
_PUBLISHER_DB_CACHE: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, tuple[str, str]]] | None = None


# ============================================================
# 정규화 유틸
# ============================================================

def normalize_publisher_name(name: str) -> str:
    """출판사명 표준화 (공백·법인격·괄호 제거, 소문자 변환)."""
    return re.sub(r"\s|\(.*?\)|주식회사|㈜|도서출판|주\)도서출판|출판사", "", name or "").lower()


def normalize_stage2(name: str) -> str:
    """2단계 정규화 — 시리즈성 접미어, 영문→한글 치환."""
    name = re.sub(
        r"(주니어|JUNIOR|어린이|키즈|북스|아이세움|프레스)", "", name, flags=re.IGNORECASE
    )
    eng_to_kor = {
        "springer": "스프링거",
        "cambridge": "케임브리지",
        "oxford": "옥스포드",
    }
    for eng, kor in eng_to_kor.items():
        name = re.sub(eng, kor, name, flags=re.IGNORECASE)
    return name.strip().lower()


def split_publisher_aliases(name: str) -> tuple[str, list[str]]:
    """
    "출판사명(별칭1/별칭2)" 형태에서 대표명·별칭 목록을 분리한다.

    Returns:
        (대표명, [별칭1, 별칭2, ...])
    """
    aliases: list[str] = []
    for content in re.findall(r"\((.*?)\)", name):
        aliases.extend(p.strip() for p in re.split(r"[,/]", content) if p.strip())
    name_no_brackets = re.sub(r"\(.*?\)", "", name).strip()
    if "/" in name_no_brackets:
        parts = [p.strip() for p in name_no_brackets.split("/") if p.strip()]
        return parts[0], aliases + parts[1:]
    return name_no_brackets, aliases


def normalize_publisher_location_for_display(location_name: str) -> str:
    """
    주소 문자열을 KORMARC 260 $a 표시용 지역명으로 변환한다.
    예: "서울특별시 마포구 …" → "서울"
    """
    if not location_name or location_name in ("출판지 미상", "예외 발생"):
        return location_name
    location_name = location_name.strip()
    major_cities = ["서울", "인천", "대전", "광주", "울산", "대구", "부산", "세종"]
    for city in major_cities:
        if city in location_name:
            return location_name[:2]
    parts = location_name.split()
    loc = parts[1] if len(parts) > 1 else parts[0]
    if loc.endswith("시"):
        loc = loc[:-1]
    return loc


# ============================================================
# Google Sheets 기반 출판사 DB
# ============================================================

def load_publisher_db(secrets: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Google Sheets '출판사 DB' 스프레드시트에서 네 가지 데이터프레임을 로드한다.

    Args:
        secrets: Streamlit secrets dict (또는 동등한 dict).
                 secrets["gspread"] 에 서비스 계정 JSON 키가 있어야 한다.

    Returns:
        (publisher_data, region_data, imprint_data, isbn_prefix_dict)
        - publisher_data:    columns=["출판사명", "주소"]
        - region_data:       columns=["발행국", "발행국 부호"]
        - imprint_data:      columns=["임프린트"]
        - isbn_prefix_dict:  {isbn_prefix → 발행지} — O(1) 조회용 dict
    """
    global _PUBLISHER_DB_CACHE
    if _PUBLISHER_DB_CACHE is not None:
        return _PUBLISHER_DB_CACHE

    import json
    import os

    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    env_creds = os.environ.get("GSPREAD_CREDENTIALS", "").strip()
    keyfile_dict = None

    if env_creds:
        # 1. 만약 전체가 따옴표로 감싸져 있다면 제거 (Render 등 배포 환경에서 흔히 발생)
        if (env_creds.startswith('"') and env_creds.endswith('"')) or \
           (env_creds.startswith("'") and env_creds.endswith("'")):
            env_creds = env_creds[1:-1]

        try:
            # 2. 표준 JSON 파싱 시도
            keyfile_dict = json.loads(env_creds)
        except json.JSONDecodeError:
            try:
                # 3. Invalid \escape 에러 대응: 실제 줄바꿈(\n)이 포함된 경우 \n 문자열로 치환하여 재시도
                fixed_creds = env_creds.replace('\n', '\\n')
                keyfile_dict = json.loads(fixed_creds)
            except Exception as e:
                raise ValueError(f"GSPREAD_CREDENTIALS JSON 형식이 올바르지 않습니다: {e}")
    else:
        keyfile_dict = secrets.get("gspread")

    if not keyfile_dict:
        raise ValueError("구글 시트 인증 정보(GSPREAD_CREDENTIALS)를 찾을 수 없습니다.")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        keyfile_dict,
        ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open("출판사 DB")

    pub_rows = sh.worksheet("발행처명–주소 연결표").get_all_values()[1:]
    publisher_data = pd.DataFrame(
        [row[1:3] for row in pub_rows], columns=["출판사명", "주소"]
    )

    region_rows = sh.worksheet("발행국명–발행국부호 연결표").get_all_values()[1:]
    region_data = pd.DataFrame(
        [row[:2] for row in region_rows], columns=["발행국", "발행국 부호"]
    )

    imprint_frames: list[str] = []
    for ws in sh.worksheets():
        if ws.title.startswith("발행처-임프린트 연결표"):
            imprint_frames.extend(row[0] for row in ws.get_all_values()[1:] if row)
    imprint_data = pd.DataFrame(imprint_frames, columns=["임프린트"])

    # "ISBN발행자번호-발행지 연결표" 시트 로드
    # 행 구조: [No, 발행자명, isbn_prefix_1, ..., isbn_prefix_9, 발행지]  (12열)
    # → col[0]=No, col[1]=발행자명, col[2..10]=ISBN 접두부, col[11]=발행지
    # dict {prefix: (발행지, 발행자명)} — 이중 발행처 비교를 위해 발행자명도 보존
    # 동일 접두부가 여러 발행지를 가질 경우 첫 번째 값 유지 (선입 우선)
    isbn_loc_rows = sh.worksheet("ISBN발행자번호-발행지 연결표").get_all_values()[1:]
    isbn_prefix_dict: dict[str, tuple[str, str]] = {}
    for row in isbn_loc_rows:
        if not row:
            continue
        location = row[-1].strip() if row else ""
        if not location:
            continue
        pub_name = row[1].strip() if len(row) > 1 else ""
        for cell in row[2:-1]:  # No(0)·발행자명(1) 제외, 발행지(-1) 제외
            prefix = re.sub(r"\D", "", str(cell))
            if 5 <= len(prefix) <= 13 and prefix not in isbn_prefix_dict:
                isbn_prefix_dict[prefix] = (location, pub_name)

    result = (publisher_data, region_data, imprint_data, isbn_prefix_dict)
    _PUBLISHER_DB_CACHE = result
    return _PUBLISHER_DB_CACHE


# ============================================================
# 출판사 위치 검색
# ============================================================

def search_location_by_isbn_prefix(
    isbn: str, isbn_prefix_dict: dict[str, tuple[str, str]]
) -> tuple[str, str, list[str]]:
    """
    'ISBN발행자번호-발행지 연결표' dict에서 ISBN 접두부 매칭으로 발행지와 발행자명을 찾는다.

    긴 접두부(더 구체적)부터 짧은 접두부 순으로 dict 키를 조회하므로
    최장 매칭이 우선된다. 검색 비용은 O(접두부 길이 범위) = O(9).

    Args:
        isbn:             13자리 ISBN (하이픈 포함/미포함 모두 처리)
        isbn_prefix_dict: {isbn_prefix → (발행지, 발행자명)}

    Returns:
        (발행지 또는 "출판지 미상", 발행자명 또는 "", 디버그 메시지 목록)
    """
    debug: list[str] = []
    isbn_clean = re.sub(r"\D", "", isbn or "")

    if len(isbn_clean) != 13:
        return "출판지 미상", "", [f"❌ ISBN 접두부 검색 불가: 13자리 아님 ({isbn_clean})"]

    if not isbn_prefix_dict:
        return "출판지 미상", "", ["❌ ISBN발행자번호-발행지 연결표가 비어 있음"]

    # 길이 13→5 순으로 줄여가며 dict 조회 — 첫 번째 히트가 최장 매칭
    for length in range(13, 4, -1):
        prefix = isbn_clean[:length]
        if prefix in isbn_prefix_dict:
            location, pub_name = isbn_prefix_dict[prefix]
            debug.append(f"✅ ISBN 접두부 매칭 성공: {prefix}… → {location} ({pub_name})")
            return location, pub_name, debug

    debug.append(f"❌ ISBN 접두부 매칭 실패: {isbn_clean}")
    return "출판지 미상", "", debug


def search_publisher_location_with_alias(
    name: str, publisher_data: pd.DataFrame
) -> tuple[str, list[str]]:
    """
    KPIPA DB(Google Sheets)에서 출판사명으로 주소를 찾는다.

    Returns:
        (주소 또는 "출판지 미상", 디버그 메시지 목록)
    """
    debug: list[str] = []
    if not name:
        return "출판지 미상", ["❌ 검색 실패: 입력된 출판사명이 없음"]
    norm = normalize_publisher_name(name)
    candidates = publisher_data[
        publisher_data["출판사명"].apply(normalize_publisher_name) == norm
    ]
    if not candidates.empty:
        addr = candidates.iloc[0]["주소"]
        debug.append(f"✅ KPIPA DB 매칭 성공: {name} → {addr}")
        return addr, debug
    debug.append(f"❌ KPIPA DB 매칭 실패: {name} (정규화 결과: {norm})")
    return "출판지 미상", debug


def get_country_code_by_region(region_name: str, region_data: pd.DataFrame) -> str:
    """
    지역명(발행지)으로 008 발행국 3자리 부호를 찾는다.
    매칭 실패 시 공백 3칸("   ") 반환.
    """
    def _norm(r: str) -> str:
        r = (r or "").strip()
        if r.startswith(("전라", "충청", "경상")):
            return r[0] + (r[2] if len(r) > 2 else "")
        return r[:2]

    try:
        norm_input = _norm(region_name)
        for _, row in region_data.iterrows():
            if _norm(row["발행국"]) == norm_input:
                return row["발행국 부호"].strip() or "   "
        return "   "
    except Exception:
        return "   "


# ============================================================
# 발행지 통합 번들 (260 생성에 직접 사용)
# ============================================================

def build_pub_location_bundle(isbn: str, publisher_name_raw: str, secrets: dict) -> dict:
    """
    5단계 체인으로 발행지를 조회하고 260/008 필드 생성에 필요한 정보를 dict로 반환한다.

    탐색 순서 (실패 시 다음 단계로):
      [1] ISBN 접두부 → ISBN발행자번호-발행지 연결표
      [2] KPIPA API 출판사명 → KPIPA DB
      [3] 알라딘 출판사명 → KPIPA DB
      [4] 알라딘 출판사명 → IMPRINT DB → KPIPA DB
      [5] 알라딘 출판사명 → IMPRINT DB → 행안부 API

    Args:
        isbn:               ISBN-13
        publisher_name_raw: 알라딘 API에서 받은 출판사명 원본 (steps 3-5 사용)
        secrets:            Google Sheets 인증용 secrets dict

    Returns:
        {
            "place_raw":          원본 주소 문자열,
            "place_display":      정규화된 표시용 지역명 (260 $a),
            "country_code":       008용 3자리 국가코드,
            "resolved_publisher": 검색에 실제 사용한 출판사명,
            "source":             데이터 출처 레이블,
            "debug":              디버그 메시지 목록,
        }
    """
    debug: list[str] = []
    _UNKNOWN = ("출판지 미상", "예외 발생", "미확인", "오류 발생", None)

    try:
        publisher_data, region_data, imprint_data, isbn_prefix_dict = load_publisher_db(secrets)
        debug.append("✓ 구글시트 DB 적재 성공")

        # 알라딘 출판사 대표명 분리 (이중 발행처 비교 기준 — 모든 경로에서 공통 사용)
        aladin_rep, _ = split_publisher_aliases(publisher_name_raw or "")
        aladin_rep = aladin_rep or (publisher_name_raw or "").strip()

        place_raw: str | None = None
        source = "FALLBACK"
        resolved = aladin_rep
        secondary_publisher = ""

        # [1] ISBN 접두부 → ISBN발행자번호-발행지 연결표
        place_raw, db_publisher, isbn_msgs = search_location_by_isbn_prefix(isbn, isbn_prefix_dict)
        debug += isbn_msgs
        if place_raw not in _UNKNOWN:
            source = "ISBN_PREFIX_DB"
            # DB 발행자명이 알라딘 출판사와 다르면 두 번째 발행처로 기록
            if db_publisher and normalize_publisher_name(db_publisher) != normalize_publisher_name(aladin_rep):
                secondary_publisher = db_publisher
                debug.append(f"→ 이중 발행처: 알라딘({aladin_rep}) ≠ DB({db_publisher})")

        # [2] KPIPA API 출판사명 → KPIPA DB
        if place_raw in _UNKNOWN:
            kpipa_api_key = (secrets or {}).get("KPIPA_API_KEY", "")
            kpipa_data, kpipa_err = get_kpipa_book_detail(isbn, kpipa_api_key)
            if kpipa_err:
                debug.append(f"KPIPA API 오류: {kpipa_err}")
            else:
                result_code = (
                    (kpipa_data.get("response") or {})
                    .get("result", {})
                    .get("resultCode", "?")
                )
                kpipa_pub = extract_kpipa_publisher_name(kpipa_data)
                if kpipa_pub:
                    debug.append(
                        f"✓ KPIPA API 성공 (resultCode={result_code}, 출판사: {kpipa_pub})"
                    )
                    place_raw, msgs = search_publisher_location_with_alias(kpipa_pub, publisher_data)
                    debug += msgs
                    if place_raw not in _UNKNOWN:
                        resolved = kpipa_pub
                        source = "KPIPA_API→DB"
                        if normalize_publisher_name(kpipa_pub) != normalize_publisher_name(aladin_rep):
                            secondary_publisher = kpipa_pub
                            debug.append(f"→ 이중 발행처: 알라딘({aladin_rep}) ≠ KPIPA({kpipa_pub})")
                else:
                    debug.append(
                        f"KPIPA API 응답 있음 (resultCode={result_code}) → PublisherName 없음"
                    )

        # [3] 알라딘 출판사명 → KPIPA DB
        if place_raw in _UNKNOWN:
            debug.append(f"[알라딘경로] 대표명: {aladin_rep}")
            place_raw, msgs = search_publisher_location_with_alias(aladin_rep, publisher_data)
            debug += msgs
            if place_raw not in _UNKNOWN:
                resolved = aladin_rep
                source = "ALADIN→DB"

        # [4] + [5]: IMPRINT DB 조회 (한 번만 수행 후 두 단계에서 재사용)
        if place_raw in _UNKNOWN:
            imprint_main: str | None = None
            norm_aladin = normalize_publisher_name(aladin_rep)
            for full_text in imprint_data["임프린트"]:
                if "/" in full_text:
                    pub_p, imp_p = [p.strip() for p in full_text.split("/", 1)]
                    if normalize_publisher_name(imp_p) == norm_aladin:
                        imprint_main = pub_p
                        debug.append(f"✅ IMPRINT 매칭: {aladin_rep} → {imprint_main}")
                        break
            if not imprint_main:
                debug.append(f"❌ IM DB 검색 실패: 매칭되는 임프린트 없음 ({aladin_rep})")

            # [4] IMPRINT → KPIPA DB
            if imprint_main:
                place_raw, msgs = search_publisher_location_with_alias(imprint_main, publisher_data)
                debug += msgs
                if place_raw not in _UNKNOWN:
                    resolved = aladin_rep
                    source = "ALADIN→IMPRINT→DB"
                    secondary_publisher = imprint_main  # 알라딘명이 임프린트, 모회사를 두 번째 발행처로

            # [5] IMPRINT → 행안부 API
            # imprint 매칭 성공 시 메인 출판사명으로, 실패 시 알라딘 대표명으로 검색
            if place_raw in _UNKNOWN:
                mois_target = imprint_main or aladin_rep
                mois_key = (secrets or {}).get("DATA_GO_KR", "")
                mois_addr, mois_debug = get_mois_publisher_address(mois_target, mois_key)
                debug += mois_debug
                if mois_addr:
                    place_raw = mois_addr
                    resolved = aladin_rep
                    source = "ALADIN→IMPRINT→MOIS"
                    if imprint_main:
                        secondary_publisher = imprint_main

        # 최종 fallback
        if not place_raw or place_raw in _UNKNOWN:
            place_raw, source = "출판지 미상", "FALLBACK"
            debug.append("⚠️ 모든 경로 실패 → '출판지 미상'")

        place_display = normalize_publisher_location_for_display(place_raw)
        country_code  = get_country_code_by_region(place_raw, region_data)

        return {
            "place_raw":           place_raw,
            "place_display":       place_display,
            "country_code":        country_code,
            "resolved_publisher":  resolved,
            "secondary_publisher": secondary_publisher,
            "source":              source,
            "debug":               debug,
        }

    except Exception as e:
        return {
            "place_raw":           "발행지 미상",
            "place_display":       "발행지 미상",
            "country_code":        "   ",
            "resolved_publisher":  publisher_name_raw or "",
            "secondary_publisher": "",
            "source":              "ERROR",
            "debug":               [f"예외: {e}"],
        }
