"""
core/fields/marc_245.py
245(표제/책임표시)·246(원서명)·940(제목 한글 읽기 색인) 필드 생성 + 원제/원저자 수집.

원본: 245/245/app.py 의 "245 책임표시"·"권차($n) 분리"·"MARC 필드 빌더"(build_245/
build_246/build_940) 섹션과 "원제·원저자 수집 메인 로직"(collect_orig_info) 전체.

245와 500/700/710/900은 collect_orig_info()가 만드는 author_info/orig_title/
orig_author_en 등을 강하게 공유하므로(INTEGRATION_PRINCIPLES.md #9 예외 조항),
이 파일이 공통 전처리(collect_orig_info)를 갖고 core/fields/marc_500_700_710.py가
이 파일에서 필요한 것을 import해서 쓴다.

이식 시 적용한 원칙:
  - #1  api/aladin_client.OPT_RESULT_FULL이 이미 subInfo/authors를 포함하므로
        245/app.py 원본처럼 authors,subInfo,seriesInfo만 별도로 재요청하지 않는다.
  - #3  OpenAI 클라이언트는 함수 인자로 주입 (collect_orig_info → gpt_orig_info_lookup).
  - #5  245/app.py 원본의 ALADIN_API_KEY 하드코딩 기본값은 이식하지 않음 —
        원제 조회용 알라딘 재검색(enrich_kanji_map_from_*)에는 core.config.Settings의
        aladin_ttb_key를 사용한다.
  - #6  에러를 성공 값 자리에 섞지 않는다 — collect_orig_info는 실패 시 그냥 None들을 담은
        dict를 반환한다(원본과 동일한 관용, 애초에 예외를 던지지 않는 설계였음).
  - #7  core.debug_log.dbg/dbg_err + "[245]" 프리픽스로 원본의 print() 디버그를 대체.
  - #8  (2026-07 패치) build_245_family에 lang_h(041 $h) 파라미터를 추가 —
        옮긴이 크레딧이 없는 번역서도 041에서 외국어로 판별되면 원제·원저자
        수집을 진행하도록 함(단독개발/통합 비교에서 246 누락 다수 발견되어 반영).
        app.py 호출부에서 build_041_546() 결과의 lang_h를 넘겨줘야 함.
"""

from __future__ import annotations

import html
import re

from core.debug_log import dbg, dbg_err
from core.text_utils import (
    PRIMARY_ROLES,
    ROLE_LABEL,
    ROLES_EXCLUDED_FROM_245,
    TRANS_ROLES,
    _ROLE_VERB_245,
    clean_subtitle,
    extract_english_author_after_korean_paren,
    remove_series,
    remove_year,
    strip_award_suffix_from_title,
    strip_honorifics,
)
from api.aladin_scraper import (
    _normalize_western_name_case,
    enrich_english_map_from_book_author_keyword,
    enrich_kanji_map_from_aladin_blob,
    enrich_kanji_map_from_author_overview_pages,
    enrich_kanji_map_from_book_author_keyword,
    enrich_kanji_map_from_foreign_title_search,
    gpt_orig_info_lookup,
    scrape_aladin_product,
)
from api.nlk_client import fetch_nlk_orig_info


# ─────────────────────────────────────────────
# 원제·원저자 수집 메인 로직
# ─────────────────────────────────────────────
def _book_description_for_gpt_hint(item: dict, limit: int = 500) -> str | None:
    """알라딘 책 소개(fullDescription2 등)에서 태그를 뺀 짧은 텍스트만 추출."""
    for key in ("fullDescription2", "fullDescription", "description"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            text = re.sub(r"<[^>]+>", " ", html.unescape(val))
            text = re.sub(r"\s+", " ", text).strip()
            return text[:limit] or None
    return None


def collect_orig_info(
    item: dict,
    item_id: str,
    isbn13: str,
    title: str,
    authors: list[dict],
    subtitle: str | None = None,
    category: str | None = None,
    *,
    aladin_ttb_key: str = "",
    nlk_api_key: str = "",
    openai_client=None,
    lang_h: str | None = None,
) -> dict:
    """
    알라딘 API → 알라딘 상품 페이지 크롤링 → NLK MARC → GPT 웹 검색 순으로
    원서명·원저자명·저자별 한자/영문 원표기를 수집한다.
    """
    non_trans    = [a for a in authors if not a["is_org"] and a["role"] not in TRANS_ROLES]
    primary_ko   = [a for a in non_trans if a["role"] in PRIMARY_ROLES]
    primary_name = primary_ko[0]["name"] if primary_ko else (non_trans[0]["name"] if non_trans else "")

    orig_title:     str | None = None
    orig_author_en: str | None = None
    _orig_title_src:  str = "-"
    _orig_author_src: str = "-"

    # 1순위: 알라딘 API subInfo.originalTitle
    sub_info = item.get("subInfo", {})
    if isinstance(sub_info, dict):
        api_orig = html.unescape((sub_info.get("originalTitle") or "").strip())
        if api_orig:
            orig_title = remove_year(api_orig)
            _orig_title_src = "aladin_api"

    # 2순위: 알라딘 상품 페이지 크롤링
    scraped       = scrape_aladin_product(item_id, orig_title_hint=orig_title)
    kanji_map     = scraped["kanji_map"]
    is_east_asian = scraped["is_east_asian"]

    if not orig_title and scraped["orig_title"]:
        orig_title = scraped["orig_title"]
        _orig_title_src = "aladin_scrape"
    if not orig_author_en and scraped["orig_author_en"]:
        orig_author_en = scraped["orig_author_en"]
        _orig_author_src = "aladin_scrape"

    enrich_kanji_map_from_aladin_blob(
        scraped.get("text_blob") or "", [a["name"] for a in non_trans], kanji_map,
    )
    enrich_kanji_map_from_foreign_title_search(
        orig_title, [a["name"] for a in non_trans], kanji_map, aladin_ttb_key,
    )
    english_map: dict[str, str] = {}
    enrich_kanji_map_from_author_overview_pages(
        [a["name"] for a in non_trans], scraped.get("author_overview_urls") or {},
        kanji_map, english_map=english_map,
    )
    orig_title_has_cjk_for_kanji_kw = bool(
        (orig_title or "").strip() and re.search(r"[぀-ヿ一-鿿]", orig_title)
    )
    if orig_title_has_cjk_for_kanji_kw:
        enrich_kanji_map_from_book_author_keyword(
            [a["name"] for a in non_trans], kanji_map, aladin_ttb_key,
        )
    enrich_english_map_from_book_author_keyword(
        [a["name"] for a in non_trans], english_map, aladin_ttb_key,
    )

    # 3순위: NLK MARC 레코드 — 246 19(원서명)·500 원저자명
    if not orig_title or not orig_author_en:
        nlk = fetch_nlk_orig_info(isbn13, title=title, api_key=nlk_api_key)
        if not orig_title and nlk["orig_title"]:
            _nlk_author = nlk.get("orig_author", "")
            _reject_nlk = False
            if orig_author_en and _nlk_author and re.search(r"[A-Za-z]", _nlk_author):
                _known_tok = set(re.findall(r"[A-Za-z]+", orig_author_en.lower()))
                _nlk_tok   = set(re.findall(r"[A-Za-z]+", _nlk_author.lower()))
                if _known_tok and _nlk_tok and not (_known_tok & _nlk_tok):
                    dbg_err(f"[245] NLK orig_title 거부 — 저자 불일치 (known={orig_author_en!r}, nlk={_nlk_author!r})")
                    _reject_nlk = True
            # (2026-07 패치) 041 $h로 이미 원서 언어가 비동아시아권으로 확정된 상태인데
            # NLK가 내놓은 원제가 한자·가나(CJK)면, 이 ISBN에 대한 NLK 레코드 자체가
            # 엉뚱한(다른 책) 데이터일 가능성이 높다고 보고 거부한다.
            # ("슬픔은 다 거짓이야"(대니얼 나예리, 영어 원작) 사례 — NLK가 전혀 무관한
            # 일본어 원제로 보이는 "源叔夫"를 반환한 것을 확인.)
            if (
                not _reject_nlk
                and lang_h
                and lang_h not in ("jpn", "chi", "zho", "und")
                and re.search(r"[一-鿿㐀-䶿぀-ヿ]", nlk["orig_title"])
            ):
                dbg_err(f"[245] NLK orig_title 거부 — lang_h={lang_h!r}인데 CJK 원제 반환 (nlk_title={nlk['orig_title']!r})")
                _reject_nlk = True
            if not _reject_nlk:
                orig_title = nlk["orig_title"]
                _orig_title_src = "nlk"
        if not orig_author_en and nlk["orig_author"]:
            if re.search(r"[A-Za-z]", nlk["orig_author"]):
                orig_author_en = nlk["orig_author"]
                _orig_author_src = "nlk"
            elif re.search(r"[一-鿿぀-ヿ㐀-䶿]", nlk["orig_author"]):
                # NLK 500이 선집(여러 원저자 단편 모음)일 때 콤마로 구분된 여러 명의
                # 원저자명을 한 줄에 몰아 담아두는 경우가 있다("봄은 마차를 타고" —
                # 국중 500에 12명 한자명이 통째로 한 줄로 들어있음). 이걸 그대로
                # primary_name(대표 저자 1명) 몫으로 넣으면, 그 12명이 각자 프로필
                # 조회로 이미 개별적으로 찾아낸 한자명과 중복돼 500이 부풀려진다
                # (2026-08 발견). 콤마가 없는 진짜 단일 인물 표기일 때만 적용한다.
                _nlk_orig_author_chunks = [
                    c.strip() for c in re.split(r",\s*", nlk["orig_author"]) if c.strip()
                ]
                if (
                    len(_nlk_orig_author_chunks) == 1
                    and primary_name
                    and not kanji_map.get(primary_name)
                ):
                    kanji_map[primary_name] = nlk["orig_author"]

    # 4순위: GPT Responses API (web_search_preview) — 알라딘·NLK 모두 없을 때
    if not orig_title or not orig_author_en:
        _reliable_orig_title = orig_title if _orig_title_src == "aladin_api" else None
        _pub  = (item.get("publisher") or "").strip() or None
        _year = (item.get("pubDate") or "")[:4] or None
        _author_kanji = kanji_map.get(primary_name) if primary_name else None
        _desc_hint = _book_description_for_gpt_hint(item)
        dbg(f"[245] GPT 원제/원저자 조회 — title={title!r} orig_title={orig_title!r} orig_author_en={orig_author_en!r}")
        gpt = gpt_orig_info_lookup(
            openai_client, title, authors,
            known_orig_author=orig_author_en, known_orig_title=_reliable_orig_title,
            publisher=_pub, pub_year=_year, subtitle=subtitle, category=category,
            author_kanji=_author_kanji, description_hint=_desc_hint,
        )
        if gpt["orig_title"] and (not orig_title or _orig_title_src != "aladin_api"):
            orig_title = gpt["orig_title"]
            _orig_title_src = "gpt"
        if not orig_author_en and gpt["orig_author_en"]:
            orig_author_en = gpt["orig_author_en"]
            _orig_author_src = "gpt"
        if gpt.get("orig_author_kanji") and primary_name and not kanji_map.get(primary_name):
            kanji_map[primary_name] = gpt["orig_author_kanji"]
        if (
            _orig_title_src == "gpt"
            and orig_title
            and re.search(r"[぀-ヿ一-鿿]", orig_title)
            and primary_name
            and not kanji_map.get(primary_name)
        ):
            enrich_kanji_map_from_foreign_title_search(
                orig_title, [a["name"] for a in non_trans], kanji_map, aladin_ttb_key,
            )

    if orig_author_en:
        orig_author_en = strip_honorifics(orig_author_en)

    dbg(f"[245] orig_info ISBN={isbn13} title={title!r} orig_title={orig_title!r}(src={_orig_title_src}) orig_author_en={orig_author_en!r}(src={_orig_author_src})")

    author_info = []
    for a in non_trans:
        nm = a["name"]
        en_prof = english_map.get(nm)
        if not en_prof:
            from api.aladin_scraper import _norm_author_display
            nk = _norm_author_display(nm)
            for k, v in english_map.items():
                if _norm_author_display(k) == nk:
                    en_prof = v
                    break
        author_info.append({
            "name":          nm,
            "kanji_name":    kanji_map.get(nm),
            "english_name":  strip_honorifics(en_prof) if en_prof else en_prof,
            "is_east_asian": is_east_asian or orig_title_has_cjk_for_kanji_kw,
        })

    if orig_author_en:
        orig_author_en = _normalize_western_name_case(orig_author_en)

    return {
        "orig_title":         orig_title,
        "orig_author_en":     orig_author_en,
        "author_info":        author_info,
        "intro_persons":      scraped.get("intro_persons") or [],
        "intro_author_pairs": scraped.get("intro_author_pairs") or [],
    }


# ─────────────────────────────────────────────
# 245 책임표시
# ─────────────────────────────────────────────
def _role_label_for_245(role: str) -> str:
    """245 책임표시에 쓸 역할어."""
    r = (role or "").strip()
    if not r or r in PRIMARY_ROLES:
        return "지은이"
    return ROLE_LABEL.get(r, r)


def _role_excluded_from_245(role: str) -> bool:
    """245 $d/$e 책임표시에서 빼고 500 주기로 보낼 역할."""
    r = (role or "").strip()
    if r in ROLES_EXCLUDED_FROM_245:
        return True
    return _role_label_for_245(r) in ROLES_EXCLUDED_FROM_245


def _role_verb_for_245(role: str) -> str:
    """역할어 → 245 동사형. 매핑 없으면 원본 반환."""
    return _ROLE_VERB_245.get((role or "").strip(), (role or "").strip())


def _marc_suffix_from_responsibility_pairs(pairs: list[tuple[str, str]]) -> str | None:
    """
    (역할, 이름) 목록 → MARC 245 책임표시 suffix.
    형식: /$d 이름1 ,$e 이름2 지음 ;$e 이름3 옮김
    """
    groups: list[tuple[str, list[str]]] = []
    for role, name in pairs:
        if _role_label_for_245(role) in ROLES_EXCLUDED_FROM_245:
            continue
        name = name.strip()
        if not name:
            continue
        if groups and groups[-1][0] == role:
            groups[-1][1].append(name)
        else:
            groups.append((role, [name]))

    if not groups:
        return None

    parts: list[str] = []
    for i, (role, names) in enumerate(groups):
        verb = _role_verb_for_245(role)
        if i == 0:
            e_str = names[0] + "".join(f" ,$e {n}" for n in names[1:]) + f" {verb}"
            parts.append(f"/$d {e_str}")
        else:
            e_str = f";$e {names[0]}" + "".join(f" ,$e {n}" for n in names[1:]) + f" {verb}"
            parts.append(f" {e_str}")
    return "".join(parts)


def _responsibility_pairs_from_authors(authors: list[dict]) -> list[tuple[str, str]]:
    """책임표시용 (원본역할, 이름) — 개인·기관 저자 모두 포함, 알라딘 등장 순서 그대로.
    (2026-08 패치: 예전엔 개인 저자가 하나라도 있으면 기관 저자를 전부 버리는
    "pairs or org_pairs" 방식이라, 개인·기관이 섞인 저자 목록에서 기관 저자가
    $d에서 통째로 누락됐다 — "구루마다 가즈히사"(오판으로 기관 처리됨) + 번역자
    "박세미" 사례에서 $d에 "박세미 옮김"만 남고 저자 이름이 빠지던 문제. 모두 한
    목록에 순서대로 담으면 "저자 전원이 기관인 경우"(국립중앙박물관 등, $d가
    비지 않아야 함)도 자연히 해결된다.)"""
    pairs: list[tuple[str, str]] = []
    for a in authors:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        if _role_excluded_from_245(a.get("role", "")):
            continue
        role = (a.get("role") or "").strip()
        pairs.append((role, name))
    return pairs


def _build_responsibility_marc_suffix_from_authors(authors: list[dict]) -> str | None:
    """245 책임표시. 예: /$d 이름 지음 ;$e 이름 옮김"""
    return _marc_suffix_from_responsibility_pairs(_responsibility_pairs_from_authors(authors))


def _responsibility_plain_to_marc_suffix(text: str) -> str | None:
    """'지은이: A, B ; 옮긴이: C' → '/$d 지은이: A ,$e B ;$e 옮긴이: C'."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return None
    if t.startswith("/$"):
        return t
    pairs: list[tuple[str, str]] = []
    parts = [p.strip() for p in re.split(r"\s*;\s*", t) if p.strip()]
    for part in parts:
        m = re.match(r"^([^:]+):\s*(.+)$", part)
        if m:
            label = m.group(1).strip()
            for name in re.split(r"\s*,\s*", m.group(2).strip()):
                if name.strip():
                    pairs.append((label, name.strip()))
        elif part:
            label = pairs[-1][0] if pairs else "지은이"
            pairs.append((label, part))
    return _marc_suffix_from_responsibility_pairs(pairs)


def _split_title_subtitle_for_245(title: str, subtitle: str) -> tuple[str, str]:
    """
    표제 문자열에서 $a·$b 분리.
    예: '카프네 = Cafuné : 아베 아키코 장편소설' → ('카프네', '아베 아키코 장편소설')
    """
    t = strip_award_suffix_from_title(remove_series((title or "").strip()))
    sub = clean_subtitle((subtitle or "").strip())

    m = re.match(r"^(.+?)\s*=\s*[^:：]+[:：]\s*(.+)$", t)
    if m:
        a, b = m.group(1).strip(), clean_subtitle(m.group(2).strip())
        if b:
            return a, b

    for sep in (" : ", "：", ":"):
        if sep not in t:
            continue
        a, b = t.split(sep, 1)
        a, b = a.strip(), clean_subtitle(b.strip())
        if b:
            return a, b

    if sub:
        return t, sub
    return t, ""


# ─────────────────────────────────────────────
# 권차($n) 분리 유틸
# ─────────────────────────────────────────────
_PART_LABEL_RX = re.compile(
    r"(?:제?\s*\d+\s*(?:권|부|편|책)"
    r"|[IVXLCDM]+"
    r"|[상중하]|[전후])$",
    re.IGNORECASE,
)


def _has_series_evidence(item: dict) -> bool:
    series = item.get("seriesInfo") or {}
    sub    = item.get("subInfo") or {}
    if series.get("seriesName") or series.get("seriesId"):
        return True
    orig = (sub.get("originalTitle") or "").strip()
    if orig and not re.search(r"\d\s*$", orig):
        return True
    return False


def _split_part_suffix_for_245(a_raw: str, item: dict) -> tuple[str, str | None]:
    """제목 끝의 권차(1권/1부/상/I 등)를 $n으로 분리. 반환: (a_base, n_or_None)."""
    if not a_raw:
        return "", None
    a = a_raw.strip(" .,/;:-—·|")
    if re.fullmatch(r"\d+|[IVXLCDM]+", a, re.IGNORECASE):
        return a, None

    m_paren = re.search(r"\s*[\(\[]\s*([^()\[\]]+)\s*[\)\]]\s*$", a)
    if m_paren and _PART_LABEL_RX.search(m_paren.group(1).strip()):
        n_token = m_paren.group(1).strip()
        a_base  = a[: m_paren.start()].rstrip(" .,/;:-—·|")
        m_num   = re.search(r"\d+", n_token)
        return a_base, (m_num.group(0) if m_num else n_token)

    m_label = re.search(r"\s*(제?\s*\d+\s*(?:권|부|편|책))\s*$", a, re.IGNORECASE)
    if m_label:
        a_base = a[: m_label.start()].rstrip(" .,/;:-—·|")
        num    = re.search(r"\d+", m_label.group(1))
        return a_base, (num.group(0) if num else m_label.group(1).strip())

    m_kor = re.search(r"(?:^|\s)([상중하]|[전후])\s*$", a)
    if m_kor:
        a_base = a[: m_kor.start()].rstrip(" .,/;:-—·|")
        return a_base, m_kor.group(1)

    m_roman = re.search(r"\s*([IVXLCDM]+)\s*$", a, re.IGNORECASE)
    if m_roman:
        a_base = a[: m_roman.start()].rstrip(" .,/;:-—·|")
        return a_base, m_roman.group(1)

    m_tailnum = re.search(r"\s*(\d{1,3})\s*$", a)
    if m_tailnum and _has_series_evidence(item):
        a_base = a[: m_tailnum.start()].rstrip(" .,/;:-—·|")
        if a_base:
            return a_base, m_tailnum.group(1)

    return a, None


# ─────────────────────────────────────────────
# MARC 필드 빌더
# ─────────────────────────────────────────────
def build_245(
    title: str,
    subtitle: str,
    authors: list[dict],
    responsibility: str | None = None,
    *,
    item: dict | None = None,
) -> str:
    a_part, b_part = _split_title_subtitle_for_245(title, subtitle)

    n_part = ""
    if item is not None:
        a_part, n_part = _split_part_suffix_for_245(a_part, item)
        n_part = n_part or ""

    field = f"$a {a_part}"
    if n_part:
        field += f" .$n {n_part}"
    if b_part:
        field += f" :$b {b_part}"

    resp_plain = (responsibility or "").strip()
    resp_marc = (
        _responsibility_plain_to_marc_suffix(resp_plain)
        if resp_plain
        else _build_responsibility_marc_suffix_from_authors(authors)
    )
    if resp_marc:
        field += f" {resp_marc}"

    return field


_LEADING_ARTICLE_PAT = re.compile(r"^(the|an?)\s+", re.IGNORECASE)

_YEAR_OR_EDITION_PAREN_PAT = re.compile(
    r"""\s*\(\s*(?:
         \d{3,4}\s*년?
        |rev(?:ised)?\.?\s*ed\.?
        |\d+(?:st|nd|rd|th)\s*ed\.?
        |edition
        |ed\.?
        |제?\s*\d+\s*판
        |개정(?:증보)?판?
        |증보판|초판|신판|보급판
    )[^()\[\]]*\)\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def build_246(orig_title: str | None) -> str | None:
    if not orig_title:
        return None
    t = remove_year(orig_title.strip())
    t = _YEAR_OR_EDITION_PAREN_PAT.sub("", t).strip()
    t = _LEADING_ARTICLE_PAT.sub("", t).strip()
    if not t:
        return None
    if ":" in t:
        main, _, sub = t.partition(":")
        main = main.strip()
        sub = sub.strip()
        if main and sub:
            return f"246 19 $a {main} :$b {sub}"
    return f"246 19 $a {t}"


_ENG_LETTER_KO: dict[str, str] = {
    'A': '에이', 'B': '비', 'C': '씨', 'D': '디', 'E': '이',
    'F': '에프', 'G': '지', 'H': '에이치', 'I': '아이', 'J': '제이',
    'K': '케이', 'L': '엘', 'M': '엠', 'N': '엔', 'O': '오',
    'P': '피', 'Q': '큐', 'R': '알', 'S': '에스', 'T': '티',
    'U': '유', 'V': '브이', 'W': '더블유', 'X': '엑스', 'Y': '와이',
    'Z': '제트',
}
_ENG_DIGIT_KO: dict[str, str] = {
    '0': '제로', '1': '원', '2': '투', '3': '쓰리', '4': '포',
    '5': '파이브', '6': '식스', '7': '세븐', '8': '에이트', '9': '나인',
}

_KO_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_KO_PLACES = ["", "십", "백", "천"]
_KO_LARGE  = ["", "만", "억", "조"]
_KO_DIGIT_READ = ["공", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]

# 순우리말 단위명사(가지/개/명 등) 앞에서는 한자어 수사 대신 고유어 수사를 씀.
# 단위명사 바로 앞은 관형형(하나→한, 둘→두, 셋→세, 넷→네, 스물→스무, 그 외는 동일).
_KO_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_KO_NATIVE_ONES_ATTR = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_KO_NATIVE_TENS_ATTR = ["", "열", "스무", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_NATIVE_COUNTER_WORDS = (
    "시간", "가지", "그루", "송이", "켤레", "마리", "조각", "다발", "마디",
    "달", "개", "명", "살", "채", "벌", "자루", "시", "권", "부", "편", "책",
)
_NATIVE_COUNTER_RX = "|".join(_NATIVE_COUNTER_WORDS)


def _native_korean_number_attr(n: int) -> str | None:
    """단위명사 앞 순우리말 수관형사(세 명/여섯 가지 등). 1~99만 지원, 범위 밖이면 None."""
    if n <= 0 or n > 99:
        return None
    if n < 10:
        return _KO_NATIVE_ONES_ATTR[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _KO_NATIVE_TENS_ATTR[tens]
    return _KO_NATIVE_TENS[tens] + _KO_NATIVE_ONES_ATTR[ones]


def _is_decade_pair_code(n: int) -> bool:
    """1020/2030/.../9020처럼 두 자리 세대(연령대) 쌍으로 이루어진 4자리 숫자인지.
    "1020 극우가 온다"처럼 "10대+20대"를 뜻하는 세대 코드는 큰 수(천이십)가 아니라
    자릿수별(일공이공)로 읽어야 함."""
    if n < 1000 or n > 9999:
        return False
    first, second = n // 100, n % 100
    return 10 <= first <= 90 and first % 10 == 0 and 10 <= second <= 90 and second % 10 == 0


def _arabic_to_korean(n: int) -> str:
    """아라비아 숫자 → 한국어 수 읽기. 예: 64 → 육십사, 1984 → 천구백팔십사.
    단, 1020/5060처럼 세대 코드로 보이는 4자리 숫자는 자릿수별로 읽음(일공이공)."""
    if _is_decade_pair_code(n):
        return "".join(_KO_DIGIT_READ[int(c)] for c in str(n))
    if n == 0:
        return "영"
    result = ""
    groups: list[int] = []
    tmp = n
    while tmp > 0:
        groups.append(tmp % 10000)
        tmp //= 10000
    for i in range(len(groups) - 1, -1, -1):
        u = groups[i]
        if u == 0:
            continue
        group = ""
        for j in range(3, -1, -1):
            d = (u // (10 ** j)) % 10
            if d == 0:
                continue
            if d == 1 and j > 0:
                group += _KO_PLACES[j]
            else:
                group += _KO_DIGITS[d] + _KO_PLACES[j]
        result += group + _KO_LARGE[i]
    return result


def build_940(title: str) -> str | None:
    """245 제목에 숫자·영문자가 포함되면 한국어 읽기로 변환해 940 필드 반환.
    없으면 None."""
    t = (title or "").strip()
    if not t:
        return None

    has_change = False

    def _replace(m: re.Match) -> str:
        nonlocal has_change
        token = m.group(0)
        has_change = True
        mixed = re.match(r'^(\d+)([A-Za-z]+)$', token)
        if mixed:
            ko_num = "".join(_ENG_DIGIT_KO.get(c, c) for c in mixed.group(1))
            ko_let = "".join(_ENG_LETTER_KO.get(c.upper(), c) for c in mixed.group(2))
            return ko_num + ko_let
        m_percent = re.match(r'^(\d+)\s?%$', token)
        if m_percent:
            return _arabic_to_korean(int(m_percent.group(1))) + "퍼센트"
        m_counter = re.match(r'^(\d+)(\s?)(' + _NATIVE_COUNTER_RX + r')$', token)
        if m_counter:
            num_part, space, counter = m_counter.group(1), m_counter.group(2), m_counter.group(3)
            native = _native_korean_number_attr(int(num_part))
            if native:
                return native + space + counter
            return _arabic_to_korean(int(num_part)) + space + counter
        if token.isdigit():
            return _arabic_to_korean(int(token))
        return "".join(_ENG_LETTER_KO.get(c.upper(), c) for c in token)

    result = re.sub(
        r'[A-Za-z]+|\d+[A-Za-z]+|\d+\s?%|\d+\s?(?:' + _NATIVE_COUNTER_RX + r')|\d+',
        _replace, t,
    )
    if not has_change:
        return None
    result = re.sub(r'[^가-힣\s]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return f"940    $a{result}"


# ─────────────────────────────────────────────
# 상위 오케스트레이터 — app.py가 호출하는 진입점
# ─────────────────────────────────────────────
def build_245_family(
    item: dict,
    isbn13: str,
    *,
    aladin_ttb_key: str = "",
    nlk_api_key: str = "",
    openai_client=None,
    lang_h: str | None = None,
) -> dict:
    """
    245/246/940 필드와, 500/700/710/900 계열이 이어서 쓸 컨텍스트(orig_title,
    orig_author_en, author_info 등)를 함께 반환한다.

    원본: 245/245/app.py의 _isbn_lookup() 전체 — item에서 title/subtitle/authors를
    직접 추출하는 부분(총서명 제거, subInfo.subTitle 분리, parse_authors, 번역서 판별)부터
    245/246/940 관련 부분(collect_orig_info 호출 → build_245/build_940 호출)까지.
    이후 500/700/710/900 계산은 core/fields/marc_500_700_710.build_500_700_710_900()
    가 이 함수의 반환값(dict)을 그대로 입력받아 이어서 처리한다.

    Args:
        lang_h: 041 $h(원저작 언어) 코드. app.py가 build_041_546()을 먼저 호출한 뒤
            LangFieldBuilder.extract_lang_h(tag_041)로 뽑아서 넘겨준다. 옮긴이
            크레딧이 없는 번역서(원저자가 외국인인데 옮긴이 표시가 안 된 경우)도
            041에서 외국어로 판별되면 원제·원저자 수집을 진행하기 위해 사용한다.

    Returns:
        {
            "field_245": str, "field_246_raw": str|None, "field_940": str|None,
            "title": str, "subtitle": str, "authors": list[dict],
            "orig_title": str|None, "orig_author_en": str|None,
            "author_info": list[dict], "intro_persons": list[dict],
            "intro_author_pairs": list[dict],
            "translation_book": bool, "category_name": str,
        }
    """
    from core.text_utils import parse_authors

    item_id = str(item.get("itemId", ""))
    title = item.get("title", "")
    subtitle = ""

    # 총서명 제거 (seriesInfo.seriesName 활용)
    series_info = item.get("seriesInfo", {})
    if isinstance(series_info, dict):
        series_name = (series_info.get("seriesName") or "").strip()
        if series_name:
            series_base = re.sub(r"\s*\d+$", "", series_name).strip()
            title = re.sub(r"\s*\(" + re.escape(series_base) + r"[^)]*\)", "", title).strip()

    sub_info = item.get("subInfo", {})
    if isinstance(sub_info, dict):
        api_sub = (sub_info.get("subTitle") or "").strip()
        if api_sub and title.endswith(api_sub):
            title    = title[: -len(api_sub)].rstrip(" -:").strip()
            subtitle = api_sub
        elif api_sub:
            subtitle = "" if clean_subtitle(api_sub) == "" else api_sub

    if not subtitle:
        for sep in (" - ", " – ", " : ", "：", ":"):
            if sep in title:
                t, s = title.split(sep, 1)
                t, s = t.strip(), s.strip()
                if clean_subtitle(s) == "":
                    title = t
                else:
                    title, subtitle = t, s
                break

    author_str = item.get("author", "")
    authors    = parse_authors(author_str)
    has_translator = any(a["role"] in TRANS_ROLES for a in authors)
    # 옮긴이 역할이 명시되지 않은 번역서(원저자가 외국인인데 옮긴이 크레딧이 따로 없는 경우)도
    # 041 $h(lang_h)가 외국어(kor/und가 아님)로 감지되면 번역서로 간주해 원제·원저자
    # 수집을 진행한다. (2026-07 패치: 단독개발/통합 비교에서 246 누락 다수 발견되어 반영)
    _lang_h_is_foreign = bool(lang_h and lang_h not in ("kor", "und"))
    needs_orig_lookup = has_translator or _lang_h_is_foreign
    category_name = (item.get("categoryName") or "").strip()

    orig_title:     str | None = None
    orig_author_en: str | None = None
    author_info:    list       = []
    intro_persons:  list[dict] = []
    intro_author_pairs: list[dict] = []

    if needs_orig_lookup:
        orig_info = collect_orig_info(
            item, item_id, isbn13, title, authors, subtitle=subtitle, category=category_name,
            aladin_ttb_key=aladin_ttb_key, nlk_api_key=nlk_api_key, openai_client=openai_client,
            lang_h=lang_h,
        )
        orig_title = orig_info["orig_title"]
        orig_author_en = orig_info["orig_author_en"]
        author_info    = orig_info["author_info"]
        intro_persons  = orig_info.get("intro_persons") or []
        intro_author_pairs = orig_info.get("intro_author_pairs") or []
        if not orig_author_en:
            from core.text_utils import aladin_item_description_blob
            blob = aladin_item_description_blob(item)
            orig_author_en = extract_english_author_after_korean_paren(blob)
        if author_info:
            from core.text_utils import _extract_paren_english_names_from_blob, aladin_item_description_blob
            blob2 = aladin_item_description_blob(item)
            n_auth = len(author_info)
            n_comm = (orig_author_en or "").count(",")
            thin = (
                not orig_author_en
                or len(orig_author_en) < 100
                or (n_comm + 1 < min(n_auth, 14))
            )
            if thin:
                names = _extract_paren_english_names_from_blob(blob2)
                if names and len(names) >= max(2, n_comm + 2):
                    orig_author_en = ", ".join(names[: min(len(names), n_auth + 4)])

    if subtitle and clean_subtitle(subtitle) == "":
        subtitle = ""
    title = strip_award_suffix_from_title(title)

    field_245 = build_245(title, subtitle, authors, item=item)
    # build_245 내부(_split_title_subtitle_for_245)는 remove_series()로 제목 끝 괄호
    # (예: "(2026개정판)")를 지우고 245를 만드는데, 940은 그 정리 전 title을 그대로 받아서
    # "2026개정판"처럼 제목이 아닌 부분까지 숫자 읽기로 변환되는 문제가 있었음. 245와 같은
    # 정리를 940 입력에도 적용한다.
    # (2026-08 패치: "훔쳐라, 아티스트처럼" 사례 — 940에 "이천이십육 개정판"이 그대로 노출됨.)
    field_940 = build_940(remove_series(title))

    return {
        "field_245":           f"245 00 {field_245}",
        "field_246_raw":       orig_title,   # build_246은 jp_ctx_for_500 계산 후(500/700 단계)에 호출
        "field_940":           field_940,
        "title":               title,
        "subtitle":            subtitle,
        "authors":             authors,
        "orig_title":          orig_title,
        "orig_author_en":      orig_author_en,
        "author_info":         author_info,
        "intro_persons":       intro_persons,
        "intro_author_pairs":  intro_author_pairs,
        "translation_book":    needs_orig_lookup,
        "category_name":       category_name,
        "lang_h":              lang_h,
    }
