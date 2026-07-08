"""
core/fields/marc_300.py
300(형태사항) 필드 생성 규칙 — 실제 동작(260+300 폴더에서 이관).

원본: 260+300/core/field_rules.py 의 300 섹션.
알라딘 상세 페이지 크롤링 + 네이버 책소개 보강 + OpenAI 삽화 판정을 거쳐 300 필드를 생성한다.

NOTE(레이어링 잔재): 원본 구조를 그대로 이관해 알라딘 상세 페이지 HTTP 요청을
이 파일이 직접 수행한다(api/aladin_client.py를 거치지 않음). 골격 우선 원칙에 따라
이번 이관에서는 재구조화하지 않고 그대로 옮겼다 — 추후 api/aladin_scraper.py로
크롤링 부분을 옮기는 리팩터링은 별도 작업으로 남겨둔다.
"""

from __future__ import annotations

import math
import re

import requests
from bs4 import BeautifulSoup
from pymarc import Field, Subfield

from core.debug_log import dbg, dbg_err


# 삽화 키워드 매핑 (KORMARC 용어 → 감지 키워드)
_ILLUS_KEYWORD_GROUPS: dict[str, list[str]] = {
    "천연색삽화": ["삽화", "일러스트", "일러스트레이션", "illustration", "그림"],
    "삽화":       ["흑백 삽화", "흑백 일러스트", "흑백 일러스트레이션", "흑백 그림"],
    "사진":       ["사진", "포토", "photo", "화보"],
    "도표":       ["도표", "차트", "그래프"],
    "지도":       ["지도", "지도책"],
}


def detect_illustrations(text: str) -> tuple[bool, str | None]:
    """
    텍스트에서 삽화 관련 키워드를 감지하여 KORMARC $b 값을 반환한다.

    Returns:
        (감지 여부, 삽화 레이블 문자열 또는 None)
        예: (True, "도표, 사진") / (False, None)
    """
    if not text:
        return False, None
    found = set()
    for label, keywords in _ILLUS_KEYWORD_GROUPS.items():
        if any(kw in text for kw in keywords):
            found.add(label)
    if found:
        return True, ", ".join(sorted(found))
    return False, None


def _norm_label(text: str) -> str:
    """레이블 텍스트에서 NBSP·줄바꿈 등 모든 공백을 일반 공백으로 정규화."""
    return re.sub(r"[\s 　]+", " ", text).strip()


def _find_section_text(soup: BeautifulSoup, label: str) -> str:
    """
    알라딘 상세 페이지에서 레이블(Ere_prod_mconts_LL/LS)이 일치하는
    Ere_prod_mconts_box 내의 Ere_prod_mconts_R 텍스트를 반환한다.
    공백 정규화(NBSP 포함)를 적용해 비교한다.
    """
    for box in soup.select("div.Ere_prod_mconts_box"):
        for lbl_el in box.select(".Ere_prod_mconts_LL, .Ere_prod_mconts_LS"):
            if _norm_label(lbl_el.get_text()) == label:
                content = box.select_one(".Ere_prod_mconts_R")
                if content:
                    return content.get_text(" ", strip=True)
    return ""


def _diagnose_boxes(soup: BeautifulSoup) -> list[dict]:
    """디버그: 모든 Ere_prod_mconts_box의 레이블을 수집해 반환."""
    result = []
    for box in soup.select("div.Ere_prod_mconts_box"):
        labels = [
            _norm_label(el.get_text())
            for el in box.select(".Ere_prod_mconts_LL, .Ere_prod_mconts_LS")
        ]
        result.append({"labels": list(dict.fromkeys(labels))})
    return result


def detect_illustrations_with_sources(
    title_text: str, subtitle_text: str, desc_text: str,
    toc_text: str, pub_desc_text: str = ""
) -> tuple[bool, str | None, list[dict]]:
    """
    소스별로 삽화 키워드를 검사해 KORMARC 레이블과 출처를 함께 반환한다.

    Returns:
        (감지 여부, 레이블 문자열, 상세 리스트)
        상세 리스트 예: [{"label": "사진", "keyword": "사진", "source": "책소개"}]
    """
    source_map = [
        ("제목",           title_text),
        ("부제",           subtitle_text),
        ("책소개",         desc_text),
        ("목차",           toc_text),
        ("출판사 제공 소개", pub_desc_text),
    ]
    found: dict[str, dict] = {}
    for label, keywords in _ILLUS_KEYWORD_GROUPS.items():
        for kw in keywords:
            for src_name, src_text in source_map:
                if src_text and kw in src_text:
                    found[label] = {"keyword": kw, "source": src_name}
                    break
            if label in found:
                break
    if found:
        label_str = ", ".join(sorted(found.keys()))
        detail = [{"label": k, **v} for k, v in found.items()]
        return True, label_str, detail
    return False, None, []


def _detect_illustrations_with_ai(
    title: str, desc: str, toc: str, openai_api_key: str,
    categories: list[str] | None = None,
) -> tuple[bool, str | None, list[dict]]:
    """
    OpenAI API로 카테고리·책소개·목차를 종합해 형태사항 $b를 판정한다.
    API 키 미설정·오류 시 (False, None, []) 반환.
    """
    if not openai_api_key:
        return False, None, []

    desc_trunc = (desc or "")[:1000]
    toc_trunc  = (toc  or "")[:500]
    cat_text   = "\n".join(categories) if categories else "(없음)"

    system_msg = (
        "당신은 KORMARC 300 필드 $b 판정 전문가입니다.\n"
        "도서의 카테고리·책소개·목차를 종합하여 해당 도서에 실제로 수록된 시각 자료 유형만 정확히 판정합니다.\n"
        "판정 결과는 반드시 JSON으로만 응답합니다."
    )
    user_msg = f"""아래 도서 정보를 바탕으로 KORMARC 300 $b 형태사항을 판정하세요.

[제목]
{title or "(없음)"}

[카테고리]
{cat_text}

[책소개]
{desc_trunc or "(없음)"}

[목차]
{toc_trunc or "(없음)"}

[판정 규칙]
1. 도서에 실제로 수록된 시각 자료만 포함합니다.
2. 비유·수사적 표현은 제외합니다. (예: "그림처럼", "지도를 그리듯", "사진을 찍듯")
3. 부정 표현이 있으면 제외합니다. (예: "삽화 없이", "그림 없는", "텍스트만으로")
4. 명확한 근거가 없으면 포함하지 않습니다.
5. 천연색삽화와 삽화는 중복 불가합니다.
   - 컬러·천연색임이 확인되면 → 천연색삽화
   - 색상 불명이거나 흑백이면 → 삽화

[선택 가능한 항목과 기준]
- 천연색삽화: 컬러/천연색 삽화, 일러스트, 그림이 실제 수록된 경우
- 삽화: 흑백 또는 색상 불명의 삽화, 일러스트가 실제 수록된 경우
- 사진: 실물 사진(흑백·컬러 무관)이 수록된 경우. 사진집·화보·포토에세이 포함
- 도표: 표, 차트, 그래프, 다이어그램이 수록된 경우
- 지도: 실제 지도가 수록된 경우 (약도·지형도 포함)
- 악보: 악보(오선보)가 수록된 경우

[응답 형식]
{{"items": ["해당 항목들"], "reason": "판정 근거 한 줄 요약"}}
항목이 없으면 "items": []"""

    try:
        import json as _json
        import openai
        client = openai.OpenAI(api_key=openai_api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=15,
        )
        data   = _json.loads(resp.choices[0].message.content)
        items  = [str(i) for i in data.get("items", []) if i]
        reason = data.get("reason", "")
        if not items:
            return False, None, []
        label_str = ", ".join(items)
        detail    = [{"label": i, "keyword": "(AI판정)", "source": f"AI: {reason}"} for i in items]
        dbg(f"[300] AI 판정 성공 → {label_str} ({reason})")
        return True, label_str, detail
    except Exception as e:
        dbg_err(f"[300] AI 판정 오류: {e}")
        return False, None, []


def _fetch_naver_description(isbn: str, client_id: str, client_secret: str) -> str:
    """네이버 책 검색 API(book_adv)로 책소개를 가져온다."""
    if not client_id or not client_secret or not isbn:
        return ""
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/book_adv.json",
            params={"d_isbn": isbn, "display": 1},
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=8,
        )
        if not r.ok:
            return ""
        items = r.json().get("items", [])
        if not items:
            return ""
        raw = items[0].get("description", "")
        return re.sub(r"<[^>]+>", "", raw).strip()
    except Exception:
        return ""


def _parse_aladin_categories(soup: BeautifulSoup) -> list[str]:
    """알라딘 상세 페이지의 conts_info_list2 블록에서 분류 경로 목록을 추출한다."""
    cat_div = soup.select_one("div.conts_info_list2")
    if not cat_div:
        return []
    results = []
    for li in cat_div.select("li"):
        text = li.get_text(" ", strip=True)
        # "보기" / "접기" 버튼 텍스트 제거
        text = re.sub(r"\s*(보기|접기)\s*$", "", text).strip()
        # 연속 공백·중복 꺾쇠 정리
        text = re.sub(r"\s{2,}", " ", text)
        if text:
            results.append(text)
    return results


def _parse_aladin_physical_info(
    html: str, api_description: str = "", naver_description: str = "", openai_api_key: str = ""
) -> dict:
    """
    알라딘 상세 페이지 HTML에서 형태사항(300 필드용) 데이터를 파싱한다.

    api_description: 알라딘 TTB API item["description"] — 책소개 섹션이 JS 렌더링으로만
                     존재할 때(정적 HTML에 없을 때) 대체 소스로 사용.

    Returns:
        {
            "300": MRK 문자열,
            "300_subfields": [Subfield, ...],
            "page_value": int | None,
            "size_value": str | None,
            "illustration_possibility": str,
        }
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── 5개 텍스트 소스 추출 ────────────────────────────────────
    title_el      = soup.select_one("span.Ere_bo_title")
    subtitle_el   = soup.select_one("span.Ere_sub1_title")
    title_text    = title_el.get_text(strip=True)    if title_el    else ""
    subtitle_text = subtitle_el.get_text(strip=True) if subtitle_el else ""

    # 책소개: 네이버 API → 알라딘 HTML → TTB API 순서로 fallback
    desc_text = naver_description or _find_section_text(soup, "책소개") or api_description

    # 출판사 제공 소개: 레이블이 책마다 다름 — 순서대로 시도
    pub_desc_text = ""
    for _pub_label in ("출판사 제공 책소개", "출판사 소개"):
        pub_desc_text = _find_section_text(soup, _pub_label)
        if pub_desc_text:
            break

    # 형태사항 블록 파싱
    a_part: str = ""
    b_part: str = ""
    c_part: str = ""
    page_value:  int | None = None
    size_value:  str | None = None

    form_wrap = soup.select_one("div.conts_info_list1")
    if form_wrap:
        for item in [s.strip() for s in form_wrap.stripped_strings if s.strip()]:
            # $a — 쪽수
            if re.search(r"(쪽|p)\s*$", item):
                m = re.search(r"\d+", item)
                if m:
                    page_value = int(m.group())
                    a_part = f"{m.group()} p."

            # $c — 크기 (mm 단위 → cm 변환)
            elif "mm" in item:
                m = re.search(r"(\d+)\s*[*x×X]\s*(\d+)", item)
                if m:
                    width  = int(m.group(1))
                    height = int(m.group(2))
                    size_value = f"{width}x{height}mm"
                    if width == height or width > height or width < height / 2:
                        c_part = f"{math.ceil(width/10)}x{math.ceil(height/10)} cm"
                    else:
                        c_part = f"{math.ceil(height/10)} cm"

    # 목차(TOC) 파싱: 레이블 "목차" 섹션 전체 텍스트 (Short+All 포함)
    toc_text = _find_section_text(soup, "목차")

    # 알라딘 카테고리 경로 추출
    aladin_categories = _parse_aladin_categories(soup)

    # $b — 삽화 감지: AI 판정 전용 (카테고리·책소개·목차 종합)
    has_illus, illus_label, illus_detail = _detect_illustrations_with_ai(
        title_text, desc_text, toc_text, openai_api_key, categories=aladin_categories
    )
    if has_illus:
        b_part = illus_label  # type: ignore[assignment]

    # ---- pymarc Subfield 리스트 구성 ----
    subfields_300: list[Subfield] = []
    if a_part:
        subfields_300.append(Subfield("a", a_part))
    if b_part:
        subfields_300.append(Subfield("b", b_part))
    if c_part:
        subfields_300.append(Subfield("c", c_part))

    # ---- MRK 텍스트 구성 (KORMARC 구두점 규칙 준수) ----
    mrk_parts: list[str] = []

    if a_part:
        chunk = f"$a{a_part}"
        if b_part:
            chunk += f" :$b{b_part}"
        mrk_parts.append(chunk)
    elif b_part:
        mrk_parts.append(f"$b{b_part}")

    if c_part:
        if mrk_parts:
            mrk_parts.append(f"; $c{c_part}")
        else:
            mrk_parts.append(f"$c{c_part}")

    # 아무 정보도 없으면 fallback
    if not mrk_parts:
        mrk_parts = ["$a1책."]
        subfields_300 = [Subfield("a", "1책.")]

    field_300 = "=300  \\\\" + " ".join(mrk_parts)

    return {
        "300": field_300,
        "300_subfields": subfields_300,
        "page_value": page_value,
        "size_value": size_value,
        "illustration_possibility": illus_label if illus_label else "없음",
        "toc_text": toc_text,
        "illus_diagnosis": {
            "sources": {
                "네이버 책소개":   naver_description,
                "제목":           title_text,
                "부제":           subtitle_text,
                "책소개":         desc_text,
                "목차":           toc_text,
                "출판사 제공 소개": pub_desc_text,
            },
            "알라딘 카테고리": aladin_categories,
            "detected": illus_detail,
            "_boxes": _diagnose_boxes(soup),
        },
    }


def _fetch_aladin_detail_page(
    link: str, api_description: str = "", naver_description: str = "", openai_api_key: str = ""
) -> tuple[dict, str | None]:
    """
    알라딘 상세 페이지를 HTTP로 가져와 형태사항 dict를 반환한다.

    api_description: TTB API로부터 미리 받은 책소개 — JS 렌더링 섹션 대체용.

    Returns:
        (결과 dict, 에러 메시지 또는 None)
    """
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        res = requests.get(link, headers=_HEADERS, timeout=15)
        res.raise_for_status()
        res.encoding = "utf-8"
        return _parse_aladin_physical_info(res.text, api_description, naver_description, openai_api_key), None
    except Exception as e:
        return {
            "300": "=300  \\\\$a1책. [상세 페이지 파싱 오류]",
            "300_subfields": [Subfield("a", "1책 [파싱 실패]")],
            "page_value": None,
            "size_value": None,
            "illustration_possibility": "정보 없음",
        }, f"Aladin 상세 페이지 크롤링 예외: {e}"


_EMPTY_DIAG = {"toc_text": "", "illus_diagnosis": {"sources": {}, "detected": []}}


def build_300_field(item: dict, isbn: str = "", secrets: dict | None = None) -> tuple[str, Field, dict]:
    """
    알라딘 item dict에서 알라딘 상세 페이지 링크를 꺼내 300 필드를 생성한다.

    Args:
        item:    알라딘 API item dict
        isbn:    ISBN-13 (네이버 API 호출용)
        secrets: 런타임 시크릿 dict (NAVER_SEARCH_KEY_ID/SECRET 포함)

    Returns:
        (mrk 문자열, pymarc.Field 객체, 진단 dict)
        진단 dict: {"toc_text": str, "illus_diagnosis": {"sources": {}, "detected": []}}
    """
    _FALLBACK_MRK    = "=300  \\\\$a1책."
    _FALLBACK_SF     = [Subfield("a", "1책.")]

    try:
        aladin_link     = (item or {}).get("link", "")
        api_description = (item or {}).get("description", "") or ""

        # 네이버 책소개 수집
        naver_description = ""
        openai_api_key = (secrets or {}).get("OPENAI_API_KEY", "")
        if isbn and secrets:
            naver_description = _fetch_naver_description(
                isbn,
                (secrets or {}).get("NAVER_SEARCH_KEY_ID", ""),
                (secrets or {}).get("NAVER_SEARCH_KEY_SECRET", ""),
            )
            if naver_description:
                dbg(f"[300] 네이버 책소개 수집됨 ({len(naver_description)}자)")
            else:
                dbg("[300] 네이버 책소개 없음 (미수록 또는 키 미설정)")

        if not aladin_link:
            dbg_err("[300] 알라딘 링크 없음 → 기본값 사용")
            return _FALLBACK_MRK, Field(
                tag="300", indicators=["\\", "\\"], subfields=_FALLBACK_SF
            ), _EMPTY_DIAG

        detail_result, err = _fetch_aladin_detail_page(
            aladin_link,
            api_description=api_description,
            naver_description=naver_description,
            openai_api_key=openai_api_key,
        )

        tag_300       = detail_result.get("300")           or _FALLBACK_MRK
        subfields_300 = detail_result.get("300_subfields") or _FALLBACK_SF
        toc_text      = detail_result.get("toc_text", "")
        illus_diag    = detail_result.get("illus_diagnosis", {"sources": {}, "detected": []})

        f_300 = Field(tag="300", indicators=[" ", " "], subfields=subfields_300)

        if err:
            dbg_err(f"[300] {err}")
        dbg(f"[300] {tag_300}")

        illus = detail_result.get("illustration_possibility")
        if illus and illus != "없음":
            dbg(f"[300] 삽화 감지됨 → {illus}")
        if toc_text:
            dbg(f"[300] 목차 추출됨 ({len(toc_text)}자)")

        return tag_300, f_300, {"toc_text": toc_text, "illus_diagnosis": illus_diag}

    except Exception as e:
        dbg_err(f"[300] 생성 중 예외: {e}")
        return (
            "=300  \\\\$a1책. [예외]",
            Field(tag="300", indicators=["\\", "\\"],
                  subfields=[Subfield("a", "1책. [예외]")]),
            _EMPTY_DIAG,
        )


def build_300_mrk(item: dict) -> str:
    """300 MRK 문자열만 필요한 경우의 편의 래퍼."""
    tag_300, _, _diag = build_300_field(item)
    return tag_300 or "=300  \\$a1책."
