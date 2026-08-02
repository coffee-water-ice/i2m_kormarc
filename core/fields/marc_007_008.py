"""
core/fields/marc_007_008.py
KORMARC 007(형태자료 부호)·008(부호화정보) 필드 생성 모듈.

원본: 2025년 코드/1215_main.py(단일 파일, 5284줄)의
  - MarcBuilder.add_ctl / build_008_kormarc_bk / build_008_from_isbn (007/008 조립)
  - detect_illus4 / detect_index / detect_lit_form / detect_bio (008 위치별 키워드 감지)
  - generate_all_oneclick() 안의 007/008 조립 호출부(041/260 이후, 020/056/300/653 이전)

GPT 호출이 전혀 없는 순수 규칙 기반 필드다.

이식 시 적용한 원칙(docs/INTEGRATION_PRINCIPLES.md):
  - #7  core.debug_log.dbg를 "[008]" 프리픽스로 사용.
  - #8  최신 타입힌트(`str | None`) 스타일.
  - #9  이 모듈은 007/008 생성에만 책임진다. 041의 언어코드($a)는
        core.fields.marc_041.LangFieldBuilder.lang3_from_tag041()을 그대로 재사용하고,
        260의 발행국 코드는 api.publisher_db.build_pub_location_bundle()이 반환하는
        country_code를 그대로 재사용한다 — 둘 다 새로 계산하지 않는다.

원본과 의도적으로 다르게 이식한 부분:
  - 원본은 country3 결정에 두 경로가 있었다: ① build_pub_location_bundle()가 반환하는
    country_code(Google Sheets "발행국명–발행국부호 연결표" 기반, i2m_kormarc에도 이미
    api/publisher_db.get_country_code_by_region()로 이식되어 있음) ② 원본 파일 안에만
    있던 하드코딩 17개 지역 dict(KR_REGION_TO_CODE)로 300 발행지 문자열을 재매칭하는
    폴백. 그런데 원본의 실제 호출부(generate_all_oneclick)는 override_country3에
    bundle["country_code"]를 항상 넘겼고, 그 값은 실패해도 공백 3칸("   ")이라
    파이썬 진리값이 True다 — 즉 ②의 하드코딩 dict 폴백은 실제 파이프라인에서 한 번도
    실행되지 않는 죽은 코드였다. 실제로 동작하던 경로(①)만 이식했다.
"""

from __future__ import annotations

import re
from datetime import datetime

from core.debug_log import dbg

# ═══════════════════════════════════════════════════════════════
# 1. 007 — 형태자료 부호
# ═══════════════════════════════════════════════════════════════

def build_007_field() -> str:
    """
    원본은 조건 분기 없이 모든 도서에 "007  ta"를 고정 출력한다
    (t=문자자료, a=일반 인쇄자료 — 전자책·영상자료 등은 애초에 고려 대상이 아니었음).
    """
    return "=007  ta"


# ═══════════════════════════════════════════════════════════════
# 2. 008 — 부호화정보(40자) 조립
# ═══════════════════════════════════════════════════════════════

def _extract_year_from_pubdate(pubdate: str) -> str:
    """알라딘 pubDate에서 4자리 발행년도 추출. 못 찾으면 '19uu'(연대 불명)."""
    m = re.search(r"(19|20)\d{2}", pubdate or "")
    return m.group(0) if m else "19uu"


def _detect_illus4(text: str) -> str:
    """18-21 삽화 부호. a=삽화/일러스트, d=도표/차트/그래프, o=사진/화보 (최대 4자)."""
    keys: list[str] = []
    if re.search(r"삽화|삽도|도해|일러스트|일러스트레이션|그림|illustration", text, re.I):
        keys.append("a")
    if re.search(r"도표|표|차트|그래프|chart|graph", text, re.I):
        keys.append("d")
    if re.search(r"사진|포토|화보|photo|photograph|컬러사진|칼라사진", text, re.I):
        keys.append("o")
    out: list[str] = []
    for k in keys:
        if k not in out:
            out.append(k)
    return "".join(out)[:4]


def _detect_index(text: str) -> str:
    """31 색인 유무. 있으면 '1', 없으면 '0'."""
    return "1" if re.search(r"색인|찾아보기|인명색인|사항색인|index", text, re.I) else "0"


def _detect_lit_form(title: str, category: str, extra_text: str = "") -> str:
    """33 문학형식. i=서간문학 m=기행/일기/수기 p=시 f=소설 e=수필, 해당 없으면 공백."""
    blob = f"{title} {category} {extra_text}"
    if re.search(r"서간집|편지|서간문|letters?", blob, re.I):
        return "i"
    if re.search(r"기행|여행기|여행 에세이|일기|수기|diary|travel", blob, re.I):
        return "m"
    if re.search(r"시집|산문시|poem|poetry", blob, re.I):
        return "p"
    if re.search(r"소설|장편|중단편|novel|fiction", blob, re.I):
        return "f"
    if re.search(r"에세이|수필|essay", blob, re.I):
        return "e"
    return " "


def _detect_bio(text: str) -> str:
    """34 전기 여부. a=자서전 b=전기/평전 d=전기적/자전적/회고, 해당 없으면 공백."""
    if re.search(r"자서전|회고록|autobiograph", text, re.I):
        return "a"
    if re.search(r"전기|평전|인물 평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고|회상", text):
        return "d"
    return " "


def _build_008_body(
    date_entered: str,       # 00-05 YYMMDD
    date1: str,               # 07-10 4자리(예: '2025' / '19uu')
    country3: str,             # 15-17 3자리
    lang3: str,                 # 35-37 3자리
    date2: str = "",              # 11-14
    illus4: str = "",              # 18-21 최대 4자
    has_index: str = "0",           # 31 '0' 없음 / '1' 있음
    lit_form: str = " ",             # 33
    bio: str = " ",                   # 34
    type_of_date: str = "s",           # 06
    modified_record: str = " ",         # 28
    cataloging_src: str = "a",           # 32
) -> str:
    """008 본문(40자) 조립 — 단행본 기준(type_of_date 기본 's')."""

    def pad(s, n, fill=" "):
        s = "" if s is None else str(s)
        return (s[:n] + fill * n)[:n]

    if len(date_entered) != 6 or not date_entered.isdigit():
        raise ValueError("date_entered는 YYMMDD 6자리 숫자여야 합니다.")
    if len(date1) != 4:
        raise ValueError("date1은 4자리여야 합니다. 예: '2025', '19uu'")

    body = "".join([
        date_entered,                                   # 00-05
        pad(type_of_date, 1),                            # 06
        date1,                                            # 07-10
        pad(date2, 4),                                     # 11-14
        pad(country3, 3),                                  # 15-17
        pad(illus4, 4),                                    # 18-21
        " " * 4,                                           # 22-25 (이용대상/자료형태/내용형식) 공백
        " " * 2,                                           # 26-27 공백
        pad(modified_record, 1),                           # 28
        "0",                                               # 29 회의간행물
        "0",                                               # 30 기념논문집
        has_index if has_index in ("0", "1") else "0",     # 31 색인
        pad(cataloging_src, 1),                            # 32 목록 전거
        pad(lit_form, 1),                                  # 33 문학형식
        pad(bio, 1),                                       # 34 전기
        pad(lang3, 3),                                     # 35-37 언어
        " " * 2,                                           # 38-39 공백
    ])
    if len(body) != 40:
        raise AssertionError(f"008 length != 40: {len(body)}")
    return body


def build_008_field(
    item: dict,
    *,
    country_code: str,
    lang3: str | None = None,
) -> str:
    """
    008 MRK 문자열("=008  <40자>")을 반환한다.

    Args:
        item: 알라딘 API item dict — title/pubDate/categoryName/description과
              subInfo.toc를 041/653과 동일하게 그대로 읽는다(재조회 없음).
        country_code: api.publisher_db.build_pub_location_bundle()의 country_code를
                      그대로 전달(041/260 이후에만 호출 가능 — app.py 호출 순서 참고).
        lang3: core.fields.marc_041.LangFieldBuilder.lang3_from_tag041(tag_041)의
               결과. 041이 미확정(None)이면 기본값 'kor'를 쓴다(원본과 동일).
    """
    today = datetime.now().strftime("%y%m%d")
    date1 = _extract_year_from_pubdate((item or {}).get("pubDate", "") or "")

    country3 = country_code or "   "
    lang3_final = lang3 or "kor"

    title = (item or {}).get("title", "") or ""
    category = (item or {}).get("categoryName", "") or ""
    desc = (item or {}).get("description", "") or ""
    toc = ((item or {}).get("subInfo", {}) or {}).get("toc", "") or ""
    bigtext = " ".join([title, desc, toc])

    illus4 = _detect_illus4(bigtext)
    has_index = _detect_index(bigtext)
    lit_form = _detect_lit_form(title, category, bigtext)
    bio = _detect_bio(bigtext)

    dbg(
        "[008]", f"date1={date1}", f"country3={country3!r}", f"lang3={lang3_final}",
        f"illus4={illus4!r}", f"index={has_index}", f"lit_form={lit_form!r}", f"bio={bio!r}",
    )

    body = _build_008_body(
        date_entered=today,
        date1=date1,
        country3=country3,
        lang3=lang3_final,
        illus4=illus4,
        has_index=has_index,
        lit_form=lit_form,
        bio=bio,
    )
    return f"=008  {body}"
