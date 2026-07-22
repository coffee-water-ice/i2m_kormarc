"""
core/fields/marc_500_700_710.py
500(원저자명 주기)·700(개인명 부출)·710(기관명 부출)·900(원저자 한글명) 필드 생성.

원본: 245/245/app.py 의 이름 판별·도치 함수군 전체와, _isbn_lookup()의 500/700/710/900
생성 블록(약 400줄, 246의 최종 억제 여부도 여기서 함께 결정됨 — jp_ctx_for_500이
500/700/900과 246을 동시에 좌우하기 때문에 원본과 동일하게 이 단계에서 처리한다).

245와 표제 정보를 공유하므로 core/fields/marc_245.py 의 공통 전처리
(collect_orig_info가 반환한 author_info 등)를 그대로 이어받아 쓴다
(INTEGRATION_PRINCIPLES.md #9 예외 조항).

이식 시 적용한 원칙:
  - #3  OpenAI 클라이언트는 함수 인자로 주입 (decide_name_order_via_llm).
  - #7  core.debug_log.dbg + "[700]" 프리픽스로 원본의 print() 디버그를 대체.
"""

from __future__ import annotations

import re
from functools import lru_cache

from core.debug_log import dbg
from core import token_tracker
from core.text_utils import (
    KNOWN_PEN_NAMES,
    TRANS_ROLES,
    _KO_AUTHOR_PAREN_SKIP,
    _DEVANAGARI_RE,
    _PALI_SANSKRIT_DIACRITICS,
    _is_hangul_only_orig_name_for_500,
    _looks_like_roman_orig_display,
    _orig_500_token_has_hangul,
    _SPANISH_GIVEN_NAMES_KOREAN,
    _jp_name_reading_hangul,
    english_name_reverse,
    kanji_to_korean_reading,
    kanji_type,
    korean_name_reverse,
)
from core.name_data.korean_surnames import KOREAN_SURNAMES, KOREAN_SURNAMES_BY_LENGTH
from core.name_data.japanese_surnames import JAPANESE_SURNAMES
from core.name_data.korean_real_name_allowlist import KOREAN_REAL_NAME_ALLOWLIST as _KOREAN_REAL_NAME_ALLOWLIST
from core.name_data.korean_given_names import korean_given_name_is_plausible, korean_given_names
from api.aladin_scraper import (
    _is_paren_latin_roman_name,
    _is_probable_orig_script,
    _norm_author_lookup_key,
    try_orig_names_500_from_intro_english_pairs,
    try_orig_names_500_from_profile_english,
)
from core.fields.marc_245 import (
    _role_excluded_from_245,
    _role_label_for_245,
    build_246,
)


# ─────────────────────────────────────────────
# 500
# ─────────────────────────────────────────────
def build_500(orig_author_en: str | None, kanji_name: str | None = None) -> str | None:
    """
    케이스 1: 한자+가나 혼합 (鈴木いづみ) → 500 __ $a 원저자명: 鈴木いづみ
    케이스 2: 한자만 (村上春樹)           → 500 __ $a 원저자명: 村上春樹
    케이스 3: 서양 저자                   → 500 __ $a 원저자명: Georges Bernanos
    """
    if kanji_name:
        ktype = kanji_type(kanji_name)
        if ktype in ("kanji_only", "kanji_kana"):
            return f"500 __ $a 원저자명: {kanji_name}"
    if orig_author_en:
        return f"500 __ $a 원저자명: {orig_author_en.strip()}"
    return None


def build_500_role_notes(authors: list[dict]) -> list[str]:
    """245 제외 역할(감수 등) → 500 __ $a 감수: 이름 …"""
    by_role: dict[str, list[str]] = {}
    for a in authors:
        if a.get("is_org"):
            continue
        role = (a.get("role") or "").strip()
        if not _role_excluded_from_245(role):
            continue
        name = (a.get("name") or "").strip()
        if not name:
            continue
        label = _role_label_for_245(role)
        by_role.setdefault(label, []).append(name)
    fields: list[str] = []
    for label in sorted(by_role):
        names = by_role[label]
        fields.append(f"500 __ $a {label}: {', '.join(names)}")
    return fields


# ─────────────────────────────────────────────
# 700 — 이름 표기/도치
# ─────────────────────────────────────────────
def personal_name_for_700_field(name: str) -> str:
    """
    700 $a용 표기. 필명(본명) 형태면 괄호 안 한글 본명은 제거하고 앞 표기만 사용.
    예: 로사장(김다솔) → 로사장. (지은이)·(村上春樹)·(Nalo Hopkinson) 등은 유지.
    """
    n = (name or "").strip()
    m = re.match(r"^(.+?)\s*[(（]\s*([^)）]+)\s*[)）]\s*$", n)
    if not m:
        return n
    outer, inner = m.group(1).strip(), m.group(2).strip()
    if not outer or inner in _KO_AUTHOR_PAREN_SKIP:
        return n
    if _is_probable_orig_script(inner):
        return n
    if _is_paren_latin_roman_name(inner):
        return outer if re.search(r"[가-힣]", outer) else n
    if re.fullmatch(r"[가-힣·ㆍ\s]{2,24}", inner) and re.search(r"[가-힣]", inner):
        return outer
    return n


_NAME_ORDER_SYSTEM_PROMPT = (
    "당신은 한국 도서관 KORMARC 700 필드용 이름 정렬 보조자입니다.\n"
    "입력은 한글 음역 외국인 저자명입니다. 성·이름 순서를 판별하고,\n"
    "필요 시 '성, 이름'으로 재배열하여 JSON으로만 응답합니다.\n\n"
    "[힌트 활용]\n"
    "- 원서명: 원서 제목의 언어(영어·프랑스어·러시아어 등)가 국적 추론에 도움됨.\n"
    "- 분야: 알라딘 카테고리(예: '영미소설', '프랑스소설', '러시아소설', '베트남소설')가 있으면 최우선 참고.\n\n"
    "[판별 규칙]\n"
    "1) 한국·중국·일본 등 성명 관습이 성–이름인 경우 → KEEP.\n"
    "2) 유럽·미주권(이름–성 관습) → REORDER: '성, 이름'.\n"
    "3) 러시아식 부칭(-비치/-브나) → REORDER: 성을 앞으로.\n"
    "4) 스페인/포르투갈 복성은 복성 전체를 성으로.\n"
    "5) 단일 이름(모노님) → KEEP.\n"
    "6) 베트남식 성–이름 관습 → KEEP.\n\n"
    "[출력 형식] JSON 한 줄만:\n"
    '{"action":"KEEP|REORDER","result":"<최종 표기>","reason":"<판별 근거>"}\n'
    "REORDER 시 result는 반드시 '성, 이름' 형식."
)


@lru_cache(maxsize=2048)
def _decide_name_order_via_llm_cached(hangul_name: str, context: str, openai_client) -> dict:
    name = (hangul_name or "").strip()
    if not name:
        return {"action": "KEEP", "result": "", "reason": "empty"}
    parts = name.split()
    if len(parts) <= 1:
        return {"action": "KEEP", "result": name, "reason": "mononym"}

    if openai_client is None:
        if len(parts) >= 3 and parts[0] in _SPANISH_GIVEN_NAMES_KOREAN and parts[1] not in _SPANISH_GIVEN_NAMES_KOREAN:
            compound = " ".join(parts[1:])
            return {"action": "REORDER", "result": f"{compound}, {parts[0]}", "reason": "fallback-spanish-compound"}
        reversed_name = korean_name_reverse(name)
        if reversed_name:
            return {"action": "REORDER", "result": reversed_name, "reason": "fallback-no-llm"}
        return {"action": "KEEP", "result": name, "reason": "fallback-no-llm"}

    try:
        import json as _json
        user_msg = f'이름: "{name}"'
        if context:
            user_msg += f"\n컨텍스트: {context}"
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _NAME_ORDER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=100,
        )
        if response.usage:
            token_tracker.add(response.usage.prompt_tokens, response.usage.completion_tokens)
        text = (response.choices[0].message.content or "").strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        data = _json.loads(text)
        action = data.get("action", "KEEP")
        result = (data.get("result") or name).strip()
        if action == "REORDER" and "," not in result:
            result = f"{parts[-1]}, {' '.join(parts[:-1])}"
        return {"action": action, "result": result, "reason": data.get("reason", "")}
    except Exception:
        if len(parts) == 2:
            return {"action": "REORDER", "result": f"{parts[-1]}, {parts[0]}", "reason": "fallback-error"}
        return {"action": "KEEP", "result": name, "reason": "fallback-error"}


def decide_name_order_via_llm(hangul_name: str, context: str = "", openai_client=None) -> dict:
    """한글 음역 외국인 이름의 성·이름 순서를 GPT로 판별. 반환: {"action","result","reason"}"""
    return _decide_name_order_via_llm_cached(hangul_name, context, openai_client)


def build_700(author: dict, *, context: str = "", openai_client=None) -> str:
    name = personal_name_for_700_field(author["name"].strip())
    if name in KNOWN_PEN_NAMES:
        return f"$a {name}"
    if re.search(r"[A-Za-z]", name) and not re.search(r"[가-힣]", name):
        name = english_name_reverse(name)
    elif re.search(r"[가-힣]", name) and not is_korean_person_by_surname(name):
        result = decide_name_order_via_llm(name, context, openai_client)
        name = result["result"] or name
    return f"$a {name}"


# ─────────────────────────────────────────────
# 700 두 번째 지시기호(0/1) 판별
# ─────────────────────────────────────────────
_NAME_TITLE_SUFFIXES = (
    "선생님", "교수님", "박사", "교수", "선생", "작가", "기자", "님", "씨",
)


def _strip_pen_name_affixes(name: str) -> str:
    """…김홍홍박사 → 김홍홍 등 앞뒤 장식·직함 제거."""
    n = (name or "").strip()
    n = re.sub(r"^[.…·※\s]+", "", n)
    n = re.sub(r"[.…]+$", "", n)
    for suf in sorted(_NAME_TITLE_SUFFIXES, key=len, reverse=True):
        if n.endswith(suf) and len(n) > len(suf):
            n = n[:-len(suf)]
    return n.strip()


def _split_korean_surname_given(core: str) -> tuple[str, str] | None:
    """복성(남궁·제갈 등) 우선 분리."""
    for sur in KOREAN_SURNAMES_BY_LENGTH:
        if core.startswith(sur) and len(core) > len(sur):
            return sur, core[len(sur):]
    return None


def _given_part_looks_valid(given: str) -> bool:
    """이름 부분: 한글 1~2음절, 동일 글자 반복(홍홍) 제외."""
    if not given or not re.match(r"^[가-힣]+$", given):
        return False
    if len(given) > 2:
        return False
    if len(given) == 2 and given[0] == given[1]:
        return False
    return True


def korean_personal_name_is_structured(name: str) -> bool:
    """
    등록 성씨 + 이름(1~2음절)으로 성·이름 구분이 가능하면 True → 700 1_.
    김치찌개(이름 3음절), 철수(성씨 없음), …김홍홍박사 등은 False → 700 0_.
    """
    raw = (name or "").strip()
    if not raw or not re.search(r"[가-힣]", raw):
        return False

    core_check = re.sub(r"[\s·ㆍ]", "", _strip_pen_name_affixes(raw))
    if core_check in _KOREAN_REAL_NAME_ALLOWLIST:
        return True

    if re.search(r"\s", raw):
        parts = [p for p in re.split(r"\s+", raw) if p]
        if len(parts) >= 2 and re.match(r"^[가-힣]+$", parts[0]):
            if parts[0] in KOREAN_SURNAMES:
                given = "".join(p for p in parts[1:] if re.match(r"^[가-힣]+$", p))
                if len(parts[0]) == 1 and len(parts[0]) + len(given) < 3:
                    return False
                if len(parts[0]) == 2 and len(parts[0]) + len(given) < 4:
                    return False
                return _given_part_looks_valid(given)
        return False

    core = re.sub(r"[\s·ㆍ]", "", _strip_pen_name_affixes(raw))
    if not core or not re.match(r"^[가-힣]+$", core):
        return False

    split = _split_korean_surname_given(core)
    if not split:
        return False
    sur, given = split
    if sur not in KOREAN_SURNAMES:
        return False
    if len(sur) == 1 and len(core) < 3:
        return False
    if len(sur) == 2 and len(core) < 4:
        return False
    return _given_part_looks_valid(given)


def is_korean_person_by_surname(name: str) -> bool:
    """등록 성씨(korean_surnames)로 한국인 저자·옮긴이 여부."""
    n = personal_name_for_700_field((name or "").strip())
    if not re.search(r"[가-힣]", n):
        return False
    core = re.sub(r"[\s·ㆍ]", "", _strip_pen_name_affixes(n))
    if core in _KOREAN_REAL_NAME_ALLOWLIST:
        return True
    split = _split_korean_surname_given(core)
    if split and split[0] in KOREAN_SURNAMES and _given_part_looks_valid(split[1]):
        return True
    parts = [p for p in re.split(r"\s+", n) if p]
    if parts and parts[0] in KOREAN_SURNAMES and re.match(r"^[가-힣]+$", parts[0]):
        return True
    return False


def is_japanese_person_by_surname(name: str) -> bool:
    """등록 성씨(KOREAN_SURNAMES)도, kanji_name·is_east_asian 키워드도 없을 때를 위한 최후
    보조 신호. 한글 음역 첫 토큰이 흔한 일본 성씨(JAPANESE_SURNAMES)와 일치하면 일본인으로 본다."""
    n = personal_name_for_700_field((name or "").strip())
    if not re.search(r"[가-힣]", n):
        return False
    parts = [p for p in re.split(r"\s+", n) if p]
    if not parts:
        return False
    return parts[0] in JAPANESE_SURNAMES


def _name_uses_roman_or_hanja(name: str) -> bool:
    """로마자·한자(가나 제외 CJK) 표기 — 한국인 한글 외자 규칙에서 제외."""
    n = (name or "").strip()
    if re.search(r"[A-Za-z]", n):
        return True
    if re.search(r"[一-鿿㐀-䶿]", n):
        return True
    return False


def _extract_korean_given_part(name: str) -> str | None:
    """등록 성씨 분리 후 이름(뒷부분) 문자열. 실명 예외·분리 불가면 None."""
    n = personal_name_for_700_field((name or "").strip())
    if not re.search(r"[가-힣]", n):
        return None
    core = re.sub(r"[\s·ㆍ]", "", _strip_pen_name_affixes(n))
    if core in _KOREAN_REAL_NAME_ALLOWLIST:
        return None
    if re.search(r"\s", n):
        parts = [p for p in re.split(r"\s+", n) if p]
        if len(parts) >= 2 and parts[0] in KOREAN_SURNAMES:
            given = "".join(p for p in parts[1:] if re.match(r"^[가-힣]+$", p))
            return given or None
        return None
    if not core or not re.match(r"^[가-힣]+$", core):
        return None
    split = _split_korean_surname_given(core)
    if not split or split[0] not in KOREAN_SURNAMES:
        return None
    return split[1]


def _korean_given_syllable_count(name: str) -> int | None:
    """등록 성씨 분리 후 이름(뒷부분) 한글 음절 수. 분리 불가면 None."""
    given = _extract_korean_given_part(name)
    return len(given) if given else None


def _korean_given_not_in_birth_registry(
    name: str,
    *,
    translation_book: bool = False,
    author_info: list | None = None,
) -> bool:
    """
    형식상 한글 개인명(성+이름 1~2음절)인데 출생통계상 plausible하지 않음 → 필명·비정상 의심.
    """
    if not korean_given_names():
        return False
    if _name_uses_roman_or_hanja(name):
        return False
    if not is_korean_person_by_surname(name):
        return False
    if _is_translation_foreign_original_author(name, translation_book, author_info or []):
        return False
    given = _extract_korean_given_part(name)
    if not given or len(given) > 2:
        return False
    return not korean_given_name_is_plausible(given)


def _korean_hangul_short_given_exception(name: str) -> bool:
    """
    한국인 한글명, 성 제외 이름 1~2음절인데 structured만 실패(예: 김강, 조은).
    성 제외 3음절 이상(조은생각, 김아름다운)은 False → 700 0_.
    """
    if not is_korean_person_by_surname(name) or _name_uses_roman_or_hanja(name):
        return False
    if korean_personal_name_is_structured(name):
        return False
    given = _extract_korean_given_part(name)
    if not given or len(given) > 2:
        return False
    if korean_given_names() and not korean_given_name_is_plausible(given):
        return False
    return True


def _is_translation_foreign_original_author(
    name: str,
    translation_book: bool,
    author_info: list,
) -> bool:
    """번역서의 원저(외국인) — 한국인 외자 700 규칙에서 제외."""
    if not translation_book or not author_info:
        return False
    if is_korean_person_by_surname(name):
        return False
    key = _norm_author_lookup_key(name)
    if not key:
        return False
    return any(
        key == _norm_author_lookup_key((ai.get("name") or "").strip())
        for ai in author_info
    )


def marc700_second_indicator(
    name: str,
    role: str,
    *,
    translation_book: bool = False,
    author_info: list | None = None,
    pali_sanskrit_book: bool = False,
) -> str:
    """
    700 두 번째 지시자: 성·이름 구분 가능 → 1, 닉네임·필명·비정상 구조 → 0.
    """
    n = (name or "").strip()
    if not n:
        return "1"
    if n in KNOWN_PEN_NAMES:
        return "0"
    if pali_sanskrit_book and role not in TRANS_ROLES:
        return "0"
    ai = author_info or []
    _short_exc = _korean_hangul_short_given_exception(n)
    if (
        _short_exc
        and not _is_translation_foreign_original_author(n, translation_book, ai)
    ):
        return "1"
    if re.search(r"[A-Za-z]", n) and not re.search(r"[가-힣]", n):
        return "1"
    if re.search(r"[぀-ゟ]", n):
        return "1"
    if re.search(r"[가-힣]", n):
        is_foreign_translator = (
            translation_book
            and role in TRANS_ROLES
            and not is_korean_person_by_surname(n)
        )
        if (
            (_is_translation_foreign_original_author(n, translation_book, ai) or is_foreign_translator)
            and not re.search(r"[A-Za-z぀-ヿ]", n)
        ):
            return "1"
        if _korean_given_not_in_birth_registry(n, translation_book=translation_book, author_info=ai):
            return "0"
        return "1" if korean_personal_name_is_structured(n) else "0"
    return "1"


def build_710(author: dict) -> str:
    return f"$a {author['name'].strip()}"


def _author_info_has_japanese_script(author_info: list[dict]) -> bool:
    """원저 표기(500 후보)에 한자·가나가 하나라도 있으면 일본 등 동아시아 원저로 본다."""
    for ai in author_info:
        kn = (ai.get("kanji_name") or "").strip()
        if kn and re.search(r"[぀-ヿ一-鿿㐀-䶿]", kn):
            return True
    return False


def build_900(
    orig_author_ko: str | None,
    kanji_name: str | None = None,
    orig_author_en: str | None = None,
    translation_book: bool = False,
    japanese_family_book: bool = False,
) -> str | None:
    """
    - 서양 번역: translation_book 이고 japanese_family_book 이 False → 영문 원저 힌트가 있으면 한글 성·이름 도치.
    - 일본 등: japanese_family_book True → 한자·가나 원표기·일본어 음 규칙.
    - 비번역·서양: 영문 원저자명이 있으면 한글 성·이름 도치, 없으면 한글 표기.
    """
    if not orig_author_ko:
        return None
    ko = orig_author_ko.strip()

    if translation_book and not japanese_family_book:
        if orig_author_en:
            rom = orig_author_en.strip()
            latin = bool(re.search(r"[A-Za-z]", rom)) and not re.search(
                r"[가-힣぀-ヿ一-鿿㐀-䶿]", rom,
            )
            if latin:
                reversed_name = korean_name_reverse(ko)
                if reversed_name:
                    return f"900 10 $a {reversed_name}"
        reversed_name = korean_name_reverse(ko)
        if reversed_name:
            return f"900 10 $a {reversed_name}"
        return f"900 10 $a {ko}"

    if japanese_family_book:
        kn = (kanji_name or "").strip()
        if kn:
            gloss = _jp_name_reading_hangul(kn)
            if gloss:
                g0 = re.sub(r"\s+", "", gloss)
                k0 = re.sub(r"\s+", "", ko)
                if g0 != k0:
                    return f"900 10 $a {gloss}"
        if kn and re.search(r"[぀-ヿ一-鿿㐀-䶿]", kn):
            return f"900 10 $a {ko}"
        if orig_author_en:
            rom = orig_author_en.strip()
            latin = bool(re.search(r"[A-Za-z]", rom)) and not re.search(
                r"[가-힣぀-ヿ一-鿿㐀-䶿]", rom,
            )
            if latin:
                reversed_name = korean_name_reverse(ko)
                if reversed_name:
                    return f"900 10 $a {reversed_name}"
        return f"900 10 $a {ko}"

    if kanji_name:
        ktype = kanji_type(kanji_name)
        if ktype == "kanji_kana":
            return None
        if ktype == "kanji_only":
            reading = kanji_to_korean_reading(kanji_name)
            if reading:
                return f"900 10 $a {reading}"
            return None

    if orig_author_en:
        reversed_name = korean_name_reverse(ko)
        if reversed_name:
            return f"900 10 $a {reversed_name}"
        return f"900 10 $a {ko}"

    reversed_name = korean_name_reverse(ko)
    if reversed_name:
        return f"900 10 $a {reversed_name}"
    return None


# ─────────────────────────────────────────────
# 상위 오케스트레이터 — app.py가 호출하는 진입점
# ─────────────────────────────────────────────
def build_500_700_710_900(ctx: dict, *, openai_client=None) -> dict:
    """
    core/fields/marc_245.build_245_family()가 반환한 컨텍스트(ctx)를 이어받아
    500/700/710/900을 생성하고, 246의 최종 노출 여부도 함께 결정한다
    (jp_ctx_for_500이 246·500·700·900을 동시에 좌우하므로 원본과 동일하게 여기서 처리).

    원본: 245/245/app.py의 _isbn_lookup() 중 500/700/710/900 생성 블록 전체.

    Returns:
        {"field_246": str|None, "fields_500": list[str], "fields_700": list[str],
         "fields_710": list[str], "fields_900": list[str]}
    """
    authors             = ctx["authors"]
    orig_title          = ctx["orig_title"]
    orig_author_en      = ctx["orig_author_en"]
    author_info         = ctx["author_info"]
    intro_persons       = ctx["intro_persons"]
    intro_author_pairs  = ctx["intro_author_pairs"]
    translation_book    = ctx["translation_book"]
    category_name       = ctx["category_name"]

    orig_title_has_cjk_or_kana = bool(
        (orig_title or "").strip() and re.search(r"[぀-ヿ一-鿿]", orig_title)
    )

    _author_info_has_japanese_surname = any(
        is_japanese_person_by_surname(ai.get("name", "")) for ai in author_info
    )
    jp_ctx_for_500 = (
        orig_title_has_cjk_or_kana
        or _author_info_has_japanese_script(author_info)
        or _author_info_has_japanese_surname
    )
    pali_sanskrit_book = bool(
        (orig_author_en and _PALI_SANSKRIT_DIACRITICS.search(orig_author_en))
        or (orig_title and _DEVANAGARI_RE.search(orig_title))
    )
    if _author_info_has_japanese_surname:
        for ai in author_info:
            if is_japanese_person_by_surname(ai.get("name", "")):
                ai["is_east_asian"] = True

    # 동아시아 책인데 orig_title이 순수 라틴(로마자 표기)이면 246 19 생략
    _orig_title_for_246 = None if (jp_ctx_for_500 and orig_title and not orig_title_has_cjk_or_kana) else orig_title
    field_246 = build_246(_orig_title_for_246)

    n_missing_kanji = sum(1 for x in author_info if not x.get("kanji_name"))
    allow_roman_500 = bool(orig_author_en) and n_missing_kanji == 1
    roman_once = False
    for ai in author_info:
        ai.pop("_500_script", None)
        ai.pop("_roman_for_900", None)

    orig_names_500_from_intro = try_orig_names_500_from_intro_english_pairs(
        translation_book, jp_ctx_for_500, author_info, intro_author_pairs
    )
    orig_names_500_from_profiles = try_orig_names_500_from_profile_english(
        translation_book, jp_ctx_for_500, author_info
    )
    if orig_names_500_from_intro is not None:
        orig_names_500 = orig_names_500_from_intro
        for ai, en in zip(author_info, orig_names_500_from_intro):
            ai["_500_script"] = "roman"
            ai["_roman_for_900"] = en
    elif orig_names_500_from_profiles is not None:
        orig_names_500 = [
            t for t in orig_names_500_from_profiles if _looks_like_roman_orig_display(t)
        ]
        for ai, tok in zip(author_info, orig_names_500_from_profiles):
            if _looks_like_roman_orig_display(tok):
                ai["_500_script"] = "roman"
                ai["_roman_for_900"] = tok
            else:
                ai["_500_script"] = "orig_korean_700_only"
    else:
        orig_names_500 = []
        for ai in author_info:
            kanji = ai.get("kanji_name")
            if kanji:
                orig_names_500.append(kanji)
                ai["_500_script"] = "cjk"
            elif translation_book and jp_ctx_for_500 and ai.get("name"):
                ai["_500_script"] = "orig_korean_700_only"
            elif allow_roman_500 and orig_author_en and not roman_once:
                orig_names_500.append(orig_author_en.strip())
                ai["_500_script"] = "roman"
                roman_once = True
            elif translation_book and not jp_ctx_for_500 and ai.get("name"):
                if not is_korean_person_by_surname(ai.get("name", "")):
                    ai["_500_script"] = "roman"
        if not orig_names_500 and orig_author_en and not jp_ctx_for_500:
            blob = orig_author_en.strip()
            chunks = [x.strip() for x in re.split(r",\s*", blob) if x.strip()]
            if len(chunks) >= 2 and author_info:
                for idx, ai in enumerate(author_info):
                    if idx < len(chunks):
                        orig_names_500.append(chunks[idx])
                        ai["_500_script"] = "roman"
                        ai["_roman_for_900"] = chunks[idx]
                    elif ai.get("name"):
                        if translation_book and not jp_ctx_for_500:
                            ai["_500_script"] = "orig_korean_700_only"
                        else:
                            orig_names_500.append(ai["name"].strip())
                            ai["_500_script"] = "hangul_western"
            else:
                if (
                    len(chunks) == 1
                    and len(author_info) >= 2
                    and translation_book
                    and not jp_ctx_for_500
                    and len(author_info) > len(chunks)
                ):
                    orig_names_500.clear()
                    orig_names_500.append(blob)
                    for idx, ai in enumerate(author_info):
                        if idx == 0:
                            ai["_500_script"] = "roman"
                            ai["_roman_for_900"] = blob
                        elif ai.get("name"):
                            if not is_korean_person_by_surname(ai.get("name", "")):
                                ai["_500_script"] = "roman"
                            else:
                                ai["_500_script"] = "orig_korean_700_only"
                else:
                    orig_names_500.append(blob)
                    if author_info:
                        if len(chunks) == 1 and len(author_info) >= 2 and translation_book and not jp_ctx_for_500:
                            for ai in author_info:
                                ai["_500_script"] = "orig_korean_700_only"
                        elif len(author_info) == 1:
                            author_info[0]["_500_script"] = "roman"
                            author_info[0]["_roman_for_900"] = blob

    if translation_book and not jp_ctx_for_500 and orig_names_500:
        orig_names_500 = [t for t in orig_names_500 if not _orig_500_token_has_hangul(t)]
    if jp_ctx_for_500 and orig_names_500:
        orig_names_500 = [t for t in orig_names_500 if not _is_hangul_only_orig_name_for_500(t)]
    field_500_orig = f"500 __ $a 원저자명: {', '.join(orig_names_500)}" if orig_names_500 else None
    fields_500: list[str] = []
    if field_500_orig:
        fields_500.append(field_500_orig)
    fields_500.extend(build_500_role_notes(authors))

    # ── 700 ──────────────────────────────────────────────
    persons    = [a for a in authors if not a["is_org"]]
    intro_non_org = [p for p in intro_persons if not p.get("is_org")]
    has_translator = any(a["role"] in TRANS_ROLES for a in authors)
    if has_translator and len(intro_non_org) >= max(2, len(persons)):
        persons_for_700 = intro_non_org
    else:
        persons_for_700 = persons
    fields_700: list[str] = []
    first_ai   = author_info[0] if author_info else None
    skip_first_person_700 = False
    _llm_name_context_parts = []
    if orig_title:
        _llm_name_context_parts.append(f"원서명: {orig_title}")
    if category_name:
        _llm_name_context_parts.append(f"분야: {category_name}")
    _llm_name_context = " / ".join(_llm_name_context_parts)
    n_prof_en = sum(1 for ai in author_info if (ai.get("english_name") or "").strip())
    western_700_english = (
        translation_book
        and not jp_ctx_for_500
        and bool(author_info)
        and n_prof_en >= len(author_info) - 1
    )
    if western_700_english:
        ko_to_en = {
            _norm_author_lookup_key((ai.get("name") or "").strip()): (ai.get("english_name") or "").strip()
            for ai in author_info
        }
        for a in persons_for_700:
            ind = marc700_second_indicator(
                a["name"], a.get("role", ""),
                translation_book=translation_book, author_info=author_info,
                pali_sanskrit_book=pali_sanskrit_book,
            )
            if a.get("role") in TRANS_ROLES:
                fields_700.append(f"700 {ind}_ {build_700(a, context=_llm_name_context, openai_client=openai_client)}")
            else:
                en = ko_to_en.get(_norm_author_lookup_key((a.get("name") or "").strip()))
                if en:
                    fields_700.append(f"700 {ind}_ $a {english_name_reverse(en)}")
                    skip_first_person_700 = True
                elif (
                    orig_author_en
                    and re.search(r"[A-Za-z]", orig_author_en)
                    and not re.search(r"[가-힣぀-ヿ一-鿿]", orig_author_en)
                    and not skip_first_person_700
                ):
                    fields_700.append(f"700 {ind}_ $a {english_name_reverse(orig_author_en.strip())}")
                    skip_first_person_700 = True
                else:
                    fields_700.append(f"700 {ind}_ {build_700(a, context=_llm_name_context, openai_client=openai_client)}")
    else:
        _orig_en_chunks = [x.strip() for x in (orig_author_en or "").split(",") if x.strip()]
        _handled_700_ko: set[str] = set()
        if (
            len(_orig_en_chunks) >= 2
            and len(_orig_en_chunks) == len(author_info)
            and all(re.search(r"[A-Za-z]", c) for c in _orig_en_chunks)
        ):
            for en_chunk, ai_entry in zip(_orig_en_chunks, author_info):
                ind = marc700_second_indicator(
                    ai_entry["name"], ai_entry.get("role", ""),
                    translation_book=translation_book, author_info=author_info,
                    pali_sanskrit_book=pali_sanskrit_book,
                )
                fn = (ai_entry.get("name") or "").strip()
                if fn and (ai_entry.get("is_east_asian") or orig_title_has_cjk_or_kana or ai_entry.get("kanji_name")):
                    fields_700.append(f"700 1_ $a {personal_name_for_700_field(fn)}")
                else:
                    fields_700.append(f"700 {ind}_ $a {english_name_reverse(en_chunk.strip())}")
                _handled_700_ko.add(ai_entry["name"].strip())
        if first_ai and orig_author_en and not _handled_700_ko:
            rom = orig_author_en.strip()
            latin = bool(re.search(r"[A-Za-z]", rom)) and not re.search(
                r"[가-힣぀-ヿ一-鿿㐀-䶿]", rom,
            )
            sc = rom.replace(";", ",")
            n_comma = sc.count(",")
            looks_anthology_rom = n_comma >= 2 or (n_comma >= 1 and len(rom) > 140)
            looks_truncated_rom = len(rom) <= 10 and rom.count(".") >= 1 and n_comma == 0 and len(rom.split()) <= 2
            if latin and (not first_ai.get("kanji_name") or translation_book):
                fn = (first_ai.get("name") or "").strip()
                mixed_lat_ko = bool(
                    fn and re.search(r"[A-Za-z]", fn) and re.search(r"[가-힣]", fn)
                )
                if looks_anthology_rom or looks_truncated_rom or mixed_lat_ko:
                    pass
                elif first_ai.get("is_east_asian") or orig_title_has_cjk_or_kana or first_ai.get("kanji_name"):
                    if fn:
                        fields_700.append(f"700 1_ $a {personal_name_for_700_field(fn)}")
                    skip_first_person_700 = True
                else:
                    fields_700.append(f"700 1_ $a {english_name_reverse(rom)}")
                    skip_first_person_700 = True
            elif (
                translation_book
                and not latin
                and not first_ai.get("kanji_name")
                and not first_ai.get("is_east_asian")
                and not orig_title_has_cjk_or_kana
            ):
                kr = korean_name_reverse(first_ai["name"].strip())
                if kr:
                    fields_700.append(f"700 1_ $a {kr}")
                    skip_first_person_700 = True
        elif (
            first_ai
            and translation_book
            and not orig_author_en
            and (first_ai.get("kanji_name") or first_ai.get("is_east_asian") or orig_title_has_cjk_or_kana)
        ):
            fn = (first_ai.get("name") or "").strip()
            if fn:
                fields_700.append(f"700 1_ $a {personal_name_for_700_field(fn)}")
                skip_first_person_700 = True
        elif (
            first_ai
            and translation_book
            and not first_ai.get("kanji_name")
            and not orig_author_en
            and not first_ai.get("is_east_asian")
            and not orig_title_has_cjk_or_kana
        ):
            kr = korean_name_reverse(first_ai["name"].strip())
            if kr:
                fields_700.append(f"700 1_ $a {kr}")
                skip_first_person_700 = True

        first_ko_name = (first_ai or {}).get("name", "").strip()
        dbg(f"[700] persons_for_700={[a['name'] for a in persons_for_700]} skip={skip_first_person_700} handled={_handled_700_ko} first_ko={first_ko_name!r}")
        for a in persons_for_700:
            if a["name"].strip() in _handled_700_ko:
                continue
            if skip_first_person_700 and a["name"].strip() == first_ko_name:
                skip_first_person_700 = False
                continue
            ind = marc700_second_indicator(
                a["name"], a.get("role", ""),
                translation_book=translation_book, author_info=author_info,
                pali_sanskrit_book=pali_sanskrit_book,
            )
            ai_match = next(
                (x for x in author_info if (x.get("name") or "").strip() == a["name"].strip()), None,
            )
            en_prof = (ai_match.get("english_name") or "").strip() if ai_match else ""
            if ai_match and (
                jp_ctx_for_500
                or orig_title_has_cjk_or_kana
                or ai_match.get("kanji_name")
                or ai_match.get("is_east_asian")
            ):
                fields_700.append(f"700 {ind}_ $a {personal_name_for_700_field(a['name'].strip())}")
            elif en_prof and re.search(r"[A-Za-z]", en_prof):
                fields_700.append(f"700 {ind}_ $a {english_name_reverse(en_prof)}")
            else:
                fields_700.append(f"700 {ind}_ {build_700(a, context=_llm_name_context, openai_client=openai_client)}")

    # ── 710 ──────────────────────────────────────────────
    orgs = [a for a in authors if a["is_org"]]
    fields_710 = [f"710 0_ {build_710(a)}" for a in orgs]

    # ── 900 ──────────────────────────────────────────────
    fields_900: list[str] = []
    jp_book_for_roman = orig_title_has_cjk_or_kana or (
        bool(author_info) and any(ai.get("is_east_asian") for ai in author_info)
    )
    jp_family_book = (
        jp_book_for_roman
        or _author_info_has_japanese_script(author_info)
        or orig_title_has_cjk_or_kana
    )
    emit_900 = bool(author_info) and (
        field_500_orig
        or any(
            (ai.get("_500_script") or "") in ("roman", "cjk", "hangul", "hangul_western")
            for ai in author_info
        )
    )
    if emit_900 and jp_ctx_for_500:
        emit_900 = field_500_orig is not None or any(
            ai.get("_500_script") == "cjk" for ai in author_info
        )
    if emit_900:
        for idx, ai in enumerate(author_info):
            if ai.get("_500_script") == "cjk":
                kn = (ai.get("kanji_name") or "").strip()
                kn_parts = [p.strip() for p in re.split(r"[,、]", kn) if p.strip()]
                for kn_part in kn_parts:
                    kn_compact = re.sub(r"\s+", "", kn_part)
                    if not kn_compact or kanji_type(kn_compact) != "kanji_only":
                        continue
                    reading = kanji_to_korean_reading(kn_compact)
                    if reading:
                        fields_900.append(f"900 10 $a {reading}")
                continue
            if ai.get("_500_script") == "hangul":
                if jp_ctx_for_500:
                    continue
                f900 = build_900(
                    ai["name"], ai.get("kanji_name"), orig_author_en=None,
                    translation_book=translation_book, japanese_family_book=False,
                )
                if f900:
                    fields_900.append(f900)
                continue
            if ai.get("_500_script") == "orig_korean_700_only":
                continue
            if ai.get("_500_script") == "hangul_western":
                ko = (ai.get("name") or "").strip()
                rev = korean_name_reverse(ko)
                if rev:
                    fields_900.append(f"900 10 $a {rev}")
                elif ko:
                    fields_900.append(f"900 10 $a {ko}")
                continue
            if ai.get("_500_script") != "roman":
                continue
            en_for_900 = ai.get("_roman_for_900")
            if (
                not en_for_900
                and orig_author_en
                and not ai.get("kanji_name")
                and not jp_book_for_roman
                and (len(author_info) <= 1 or idx == 0)
            ):
                en_for_900 = orig_author_en
            if not en_for_900:
                continue
            f900 = build_900(
                ai["name"], ai["kanji_name"], orig_author_en=en_for_900,
                translation_book=translation_book, japanese_family_book=jp_family_book,
            )
            if f900:
                fields_900.append(f900)
        for ai in author_info:
            ai.pop("_500_script", None)
            ai.pop("_roman_for_900", None)

    return {
        "field_246":  field_246,
        "fields_500": fields_500,
        "fields_700": fields_700,
        "fields_710": fields_710,
        "fields_900": fields_900,
    }
