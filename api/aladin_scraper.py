"""
api/aladin_scraper.py
알라딘 상품페이지·저자 프로필 HTML 크롤링 + GPT 기반 원서명/원저자명 웹 검색.

원본: 245/245/app.py 의 "알라딘 상품 페이지 크롤링" 섹션 전체(scrape_aladin_product 등)와
GPT Responses API(web_search_preview) 호출부(_gpt_orig_info_lookup).

041/653처럼 크롤링이 필요 없는 필드는 api/aladin_client.get_aladin_item_by_isbn()만
호출하고, 245처럼 원제/원저자 보강이 필요한 필드만 이 모듈을 추가로 호출한다.
GPT 웹 검색까지 "외부에서 원저 정보를 가져오는" 동일한 관심사로 묶어 이 모듈에 두었다
(marc_300.py는 반대로 AI 판정을 core/fields 안에 두었음 — 245는 스크래핑·NLK·GPT 세
경로가 collect_orig_info 하나로 강하게 얽혀 있어 이 쪽이 더 자연스러웠다. 원칙 P2 참고).
"""

from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from core.text_utils import (
    EAST_ASIA_KEYWORDS,
    TRANS_ROLES,
    _KO_AUTHOR_PAREN_SKIP,
    _normalize_jp_kanji,
    remove_year,
    to_title_case,
)

ALADIN_SEARCH_URL = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
ALADIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_INTRO_ROLE_ALIASES: dict[str, str] = {
    "지은이": "지은이", "저자": "지은이", "글": "지은이", "글쓴이": "지은이",
    "옮긴이": "옮긴이", "역자": "옮긴이", "번역": "옮긴이", "편역": "옮긴이",
    "그림": "그린이", "그린이": "그린이", "원작": "원작", "편저": "편저", "감수": "감수",
}

_INTRO_ENTRY_RE = re.compile(
    r"([가-힣][가-힣\s·ㆍ・]{0,42}[가-힣])\s*"
    r"(?:[（(][^)）]{1,52}[）)])?\s*"
    r"[（(]\s*(지은이|저자|글|글쓴이|옮긴이|역자|번역|편역|그림|그린이|원작|편저|감수)\s*[）)]",
)

_INTRO_KO_EN_ROLE_RE = re.compile(
    r"(.{2,80}?) \(([A-Za-z][A-Za-z0-9 ,.'\-]{1,120})\) \((지은이|저자|글|엮은이|그린이|원작|편저|감수)\)"
)

_NAME_PARTICLES = frozenset({
    "de", "di", "du", "da", "von", "van", "der", "den",
    "del", "della", "delle", "degli", "le", "la", "los", "las",
})


def is_org(name: str) -> bool:
    # core.text_utils.is_org와 동일 판정이 필요하지만 순환 참조를 피하기 위해
    # parse_intro_author_persons()에서만 쓰는 얇은 재선언 대신 core.text_utils를 직접 사용한다.
    from core.text_utils import is_org as _is_org
    return _is_org(name)


def _is_probable_orig_script(s: str) -> bool:
    """괄호 안 문자열이 일본·중국 원표기(한자·가나 등)로 보이면 True. 한글만·짧은 잡텍스트 제외."""
    t = (s or "").strip()
    if len(t) < 2:
        return False
    if re.fullmatch(r"[가-힣\s·・]+", t):
        return False
    return bool(re.search(r"[぀-ヿ一-鿿㐀-䶿]", t))


def _aladin_page_text_skip_global_nav(page_text: str) -> str:
    """전역 메뉴(일본도서·중국 도서 등)와 본문 분리 — 동아시아 키워드 오탐 방지."""
    for marker in ("저자 및 역자소개", "저자소개", "저자 프로필", "상품정보 요약", "책소개"):
        i = page_text.find(marker)
        if i != -1:
            return page_text[i : i + 100000]
    return page_text


def enrich_kanji_map_from_aladin_blob(blob: str, names: list[str], km: dict) -> None:
    """
    페이지/HTML에서 한글명 옆 원저 표기 보완.
    - 합저·저자소개: '한글명 (靑崎有吾) (지은이)', '한글명 (一穂ミチ) (지은이)' 등
    - 짧은 형식: '한글명（漢字）' 또는 '한글명 (漢字)'
    """
    if not blob:
        return
    script_in_paren = r"([一-鿿぀-ゟ゠-ヿー㐀-䶿·・\s]{2,56})"
    role_after = r"\s*[（(]\s*(?:지은이|저자|글(?:쓴이)?|원작)\s*[）)]"

    for nm in names:
        key = (nm or "").strip()
        if not key or km.get(key):
            continue
        m = re.search(
            re.escape(key) + r"\s*[（(]\s*" + script_in_paren + r"\s*[）)]" + role_after,
            blob,
            re.MULTILINE,
        )
        if m:
            script = re.sub(r"\s+", " ", m.group(1)).strip()
            if _is_probable_orig_script(script):
                km[key] = _normalize_jp_kanji(script)
                continue
        m2 = re.search(
            re.escape(key) + r"\s*[（(]\s*" + script_in_paren + r"\s*[）)]",
            blob,
            re.MULTILINE,
        )
        if m2:
            script = re.sub(r"\s+", " ", m2.group(1)).strip()
            if _is_probable_orig_script(script):
                km[key] = _normalize_jp_kanji(script)


def _aladin_author_overview_url_from_author_href(href: str) -> str | None:
    """상품 페이지의 저자 검색 링크에서 프로필(원문 표기) URL 생성."""
    h = (href or "").strip()
    if "AuthorSearch=" not in h:
        return None
    if "PublisherSearch" in h:
        return None
    if "wsearchresult.aspx" not in h.lower() and "wauthor_overview.aspx" not in h.lower():
        return None
    m = re.search(r"AuthorSearch=([^&\"']+)", h)
    if not m:
        return None
    return "https://www.aladin.co.kr/author/wauthor_overview.aspx?AuthorSearch=" + m.group(1)


def _parse_author_overview_name_cell(raw_html: str) -> str | None:
    """알라딘 저자 프로필(wauthor_overview) HTML에서 '이름:' 셀 텍스트."""
    t = html.unescape(raw_html)
    m = re.search(r"이름\s*:\s*</td>\s*<td[^>]*>\s*([^<]+)</td>", t)
    return m.group(1).strip() if m else None


def _ko_script_from_author_overview_cell(cell: str) -> tuple[str, str | None]:
    """'이치호 미치 (一穂ミチ)' → (이치호 미치, 一穂ミチ). 괄호 없으면 (cell, None)."""
    cell = re.sub(r"\s+", " ", (cell or "").strip())
    if "(" not in cell or ")" not in cell:
        return cell, None
    m = re.match(r"^(.+?)\s*\(\s*([^)]+)\s*\)\s*$", cell)
    if not m:
        return cell, None
    ko, script = m.group(1).strip(), m.group(2).strip()
    if not re.search(r"[가-힣]", ko):
        return cell, None
    if _is_probable_orig_script(script):
        return ko, script
    return ko, None


def _english_from_author_overview_cell(cell: str) -> tuple[str, str | None]:
    """
    '네일로 홉킨슨 (Nalo Hopkinson)', 'N. K. 제미신 (N. K. Jemisin)' 등
    괄호 안이 로마자만일 때 (앞 표기, 영문) 반환. 한자·가나 병기면 (outer, None).
    """
    cell = re.sub(r"\s+", " ", (cell or "").strip())
    if "(" not in cell or ")" not in cell:
        return cell, None
    m = re.match(r"^(.+?)\s*\(\s*([^)]+)\s*\)\s*$", cell)
    if not m:
        return cell, None
    outer, inner = m.group(1).strip(), m.group(2).strip()
    if not re.search(r"[A-Za-z]", inner):
        return outer, None
    if re.search(r"[가-힣぀-ヿ一-鿿㐀-䶿]", inner):
        return outer, None
    return outer, inner


def _is_paren_latin_roman_name(s: str) -> bool:
    """괄호 안이 로마자 표기의 사람 이름으로 보일 때(한글·한자·가나 없음)."""
    t = re.sub(r"\s+", " ", (s or "").strip())
    if len(t) < 2:
        return False
    if re.search(r"[가-힣぀-ヿ一-鿿㐀-䶿]", t):
        return False
    if t in _KO_AUTHOR_PAREN_SKIP:
        return False
    return bool(re.search(r"[A-Za-z]", t))


def _norm_author_display(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _author_overview_url_for_name(name: str, profile_urls: dict[str, str]) -> str | None:
    """상품 페이지 링크 텍스트와 parse_authors 이름이 공백만 다를 때도 매칭."""
    key = _norm_author_display(name)
    if not key:
        return None
    if key in profile_urls:
        return profile_urls[key]
    for k, u in profile_urls.items():
        if _norm_author_display(k) == key:
            return u
    return None


def _fetch_author_overview_name_cell(url: str) -> str | None:
    """저자 프로필 HTML에서 '이름:' 셀만 가져옴(재시도 1회)."""
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=ALADIN_HEADERS, timeout=8)
            resp.raise_for_status()
            return _parse_author_overview_name_cell(resp.text)
        except requests.RequestException:
            if attempt == 0:
                time.sleep(0.12)
    return None


def enrich_kanji_map_from_author_overview_pages(
    names: list[str],
    profile_urls: dict[str, str],
    km: dict,
    english_map: dict | None = None,
    max_workers: int = 6,
) -> None:
    """
    상품 페이지에 링크된 저자별 프로필(wauthor_overview)을 열어
    '이름: 한글 (원문표기)'에서 한자·가나 원표기를 채운다.
    english_map 이 있으면 같은 페이지의 '한글 (English)' 로마자 병기도 함께 채움.
    """
    tasks: list[tuple[str, str, bool, bool]] = []
    for nm in names:
        key = (nm or "").strip()
        if not key:
            continue
        need_k = not km.get(key)
        need_e = english_map is not None and not english_map.get(key)
        if not need_k and not need_e:
            continue
        url = _author_overview_url_for_name(key, profile_urls)
        if not url:
            continue
        tasks.append((key, url, need_k, need_e))

    if not tasks:
        return

    def _one(task: tuple[str, str, bool, bool]) -> tuple[str, str | None, bool, bool]:
        key, url, need_k, need_e = task
        return key, _fetch_author_overview_name_cell(url), need_k, need_e

    workers = min(max(1, len(tasks)), max_workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, t) for t in tasks]
        for fut in as_completed(futures):
            key, cell, need_k, need_e = fut.result()
            if not cell:
                continue
            ko, script = _ko_script_from_author_overview_cell(cell)
            if need_k and script and _norm_author_display(ko) == _norm_author_display(key):
                km[key] = _normalize_jp_kanji(script)
            outer_en, en_inner = _english_from_author_overview_cell(cell)
            if (
                english_map is not None
                and need_e
                and en_inner
                and _norm_author_display(outer_en) == _norm_author_display(key)
            ):
                english_map[key] = en_inner


def enrich_kanji_map_from_book_author_keyword(names: list[str], km: dict, aladin_ttb_key: str) -> None:
    """
    국내도서 키워드 검색으로 저자 문자열 속 '한글명 (원문표기)'을 찾아 한자명 보완.
    (합저 중 프로필 URL이 없거나 요청 실패한 인물 보강)
    """
    for nm in names:
        key = (nm or "").strip()
        if not key or km.get(key):
            continue
        params = {
            "ttbkey": aladin_ttb_key, "Query": key, "QueryType": "Keyword",
            "SearchTarget": "Book", "MaxResults": 12, "start": 1,
            "output": "js", "Version": "20131101",
        }
        try:
            resp = requests.get(ALADIN_SEARCH_URL, params=params, timeout=11)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.06)
            continue
        raw = data.get("item") or []
        items = [raw] if isinstance(raw, dict) else raw
        esc = re.escape(key)
        pat = re.compile(esc + r"\s*[（(]\s*([^)]+)\s*[）)]")
        for it in items[:12]:
            auth = html.unescape((it.get("author") or "").strip())
            if not auth or key not in auth:
                continue
            for m in pat.finditer(auth):
                inner = re.sub(r"\s+", " ", m.group(1)).strip()
                if inner in _KO_AUTHOR_PAREN_SKIP or not _is_probable_orig_script(inner):
                    continue
                km[key] = inner
                break
            if km.get(key):
                break
        time.sleep(0.08)


def enrich_english_map_from_book_author_keyword(names: list[str], em: dict, aladin_ttb_key: str) -> None:
    """
    국내도서 키워드 검색으로 '한글명 (English Name)'을 찾아 english_map 보완.
    (저자 프로필에 괄호 영문이 없는 합저 인물 보강)
    """
    for nm in names:
        key = (nm or "").strip()
        if not key or em.get(key):
            continue
        params = {
            "ttbkey": aladin_ttb_key, "Query": key, "QueryType": "Keyword",
            "SearchTarget": "Book", "MaxResults": 12, "start": 1,
            "output": "js", "Version": "20131101",
        }
        try:
            resp = requests.get(ALADIN_SEARCH_URL, params=params, timeout=11)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.06)
            continue
        raw = data.get("item") or []
        items = [raw] if isinstance(raw, dict) else raw
        esc = re.escape(key)
        pat = re.compile(esc + r"\s*[（(]\s*([^)]+)\s*[）)]")

        def scan_blob(blob: str) -> bool:
            b = html.unescape(blob or "")
            if key not in b:
                return False
            for m in pat.finditer(b):
                inner = re.sub(r"\s+", " ", m.group(1)).strip()
                if not _is_paren_latin_roman_name(inner):
                    continue
                em[key] = inner
                return True
            return False

        for it in items[:12]:
            for fld in ("author", "title", "description"):
                if scan_blob((it.get(fld) or "").strip()):
                    break
            else:
                continue
            break
        time.sleep(0.08)


def _merge_kanji_from_foreign_author_string(author_str: str, names: list[str], km: dict) -> None:
    """
    외국도서 검색 author 예:
    '무라카미 하루키, 안자이 미즈마루, 村上春樹 文  安西水丸 绘 (지은이)'
    앞쪽 한글 블록 순서와 뒤쪽 한자 덩어리(2자 이상) 순서를 맞춤.
    """
    s = (author_str or "").strip()
    if not s:
        return
    parts = [re.sub(r"\([^)]*\)\s*$", "", p).strip() for p in s.split(",")]
    ko_blocks: list[str] = []
    cjk_parts: list[str] = []
    hangul_only = re.compile(r"^[ 가-힣·・]+$")
    for p in parts:
        if not p:
            continue
        if hangul_only.match(p) and re.search(r"[가-힣]", p):
            ko_blocks.append(re.sub(r"\s+", " ", p.strip()))
        else:
            cjk_parts.append(p)
    blob = "".join(cjk_parts)
    clusters = re.findall(r"[一-鿿぀-ゟ゠-ヿ]{2,}", blob)
    if not clusters or not ko_blocks:
        return
    for i, ko in enumerate(ko_blocks):
        if i >= len(clusters):
            break
        if ko not in km and clusters[i]:
            km[ko] = _normalize_jp_kanji(clusters[i])


def enrich_kanji_map_from_foreign_title_search(
    orig_title: str | None, names: list[str], km: dict, aladin_ttb_key: str
) -> None:
    """동일 원제(가나·한자) 외국도서 ItemSearch 결과 author 필드로 한자명 보완."""
    if not orig_title or not names:
        return
    ot = orig_title.strip()
    if not re.search(r"[぀-ヿ一-鿿]", ot):
        return
    if not any(n and not km.get(n) for n in names):
        return
    params = {
        "ttbkey": aladin_ttb_key, "Query": ot, "QueryType": "Title",
        "SearchTarget": "Foreign", "MaxResults": 8, "start": 1,
        "output": "js", "Version": "20131101",
    }
    try:
        resp = requests.get(ALADIN_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return
    raw_items = data.get("item") or []
    items = [raw_items] if isinstance(raw_items, dict) else raw_items
    for it in items[:8]:
        auth = html.unescape((it.get("author") or "").strip())
        if not auth:
            continue
        _merge_kanji_from_foreign_author_string(auth, names, km)
        if not any(n and not km.get(n) for n in names):
            return


def _best_author_intro_container(soup: BeautifulSoup):
    """'저자 및 역자소개' 본문이 가장 많이 들어 있는 div."""
    best = None
    best_hits = 0
    for div in soup.find_all("div"):
        txt = div.get_text(" ", strip=True)
        if "소개" not in txt:
            continue
        if "저자" not in txt and "역자" not in txt and "지은이" not in txt:
            continue
        hits = (
            txt.count("(지은이)") + txt.count("(옮긴이)") + txt.count("(역자)")
            + txt.count("（지은이）") + txt.count("（옮긴이）")
        )
        if hits >= 2 and hits > best_hits:
            best_hits = hits
            best = div
    return best


def parse_intro_author_persons(soup: BeautifulSoup) -> list[dict]:
    """
    저자 및 역자소개 블록에서 '이름 (원문)? (역할)' 행을 순서대로 파싱.
    core.text_utils.parse_authors와 동일한 dict 형태: {"name","role","is_org"}
    """
    container = _best_author_intro_container(soup)
    if not container:
        return []
    raw = container.get_text("\n")
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if len(line) < 4:
            continue
        m = _INTRO_ENTRY_RE.search(line)
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(name) < 2:
            continue
        role_raw = m.group(2).strip()
        role = _INTRO_ROLE_ALIASES.get(role_raw, role_raw)
        dedup = (name, role)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append({"name": name, "role": role, "is_org": is_org(name)})
    return out


def parse_intro_author_english_pairs(soup: BeautifulSoup, page_text: str) -> list[dict]:
    """
    저자소개 등에서 '표기 (English) (지은이|엮은이|…)' 를 찾음.
    500 원저자명을 영문만 쓰기 위한 한글 표기 → 영문 매핑.
    """
    chunks: list[str] = []
    container = _best_author_intro_container(soup)
    if container:
        chunks.append(container.get_text("\n"))
    bio = _aladin_page_text_skip_global_nav(page_text)
    if bio and len(bio) > 80:
        chunks.append(bio)
    src = "\n".join(chunks)
    one = re.sub(r"\s+", " ", src.replace("\r", " ").replace("\n", " "))
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in _INTRO_KO_EN_ROLE_RE.finditer(one):
        ko = re.sub(r"\s+", " ", m.group(1).strip())
        en = re.sub(r"\s+", " ", m.group(2).strip())
        role_raw = m.group(3).strip()
        role = _INTRO_ROLE_ALIASES.get(role_raw, role_raw)
        if len(ko) < 2 or len(en) < 2:
            continue
        if not re.fullmatch(r"[A-Za-z0-9 ,.'\-\s]+", en):
            continue
        if not (re.search(r"[가-힣]", ko) or re.search(r"[A-Z]\.", ko)):
            continue
        key = (ko.lower(), en.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"ko": ko, "en": en, "role": role})
    return out


def _norm_author_lookup_key(n: str) -> str:
    return re.sub(r"\s+", " ", (n or "").strip()).lower()


def try_orig_names_500_from_intro_english_pairs(
    translation_book: bool,
    jp_ctx_for_500: bool,
    author_info: list[dict],
    pairs: list[dict],
) -> list[str] | None:
    """author_info 순서대로 영문 원저자명을 모두 찾으면 그 리스트만, 아니면 None."""
    if not translation_book or jp_ctx_for_500 or not author_info or not pairs:
        return None
    by_ko: dict[str, str] = {}
    for p in pairs:
        if p.get("role") in TRANS_ROLES:
            continue
        ko = _norm_author_lookup_key(p.get("ko", ""))
        en = (p.get("en") or "").strip()
        if ko and en:
            by_ko.setdefault(ko, en)
    out: list[str] = []
    for ai in author_info:
        nk = _norm_author_lookup_key(ai.get("name", ""))
        en = by_ko.get(nk)
        if not en:
            return None
        out.append(en)
    return out


def try_orig_names_500_from_profile_english(
    translation_book: bool,
    jp_ctx_for_500: bool,
    author_info: list[dict],
) -> list[str] | None:
    """
    저자 프로필 등으로 채운 english_name 으로 500용 리스트.
    전원 영문이면 영문만; 한 명만 비었을 때는 그 한 명만 한글 표기로 채운다.
    """
    if not translation_book or jp_ctx_for_500 or not author_info:
        return None
    out: list[str] = []
    miss: list[int] = []
    for i, ai in enumerate(author_info):
        en = (ai.get("english_name") or "").strip()
        if en:
            out.append(en)
        else:
            miss.append(i)
            out.append("")
    if not miss:
        return out
    if len(miss) != 1:
        return None
    i0 = miss[0]
    ko = (author_info[i0].get("name") or "").strip()
    if not ko:
        return None
    if len(author_info) == 1:
        return None
    out[i0] = ko
    return out


def _norm_searchword_token(tok: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (tok or "").lower())


def _searchword_drop_title_prefix(parts: list[str], title_hint: str | None) -> list[str]:
    """SearchWord 토큰 앞부분에서 알라딘 API 등으로 이미 아는 영문 원제 단어를 제거."""
    if not parts or not (title_hint or "").strip():
        return parts
    hint_toks: list[str] = []
    for w in re.split(r"[\s:/–—\-]+", title_hint):
        t = _norm_searchword_token(w)
        if t:
            hint_toks.append(t)
    if not hint_toks:
        return parts
    i, j = 0, 0
    while i < len(parts) and j < len(hint_toks):
        pt = _norm_searchword_token(parts[i])
        if not pt:
            i += 1
            continue
        if pt == hint_toks[j]:
            i += 1
            j += 1
        else:
            break
    return parts[i:]


def _merge_searchword_initials(parts: list[str]) -> list[str]:
    """N K Jemisin → N.K. Jemisin (SearchWord가 이니셜을 끊은 경우)."""
    out: list[str] = []
    i = 0
    while i < len(parts):
        letters = re.sub(r"[^A-Za-z]", "", parts[i])
        if letters.isupper() and len(letters) == 1:
            initials: list[str] = []
            j = i
            while j < len(parts):
                lj = re.sub(r"[^A-Za-z]", "", parts[j])
                if lj.isupper() and len(lj) == 1:
                    initials.append(lj)
                    j += 1
                else:
                    break
            if len(initials) >= 2:
                out.append(".".join(initials) + ".")
                i = j
                continue
        out.append(parts[i])
        i += 1
    return out


def _titleize_foreign_caps_token(tok: str) -> str:
    t = (tok or "").strip()
    if not t:
        return t
    if re.fullmatch(r"(?:[A-Z]\.){2,}", t.replace(" ", "")):
        return t if t.endswith(".") else t + "."
    core = re.sub(r"[^A-Za-z]", "", t)
    if core.isupper() and len(core) >= 2:
        if "-" in t or "'" in t:
            return to_title_case(t)
        return core[:1].upper() + core[1:].lower()
    if "-" in t or "'" in t:
        return to_title_case(t)
    return t


def _normalize_western_name_case(name: str) -> str:
    """전부 대문자인 서양 저자명을 적절한 대소문자로 변환.
    'ANTOINE DE SAINT-EXUPERY' → 'Antoine de Saint-Exupery'
    이미 혼합 케이스면 그대로 반환.
    """
    if not name:
        return name
    core = re.sub(r"[^A-Za-z]", "", name)
    if not core or not core.isupper():
        return name
    words = name.split()
    result = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in _NAME_PARTICLES:
            result.append(w.lower())
        else:
            result.append(to_title_case(w))
    return " ".join(result)


def _orig_author_en_from_searchword_parts(parts: list[str]) -> str | None:
    if not parts:
        return None
    bits = [_titleize_foreign_caps_token(p) for p in parts if p.strip()]
    bits = [b for b in bits if b]
    result = " ".join(bits).strip()
    if not result or not re.search(r"[A-Za-z]", result):
        return None
    return result


def scrape_aladin_product(item_id: str, orig_title_hint: str | None = None) -> dict:
    """
    알라딘 상품 페이지 크롤링.
    반환: {
        "orig_title": str|None,
        "orig_author_en": str|None,
        "kanji_map": dict,       # {"한글명": "漢字名"}
        "is_east_asian": bool,
        "text_blob": str,
        "author_overview_urls": dict[str, str],
        "intro_persons": list[dict],
        "intro_author_pairs": list[dict],
    }
    """
    result = {
        "orig_title":           None,
        "orig_author_en":       None,
        "kanji_map":            {},
        "is_east_asian":        False,
        "text_blob":            "",
        "author_overview_urls": {},
        "intro_persons":        [],
        "intro_author_pairs":   [],
    }

    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"
    try:
        resp = requests.get(url, headers=ALADIN_HEADERS, timeout=10, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            resp = requests.get(url, headers=ALADIN_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return result

    soup      = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text()

    profile_urls: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        overview = _aladin_author_overview_url_from_author_href(href)
        if not overview:
            continue
        nm = a.get_text(" ", strip=True)
        if nm and re.search(r"[가-힣]", nm):
            profile_urls[nm] = overview
    result["author_overview_urls"] = profile_urls

    # ── 원제/원저자 영문명 추출 ──────────────────────
    orig_link = soup.find("a", href=re.compile(r"SearchTarget=Foreign&SearchWord="))
    if orig_link:
        href = orig_link.get("href", "")
        m = re.search(r"SearchWord=([^&\"]+)", href)
        if m:
            raw   = unquote(m.group(1).replace("+", " ")).strip()
            parts = raw.split()
            hint  = (orig_title_hint or result.get("orig_title") or "").strip()
            if hint:
                rest = _searchword_drop_title_prefix(parts, hint)
                rest = _merge_searchword_initials(rest)
                if rest:
                    en = _orig_author_en_from_searchword_parts(rest)
                    if en:
                        result["orig_author_en"] = en
            else:
                merged = _merge_searchword_initials(parts)
                author_parts = [
                    p for p in merged
                    if re.sub(r"[-']", "", p).isupper()
                    and len(re.sub(r"[^A-Za-z]", "", p)) > 1
                ]
                title_parts = [p for p in merged if p not in author_parts]
                if title_parts:
                    result["orig_title"] = remove_year(" ".join(title_parts))
                if author_parts:
                    result["orig_author_en"] = _orig_author_en_from_searchword_parts(author_parts)

    if not result["orig_title"]:
        m = re.search(r"원제\s*[:：]\s*([^\n\r<(]+)", page_text)
        if m:
            candidate = remove_year(m.group(1).strip())
            if candidate and not re.search(r"[가-힣]", candidate):
                result["orig_title"] = candidate

    if not result["orig_author_en"]:
        intro_section = (
            soup.find("div", class_=re.compile(r"author", re.I))
            or soup.find("div", id=re.compile(r"author", re.I))
            or soup.find("div", class_=re.compile(r"Ere_prod_mcontents", re.I))
        )
        search_text = intro_section.get_text() if intro_section else page_text[:3000]
        for m in re.finditer(
            r"[가-힣][가-힣\s]+\(([A-Z][a-z]+(?:\s+[A-Za-z]+){1,})\)", search_text
        ):
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            words = candidate.split()
            if len(words) >= 2 and all(re.match(r"[A-Za-z\-\.\']", w) for w in words):
                result["orig_author_en"] = candidate
                break

    if not result["orig_author_en"]:
        intro_div = (
            soup.find("div", class_=re.compile(r"Ere_prod_mcontents", re.I))
            or soup.find("div", id=re.compile(r"authorIntro", re.I))
            or soup.find("div", class_=re.compile(r"author_info", re.I))
        )
        search_text = intro_div.get_text() if intro_div else page_text
        for m in re.finditer(
            r"[가-힣][가-힣\s]+\(([A-Z][a-z]+(?:\s+[A-Za-z]+){1,})\)", search_text
        ):
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            words = candidate.split()
            if len(words) >= 2 and all(re.match(r"[A-Za-z\-\.\']", w) for w in words):
                result["orig_author_en"] = candidate
                break

    CJK_PATTERN = re.compile(r"[一-鿿㐀-䶿぀-ゟ゠-ヿ]")
    for meta in soup.find_all("meta"):
        content   = meta.get("content", "") or meta.get("value", "")
        name_attr = (meta.get("name", "") + meta.get("property", "")).lower()
        if not content or "author" not in name_attr:
            continue
        if not result["orig_author_en"]:
            for p in content.split(","):
                p = p.strip()
                ws = p.split()
                if len(ws) >= 2 and all(re.match(r"^[A-Za-z.\-\']+$", w) for w in ws):
                    result["orig_author_en"] = p
                    break
        parts = [p.strip() for p in content.split(",")]
        used_cjk_idx: set[int] = set()
        for i, ko_name in enumerate(parts):
            if not (re.search(r"[가-힣]", ko_name) and not CJK_PATTERN.search(ko_name)):
                continue
            kn = ko_name.strip()
            for j in range(i + 1, min(i + 8, len(parts))):
                if j in used_cjk_idx:
                    continue
                cand = parts[j].strip()
                if (
                    CJK_PATTERN.search(cand)
                    and not re.search(r"[가-힣]", cand)
                    and len(cand) <= 36
                ):
                    if kn not in result["kanji_map"]:
                        result["kanji_map"][kn] = cand
                    used_cjk_idx.add(j)
                    break

    if not result["orig_author_en"]:
        from core.text_utils import extract_english_author_after_korean_paren
        hit = extract_english_author_after_korean_paren(page_text)
        if not hit:
            hit = extract_english_author_after_korean_paren(resp.text)
        if hit:
            result["orig_author_en"] = hit

    if result.get("orig_title") and result.get("orig_author_en"):
        t = result["orig_title"].strip()
        en = result["orig_author_en"].strip()
        if en and t.endswith(en):
            t = t[: -len(en)].rstrip(" -–—")
            if t:
                result["orig_title"] = remove_year(t)

    bio_slice = _aladin_page_text_skip_global_nav(page_text)
    if any(kw in bio_slice for kw in EAST_ASIA_KEYWORDS):
        result["is_east_asian"] = True

    result["text_blob"] = page_text + "\n" + resp.text[:150000]
    result["intro_persons"] = parse_intro_author_persons(soup)
    result["intro_author_pairs"] = parse_intro_author_english_pairs(soup, page_text)

    return result


# ============================================================
# GPT Responses API (web_search_preview) — 원서명·원저자명 검색
# ============================================================

_GPT_ORIG_SYSTEM_PROMPT = """\
번역서의 원서명과 원저자명을 웹 검색으로 확인해 JSON으로만 반환하라.

검색 전략 (아래는 출발점일 뿐이다 — 이 방식으로 안 잡히면 포기하지 말고 다른 경로도 자유롭게 시도하라):
- 저자 한자/원어 표기가 주어지면(예: 外山滋比古) 한국어 음역 대신 그 표기로 직접 검색하라.
  일본·중국 저자는 한자 표기 검색이 한국어 음역 검색보다 훨씬 정확하고 노이즈가 적다.
- 저자 실명 확인: 한자/원어 표기가 없으면 "[한국어 저자명 음역] 작가", "[한국어 저자명] author"로
  검색해 외국어 실명을 확인하라. 이건 어느 책인지와 무관하게 음역만으로 충분히 확인 가능한 경우가 많다.
- 원서명 확인: "[저자 실명/한자 표기] [한국어 제목]", "[저자 실명/한자 표기] bibliography"로 먼저
  검색해보라. 단, 한국어판 제목이 원제를 직역하지 않고 의역·재창작된 경우가 매우 흔하므로(예:
  부제만 다른 게 아니라 메인 제목 자체가 다른 경우), 이 방식으로 안 잡히면 다음도 시도하라:
  저자의 공식 사이트·출판사 신간 페이지·아마존/위키 저자 페이지에서 최신 저작 목록을 확인하거나,
  한국어판 출간을 알리는 기사·서평·블로그(원서명이 함께 언급되는 경우가 많음)를 검색하라.
  여러 후보가 있으면 한국어판 출판연도와 가까운 시기에 나온 원서를 우선 후보로 보라 — 번역서는
  보통 원서 출간 후 1~2년 내에 나오는 경우가 많다.
- 부제가 주어졌고 저자의 저작이 여러 권으로 검색돼 어느 책인지 헷갈릴 때만, 부제의 핵심 키워드를
  원어로 직접 번역해 검색어에 추가하라 (예: "월스트리트의 위험한 도박" → "Wall Street gamble").
- 동명의 한국어 번역서가 여러 권 있을 수 있으므로 저자 정보로 책을 특정하라.

규칙:
- **훈련 데이터 우선**: 원저자·원서명을 훈련 데이터에서 이미 확실히 알고 있다면 웹 검색 없이 바로
  답하라. 웹 검색 결과가 훈련 데이터와 충돌하거나 불확실하면 검색 결과를 무시하고 훈련 데이터에
  근거해 답하거나 null을 반환하라 — 검색 결과가 틀릴 수 있다.
- **책 소개의 비교 도서 무시**: 한국어판 책 소개에 "~같은", "~처럼" 형태로 다른 책 제목이 언급될 수
  있다. 이런 비교·추천 목적의 제목은 원서명이 아니다 — 절대 orig_title로 오인하지 마라.
- **책 소개에서 제목 합성 금지**: 한국어판 책 소개의 내용·키워드를 보고 그럴듯한 영어 제목을
  추론·합성·창작하지 마라. orig_title은 반드시 실제로 출판된 작품의 제목이어야 한다. 책 소개는
  검색 힌트로만 쓰고, 그 내용으로 제목을 만들어내는 것은 절대 금지.
- **같은 저자의 여러 책 구분**: 저자의 대표작이 먼저 떠올라도, 한국어판 제목·부제의 핵심 단어를
  영어로 직역해 저자의 전체 저작 목록과 대조하라. 예: 부제에 "엑시트(exit)"가 있으면 "exit"가
  포함된 제목을 찾고, 대표작의 부제 의미가 한국어판 부제와 현저히 다르면 대표작이라도 반환하지
  마라 — 같은 저자의 다른 책이 더 적합한지 반드시 확인하라.
- **한국어 제목의 음역어**: 한국어 제목에 외래어·인명 음역이 포함되면(예: "애니"→Annie,
  "매클린톡"→McClintock, "크리스마스"→Christmas), 그 음역어의 원어 철자를 복원해 원서 제목에
  그 단어가 **글자 그대로** 포함되는지 반드시 확인하라.
  중요: "의미상 유사한 다른 단어"로 대체된 제목은 오답이다("Last"≠"Annie", "Side"≠"Annie").
  훈련 데이터에서 음역어가 포함된 제목을 찾지 못했다면 반드시 orig_title = null을 반환하라
  (웹 검색이 더 정확한 결과를 가져올 수 있다).
  예: '애니가 남긴 것'의 저자가 Anna Quindlen이면 Quindlen의 저작 목록에서 'Annie'가
  포함된 제목을 찾아야 한다. 없으면 null → 웹 검색이 'After Annie' 같은 신간을 찾는다.
- 웹 검색으로 확인된 사실만. 불확실하면 해당 필드만 null (아래 독립 평가 규칙 참고).
- **orig_author와 orig_title은 독립적으로 평가하라.** 저자 실명은 한국어 음역만으로 확인 가능한 경우가
  많으므로, orig_title을 확정하지 못했다고 orig_author까지 null로 만들지 마라.
- orig_title은 같은 저자의 책이어야 한다.
- **부제 불일치만으로 null 반환 금지.** 부제는 "같은 저자가 쓴 여러 책 중 어느 책인지 헷갈릴 때"만
  쓰는 보조 단서다. 원서에 부제가 없는 경우, 또는 한국 출판사가 마케팅 목적으로 원서에 없는 부제를
  새로 붙인 경우가 매우 흔하므로, 단지 "부제가 원서와 직역으로 안 맞는다"는 이유만으로 orig_title을
  null로 만들지 마라. orig_title을 null로 반환해야 하는 경우는, 검색 결과 같은 저자의 다른 특정 책이
  한국어판 제목·부제·주제와 더 명백히 부합한다는 **적극적인 반증**을 찾았을 때뿐이다.
- orig_title: 원어 제목 그대로 (원문 언어 그대로, 한국어 번역 금지).
  원서가 일본어·중국어 등 한자/가나 문자 언어면 orig_title은 반드시 그 **원문 문자**(한자/가나,
  간체/번체 등)로 반환하라 — 로마자 표기(예: "Kouyatte, Kangaeru.")로 반환하는 것은 금지.
- orig_author_straight: 원저자명 이름 성 순서 (500 필드용, 예: Ivan Turgenev). 없으면 null.
- orig_author_inverted: 원저자명 성, 이름 순서 (700 필드용, 예: Turgenev, Ivan). 없으면 null.
- orig_author_kanji: 저자가 일본·중국 등 한자문화권 저자면, 저자명의 한자/가나 원표기
  (예: 栗山直子). orig_title을 찾을 때 본 검색 결과(아마존 재팬, 일본 위키 등)에 저자 한자명도
  같이 나오는 경우가 많으니 함께 확인하라. 서양 저자거나 못 찾으면 null.
- 한국어판 책 소개(주어지는 경우)에 원서 시리즈명·임프린트명(예: "Why I Write" 시리즈,
  특정 출판사 컬렉션명)이 언급되면 이를 검색어에 활용하라. 제목을 한국어 그대로 번역해
  검색해도 안 잡히는 경우, 시리즈/임프린트명이 결정적인 단서가 될 수 있다(특히 출간 직후라
  국내 매체에만 정보가 있고 해외 서지에는 아직 한국어판 언급이 없는 신간일 때 유용함).
- 역자·옮긴이는 제외하고 원저자만 포함.
- 공저자는 쉼표로 구분 (예: "Arkadii Strugatskii, Boris Strugatskii").
**최종 검증 — title·author 일치**: orig_title을 결정한 후, 그 제목이 orig_author가 실제로 쓴
작품인지 반드시 확인하라. 훈련 데이터에서 "그 제목의 저자 ≠ orig_author"임을 알고 있다면
orig_title = null을 반환하라. 예: orig_author가 Mark Haddon인데 찾은 제목이 Magic tree house라면,
Magic tree house는 Mary Pope Osborne의 작품이지 Mark Haddon의 작품이 아니므로 orig_title = null.
반환 형식: {"orig_title": "...", "orig_author_straight": "...", "orig_author_inverted": "...", "orig_author_kanji": "..."}
JSON 외 텍스트 절대 금지.\
"""


def _extract_source_urls(response) -> list[str]:
    """GPT Responses API의 web_search_preview 결과에서 실제 참고한 URL 목록을 뽑아냄."""
    urls: list[str] = []
    try:
        for item in (response.output or []):
            for block in (getattr(item, "content", None) or []):
                for ann in (getattr(block, "annotations", None) or []):
                    url = getattr(ann, "url", None)
                    if url and url not in urls:
                        urls.append(url)
    except Exception:
        pass
    return urls


def gpt_orig_info_lookup(
    openai_client,
    title: str,
    authors: list[dict],
    known_orig_author: str | None = None,
    known_orig_title: str | None = None,
    publisher: str | None = None,
    pub_year: str | None = None,
    subtitle: str | None = None,
    category: str | None = None,
    author_kanji: str | None = None,
    description_hint: str | None = None,
) -> dict:
    """
    GPT Responses API + web_search_preview로 원서명·원저자명 검색.

    Args:
        openai_client: 미리 생성된 openai.OpenAI 클라이언트 (INTEGRATION_PRINCIPLES.md #3).
                       원본은 함수 내부에서 timeout=60.0으로 직접 생성했으므로, 호출부에서
                       동일하게 넉넉한 timeout으로 생성한 클라이언트를 넘기는 것을 권장한다.
        known_orig_author: 이미 확인된 원저자 영문명 → GPT가 올바른 책을 찾도록 힌트.
        known_orig_title:  이미 확인된 원서명 → GPT가 올바른 원저자를 찾도록 힌트.
        publisher/pub_year: 한국어판 출판사·연도 → 동명이서 구별 힌트.
        subtitle: 한국어판 부제 — 같은 저자가 쓴 여러 책 중 어느 책인지 헷갈릴 때만 쓰는 보조 힌트.
        category: 알라딘 카테고리명(예: "경제경영") — 같은 저자의 다른 주제 책과 구별하는 추가 힌트.
        author_kanji: 저자 한자/원어 표기(예: 外山滋比古) — 한국어 음역보다 검색 정확도가 훨씬 높음.
        description_hint: 알라딘 책 소개 일부(텍스트만) — 원서 시리즈명 등 검색 단서가 섞여 있을 수 있음.

    반환: {"orig_title": str|None, "orig_author_en": str|None, "orig_author_kanji": str|None}
    """
    if openai_client is None:
        return {"orig_title": None, "orig_author_en": None, "orig_author_kanji": None}

    author_parts = []
    for a in authors:
        role = a.get("role", "")
        name = a.get("name", "")
        if name:
            author_parts.append(f"{name}({role})" if role else name)

    _primary_author_names = [
        a.get("name", "").strip()
        for a in authors
        if a.get("name") and a.get("role") not in TRANS_ROLES
    ]

    def _build_user_msg(hint_orig_title: str | None, hint_orig_author: str | None) -> str:
        msg = f"제목: {title}"
        if subtitle:
            msg += f"\n부제: {subtitle}"
        if category:
            msg += f"\n분야: {category}"
        if author_parts:
            msg += f"\n저자: {', '.join(author_parts)}"
        if author_kanji:
            msg += f"\n저자 한자/원어 표기: {author_kanji}"
        if publisher:
            msg += f"\n한국어판 출판사: {publisher}"
        if pub_year:
            msg += f"\n한국어판 출판연도: {pub_year}"
        if description_hint:
            msg += f"\n한국어판 책 소개: {description_hint}"
        _kt = hint_orig_title or known_orig_title
        _ka = hint_orig_author or known_orig_author
        if _kt:
            msg += f"\n원서명(이미 확인됨): {_kt}"
        if _ka:
            msg += f"\n원저자명(이미 확인됨): {_ka}"
        if _primary_author_names:
            names_str = ", ".join(f"'{n}'" for n in _primary_author_names)
            msg += (
                f"\n⚠️ 주의: 반환하는 orig_author는 반드시 위 지은이({names_str})와 동일 인물이어야 한다. "
                "웹 검색 결과에서 전혀 다른 저자가 나왔다면 잘못된 책을 찾은 것이다 — "
                "그 경우 orig_title과 orig_author 모두 null을 반환하라."
            )
        return msg

    def _one_attempt(msg: str, *, use_web_search: bool = True) -> dict:
        try:
            kwargs: dict = dict(
                model="gpt-4o",
                input=[
                    {"role": "system", "content": _GPT_ORIG_SYSTEM_PROMPT},
                    {"role": "user", "content": msg},
                ],
            )
            if use_web_search:
                kwargs["tools"] = [{"type": "web_search_preview"}]
            response = openai_client.responses.create(**kwargs)
            text = (response.output_text or "").strip()
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
            data = json.loads(text)
            orig_title        = (data.get("orig_title") or "").strip() or None
            orig_author_en    = (data.get("orig_author_straight") or "").strip() or None
            orig_author_kanji = (data.get("orig_author_kanji") or "").strip() or None
            return {"orig_title": orig_title, "orig_author_en": orig_author_en, "orig_author_kanji": orig_author_kanji}
        except Exception:
            return {"orig_title": None, "orig_author_en": None, "orig_author_kanji": None}

    # 1차: 웹 검색 없이 훈련 데이터만으로 시도 (웹 검색이 오히려 오답 유발하는 경우 방지)
    result = _one_attempt(_build_user_msg(None, None), use_web_search=False)

    if not result["orig_title"] and not result["orig_author_en"]:
        result = _one_attempt(_build_user_msg(None, None), use_web_search=True)

    if not result["orig_title"] and not result["orig_author_en"]:
        result = _one_attempt(_build_user_msg(None, None), use_web_search=True)
    elif result["orig_title"] and not result["orig_author_en"]:
        second = _one_attempt(_build_user_msg(result["orig_title"], None), use_web_search=True)
        if second["orig_author_en"]:
            result["orig_author_en"] = second["orig_author_en"]
        if second["orig_author_kanji"] and not result["orig_author_kanji"]:
            result["orig_author_kanji"] = second["orig_author_kanji"]
    elif not result["orig_title"] and result["orig_author_en"]:
        second = _one_attempt(_build_user_msg(None, result["orig_author_en"]), use_web_search=True)
        if second["orig_title"]:
            result["orig_title"] = second["orig_title"]
        if second["orig_author_kanji"] and not result["orig_author_kanji"]:
            result["orig_author_kanji"] = second["orig_author_kanji"]

    return result
