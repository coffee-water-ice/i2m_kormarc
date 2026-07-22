"""
api/nlk_client.py
국립중앙도서관(NLK) 연동. 이름은 하나지만 서로 다른 두 용도가 공존한다.

fetch_nlk_orig_info() / fetch_nlk_responsibility_statement():
  원본: 245/245/nlk_opac.py 전체. 소장자료 검색 + MARC 뷰 파싱으로 원서명(246)·
  원저자명(500) 및 책임표시를 보강한다. 245/500/700/900 계열이 사용.

fetch_kdc_content_code_by_isbn():
  653(자유주제어)이 카테고리가 "기타"/"인문학" 캐치올로 떨어질 때만 분야 라우팅
  보조 신호로 쓰는 ISBN 부가기호(KDC 내용분류코드) 조회. 원본: 653/backend/app/
  nlk_client.py의 Seoji 조회(httpx 비동기판)를 requests 동기판으로 이식.
  기본은 비활성(core.config.Settings.nlk_enable_653=False, opt-in).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

NLK_OPAC_SEARCH_URL = "https://www.nl.go.kr/NL/search/openApi/search.do"
NLK_MARC_VIEW_URL   = "https://www.nl.go.kr/NL/search/marc_view.do"
_NLK_HEADERS        = {"User-Agent": "KORMARC-generator/1.0"}

# MARC 서브필드 구분자 (▼ 또는 $)
_SF = r"[▼\$]"

# 국중 표제/저자사항에 쓰이는 역할어 (책임표시 절)
_NLK_RESP_ROLE = (
    r"(?:지은이|저자|옮긴이|역자|그린이|엮은이|편저|감수|해설|원작|글|글쓴이|"
    r"공저|편집|사진|일러스트|편역|해제|구성|각색|감수자|낭독|번역)"
)
_NLK_RESP_BLOCK_RE = re.compile(
    rf"({_NLK_RESP_ROLE}\s*:[^<>;/]+(?:\s*;\s*{_NLK_RESP_ROLE}\s*:[^<>;/]+)*)",
    re.I,
)

# 246 19 원서명 패턴 (▼와 서브필드 코드 사이 공백 허용)
_MARC_246_RE = re.compile(
    rf"246\s+1\s*9\s+{_SF}\s*a\s*([^▼$\n\r]+)",
    re.I,
)

# 500 원저자명 패턴 (▼와 서브필드 코드 사이 공백 허용)
_MARC_500_AUTHOR_RE = re.compile(
    rf"500\s+[^\n]*?{_SF}\s*a\s*원저자명\s*:\s*([^▼$\n\r]+)",
    re.I,
)

# 폴백: ▼ 없이 "원저자명:" 레이블만으로 탐색 (AH1 표시 형식 대응)
_ORIG_AUTHOR_LABEL_RE = re.compile(
    r"원저자명\s*[：:]\s*([^\n\r<▼$]{3,100})",
    re.I,
)

# 폴백: 246 19 뒤에 바로 오는 라틴·확장라틴 문자 제목 (▼ 없는 경우)
_MARC_246_NODEL_RE = re.compile(
    r"246\s+1\s*9\s+([A-Za-zÀ-ɏª-ÿ][^▼$\n\r<>]{2,100})",
    re.I,
)


def extract_responsibility_from_catalog_text(text: str) -> str | None:
    """
    '표제 / 지은이: … ; 옮긴이: …' 또는 '지은이: … ; …' 에서 책임표시만 추출.
    """
    if not text or not text.strip():
        return None
    t = re.sub(r"\s+", " ", text.strip())
    if "/" in t:
        t = t.split("/")[-1].strip()
    m = _NLK_RESP_BLOCK_RE.search(t)
    if not m:
        return None
    out = re.sub(r"\s*;\s*", " ; ", m.group(1).strip())
    return re.sub(r"\s+", " ", out).strip() or None


def _parse_nlk_opac_xml(xml_text: str) -> str | None:
    """Open API XML 본문에서 책임표시 문자열 탐색."""
    if not xml_text or not xml_text.strip():
        return None

    candidates: list[str] = []
    try:
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            if elem.text and _NLK_RESP_BLOCK_RE.search(elem.text):
                candidates.append(elem.text.strip())
    except ET.ParseError:
        pass

    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml_text))
    m = _NLK_RESP_BLOCK_RE.search(plain)
    if m:
        candidates.append(m.group(1))

    for c in candidates:
        got = extract_responsibility_from_catalog_text(c)
        if got:
            return got
    return extract_responsibility_from_catalog_text(plain)


def _nlk_search_one(kwd: str, key: str) -> str | None:
    """NLK 검색 API kwd 검색 → 첫 번째 레코드 id 반환."""
    params = {"key": key, "kwd": kwd, "pageSize": 5, "pageNo": 1}
    try:
        resp = requests.get(
            NLK_OPAC_SEARCH_URL,
            params=params,
            timeout=12,
            headers=_NLK_HEADERS,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    if "INVALID KEY" in resp.text or "<error>" in resp.text[:500].lower():
        return None

    try:
        root = ET.fromstring(resp.text)
        id_elem = root.find(".//id")
        return id_elem.text.strip() if id_elem is not None and id_elem.text else None
    except ET.ParseError:
        return None


def _get_nlk_record_id(isbn13: str, key: str, title: str = "") -> str | None:
    """ISBN으로 국중 검색 → 없으면 제목으로 재검색."""
    record_id = _nlk_search_one(isbn13, key)
    if record_id:
        return record_id
    if title:
        record_id = _nlk_search_one(title.strip(), key)
    return record_id


def _fetch_nlk_marc_text(record_id: str) -> str | None:
    """MARC 뷰 페이지 텍스트 반환."""
    try:
        resp = requests.get(
            NLK_MARC_VIEW_URL,
            params={"viewKey": record_id, "viewType": "AH1"},
            timeout=12,
            headers=_NLK_HEADERS,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def _parse_marc_orig_info(marc_text: str) -> dict:
    """MARC 텍스트에서 246 19(원서명)·500 원저자명 추출."""
    result = {"orig_title": None, "orig_author": None}
    if not marc_text:
        return result

    text = marc_text
    text = re.sub(r"&#9660;|&#x25[Bb][Cc];", "▼", text)
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"&#?\w+;", " ", plain)
    plain = re.sub(r"([▼$])\s+([a-z0-9])\b", r"\1\2", plain)

    m246 = _MARC_246_RE.search(plain)
    if m246:
        t = m246.group(1).strip().rstrip(".,;: ")
        if t:
            result["orig_title"] = t

    m500 = _MARC_500_AUTHOR_RE.search(plain)
    if m500:
        a = m500.group(1).strip().rstrip(".,;")
        if a:
            result["orig_author"] = a

    if not result["orig_author"]:
        m = _ORIG_AUTHOR_LABEL_RE.search(plain)
        if m:
            a = m.group(1).strip().rstrip(".,;")
            if a:
                result["orig_author"] = a

    if not result["orig_title"]:
        m = _MARC_246_NODEL_RE.search(plain)
        if m:
            t = m.group(1).strip().rstrip(".,;")
            if t:
                result["orig_title"] = t

    _needs_latin = (
        not result["orig_author"]
        or not re.search(r"[A-Za-z]", result["orig_author"])
    )
    if _needs_latin:
        plain_oneline = re.sub(r"\s+", " ", plain)
        authors_found: list[str] = []
        for m in re.finditer(
            rf"[17]00\s+[^\n]{{0,50}}{_SF}\s*a\s*([A-Za-zÀ-ɏ][^▼$\n\r]{{3,80}})",
            plain_oneline, re.I,
        ):
            raw = m.group(1).strip().rstrip(".,; ")
            if not raw or re.search(r"[가-힣぀-ヿ一-鿿Ѐ-ӿ]", raw):
                continue
            if re.search(r"\b\d+\b", raw):
                continue
            if "," in raw:
                parts = [p.strip() for p in raw.split(",", 1)]
                if len(parts) == 2 and parts[1]:
                    authors_found.append(f"{parts[1]} {parts[0]}")
            elif len(raw.split()) >= 2:
                authors_found.append(raw)
        if authors_found:
            result["orig_author"] = ", ".join(authors_found)

    if not result.get("orig_author_cjk"):
        plain_oneline = re.sub(r"\s+", " ", plain)
        for m in re.finditer(
            rf"[17]00\s+[^\n]{{0,50}}{_SF}\s*a\s*([一-鿿぀-ヿ゠-ヿ㐀-䶿][^▼$\n\r]{{1,40}})",
            plain_oneline, re.I,
        ):
            raw = m.group(1).strip().rstrip(".,; ")
            if not raw or re.search(r"[가-힣]", raw):
                continue
            if re.search(r"[一-鿿぀-ヿ㐀-䶿]", raw):
                result["orig_author_cjk"] = re.sub(r"\s*,\s*", "", raw)
                break

    return result


def fetch_nlk_orig_info(isbn13: str, title: str = "", api_key: str = "") -> dict:
    """
    ISBN으로 국중 MARC 레코드를 조회해 원서명·원저자명 반환.
    ISBN으로 못 찾으면 title로 재검색.

    Args:
        api_key: 국립중앙도서관 OpenAPI 인증키 (core.config.Settings.nlk_cert_key).

    반환: {"orig_title": str|None, "orig_author": str|None}
    키가 없거나 조회 실패 시 두 값 모두 None.
    """
    empty = {"orig_title": None, "orig_author": None}
    key = (api_key or "").strip()
    if not key:
        return empty

    isbn = re.sub(r"[^0-9Xx]", "", (isbn13 or ""))
    if len(isbn) not in (10, 13):
        return empty

    record_id = _get_nlk_record_id(isbn, key, title=title)
    if not record_id:
        return empty

    marc_text = _fetch_nlk_marc_text(record_id)
    if not marc_text:
        return empty

    return _parse_marc_orig_info(marc_text)


def fetch_nlk_responsibility_statement(isbn13: str, api_key: str = "") -> str | None:
    """
    ISBN으로 국중 소장자료를 조회해 '지은이: … ; 옮긴이: …' 형태 문자열 반환.
    키가 없거나 조회 실패 시 None.
    """
    key = (api_key or "").strip()
    if not key:
        return None
    isbn = re.sub(r"[^0-9Xx]", "", (isbn13 or ""))
    if len(isbn) not in (10, 13):
        return None

    params = {"key": key, "kwd": isbn, "pageSize": 10, "pageNo": 1}
    try:
        resp = requests.get(
            NLK_OPAC_SEARCH_URL,
            params=params,
            timeout=12,
            headers=_NLK_HEADERS,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    if "INVALID KEY" in resp.text or "<error>" in resp.text[:500].lower():
        return None
    return _parse_nlk_opac_xml(resp.text)


_NLK_SEOJI_API_URL = "https://www.nl.go.kr/seoji/SearchApi.do"


def fetch_kdc_content_code_by_isbn(isbn: str, api_key: str) -> str:
    """
    Seoji API로 ISBN 부가기호(EA_ADD_CODE)를 조회해 마지막 3자리(내용분류코드)를 반환한다.

    653(자유주제어)이 알라딘 카테고리가 "기타"/"인문학" 캐치올로 떨어질 때만
    분야 라우팅 보조 신호로 사용 — 조회 실패·키 없음 시 빈 문자열(다른 필드에는 영향 없음).
    원본: 653/backend/app/nlk_client.fetch_kdc_content_code_by_isbn(httpx 비동기판)을
    requests 동기판으로 이식.
    """
    key = (api_key or "").strip()
    isbn13 = re.sub(r"[^0-9Xx]", "", (isbn or ""))
    if not key or len(isbn13) != 13:
        return ""

    params = {
        "cert_key": key,
        "result_style": "json",
        "page_no": 1,
        "page_size": 1,
        "isbn": isbn13,
    }
    try:
        resp = requests.get(_NLK_SEOJI_API_URL, params=params, timeout=12, headers=_NLK_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("docs") if isinstance(data, dict) else None
        if not isinstance(docs, list) or not docs or not isinstance(docs[0], dict):
            return ""
        doc = docs[0]
        ea_add_code = str(doc.get("EA_ADD_CODE") or "").strip()
        if len(ea_add_code) >= 5 and ea_add_code.isdigit():
            return ea_add_code[-3:]
        kdc = str(doc.get("KDC") or "").strip()
        if len(kdc) >= 3 and kdc[:3].isdigit():
            return kdc[:3]
        return ""
    except Exception:
        return ""
