"""
core/text_utils.py
245 계열(245/246/500/700/710/900/940) 필드 생성에 공통으로 쓰이는 순수 텍스트/이름
유틸리티. 원본: 245/245/app.py 상단 "상수"·"공통 유틸" 섹션.

의도적으로 의존성이 없는 leaf 모듈이다 — api/aladin_scraper.py와
core/fields/marc_245.py, core/fields/marc_500_700_710.py가 모두 이 모듈을
가져다 쓰는데, aladin_scraper가 marc_245의 함수를 쓰고 marc_245가 다시
aladin_scraper의 함수(scrape_aladin_product)를 쓰는 순환 참조가 생기므로,
공용 텍스트 유틸은 둘 다에서 안전하게 import할 수 있는 이 leaf 모듈에 모아둔다.
"""

from __future__ import annotations

import re

try:
    import hanja
    HANJA_AVAILABLE = True
except ImportError:
    HANJA_AVAILABLE = False

try:
    import jaconv
    import pykakasi

    _PYKAKASI_JACONV = True
except ImportError:
    _PYKAKASI_JACONV = False


# ============================================================
# 상수
# ============================================================
ORG_KEYWORDS = (
    "협회", "학회", "위원회", "연구소", "연구원", "연구회", "센터",
    "재단", "법인", "기관", "청", "공단", "공사",
    "협의회", "연합회", "연맹", "조합",
    "대학교", "대학", "학교", "출판사", "출판부", "편집부",
    "association", "institute", "council", "committee",
    "foundation", "university", "society", "organization",
    "corp", "inc", "ltd",
)

ROLE_LABEL = {
    "옮긴이": "옮긴이", "역자": "옮긴이", "번역": "옮긴이",
    "그린이": "그린이", "그림": "그린이", "일러스트": "그린이",
    "사진": "사진", "감수": "감수", "편저": "편저", "편역": "편역",
    "엮은이": "엮은이", "편집": "엮은이", "해설": "해설",
    "저자": "지은이", "글": "지은이", "글쓴이": "지은이", "지은이": "지은이",
    "원작": "원작",
}

# 245 책임표시용 역할어 동사형 매핑
_ROLE_VERB_245: dict[str, str] = {
    "지은이": "지음",  "저자":   "지음",  "글쓴이": "지음",  "": "지음",
    "옮긴이": "옮김",  "역자":   "옮김",  "번역":   "옮김",
    "엮은이": "엮음",  "편집":   "엮음",
    "편저":   "편저",  "편역":   "편역",
    "그린이": "그림",
    # 아래는 그대로 표기
    "글":     "글",    "그림":   "그림",  "원작":   "원작",
    "일러스트": "일러스트",  "드로잉": "드로잉",  "그래픽": "그래픽",
    "사진":   "사진",  "해설":   "해설",
}

PRIMARY_ROLES = {"지은이", "저자", "글", "글쓴이", ""}

# 245 책임표시 제외 → 500 주기로 출력 (예: 500 __ $a 감수: …)
ROLES_EXCLUDED_FROM_245 = frozenset({"감수"})

TRANS_ROLES = {"옮긴이", "역자", "번역", "편역"}

# 등록 성씨로 안 잡히는 한글 표기 중, 실제로는 외국인 본명 음역이 아니라 한국인이 쓰는
# 필명/브랜드명임이 확인된 이름 → marc700_second_indicator에서 무조건 700 0_ 처리.
KNOWN_PEN_NAMES = frozenset({"하와이 대저택", "다숲", "느린호수"})

# 저자 문자열 괄호 안이 역할만인 경우(원문 표기 아님)
_KO_AUTHOR_PAREN_SKIP = frozenset({
    "지은이", "저자", "글", "글쓴이", "원작", "옮긴이", "역자", "번역", "편역",
    "그림", "그린이", "일러스트", "편저", "해설", "엮은이", "편집", "감수",
    "사진", "총서", "공저", "공동", "외", "외1", "외2",
})

EAST_ASIA_KEYWORDS = (
    "일본 출생", "일본 출신", "일본인", "중국 출생", "중국 출신", "중국인",
    "대만", "홍콩", "도쿄", "오사카", "교토", "이와테", "홋카이도", "오키나와",
    "나고야", "후쿠오카", "삿포로", "고베", "요코하마", "베이징", "상하이",
    "광저우", "타이베이", "東京", "大阪", "京都", "北京", "上海",
)

SUBTITLE_NOISE_PATTERNS = [
    r"\d{4}\s*일본\s*서점대상.*",
    r"\d{4}\s*서점대상.*",
    r"일본\s*서점대상.*",
    r"\d{4}\s*본야도이상.*",
    r".*아쿠타가와\s*상.*",
    r".*아쿠타가와상.*",
    r".*수상작\s*$",
    r".*수상\s*$",
    r".*수상작$",
    r".*수상$",
    r".*대상\s*\d+위.*",
    r".*베스트셀러.*",
]

# 한자 음독 딕셔너리
HANJA_READING: dict[str, str] = {
    "村":"촌","上":"상","春":"춘","樹":"수","安":"안","西":"서","水":"수","丸":"환",
    "阿":"아","部":"부","曉":"효","子":"자","山":"산","川":"천","田":"전","中":"중",
    "大":"대","小":"소","木":"목","本":"본","森":"삼","林":"림","原":"원","野":"야",
    "井":"정","石":"석","金":"금","藤":"등","松":"송","竹":"죽","梅":"매","花":"화",
    "鳥":"조","魚":"어","馬":"마","龍":"룡","鳳":"봉","虎":"호","鶴":"학","一":"일",
    "二":"이","三":"삼","四":"사","五":"오","六":"육","七":"칠","八":"팔","九":"구",
    "十":"십","百":"백","千":"천","萬":"만","東":"동","南":"남","北":"북","左":"좌",
    "右":"우","前":"전","後":"후","内":"내","外":"외","天":"천","地":"지","人":"인",
    "火":"화","月":"월","日":"일","年":"년","生":"생","愛":"애","心":"심","道":"도",
    "太":"태","正":"정","新":"신","古":"고","長":"장","短":"단","高":"고","低":"저",
    "明":"명","暗":"암","光":"광","影":"영","白":"백","黑":"흑","赤":"적","靑":"청",
    "黄":"황","紫":"자","緑":"록","美":"미","善":"선","眞":"진","幸":"행","福":"복",
    "壽":"수","喜":"희","怒":"노","哀":"애","樂":"락","平":"평","和":"화","友":"우",
    "王":"왕","臣":"신","民":"민","文":"문","武":"무","詩":"시","歌":"가","書":"서",
    "音":"음","海":"해","空":"공","星":"성","雨":"우","雪":"설","風":"풍","雲":"운",
    "草":"초","葉":"엽","根":"근","枝":"지","幹":"간",
    "暁":"효",
}

# 알라딘·일부 DB의 일본 인명 한자 오표기 보정 (曉→暁 등)
_JP_KANJI_CHAR_FIX: dict[str, str] = {
    "曉": "暁",
}

# 팔리어·산스크리트어 전용 발음 구별 부호 — 원저자명에 있으면 성·이름 구분 없는 단일 이름으로 간주
_PALI_SANSKRIT_DIACRITICS = re.compile(
    r"[āīūṭṇḍṃḥśṣḷĀĪŪṬṆḌṂḤŚṢḶṅṄñÑṙṚ]"
)
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# 스페인/중남미 이름 (라틴) — 복합 성씨 감지용
_SPANISH_GIVEN_NAMES_LATIN = frozenset({
    "Pablo", "Gabriel", "Jorge", "Luis", "Miguel", "Carlos", "Manuel", "Juan",
    "Pedro", "Alfredo", "Rafael", "Fernando", "Eduardo", "Antonio", "José", "Jose",
    "Roberto", "Ernesto", "Julio", "Mario", "Enrique", "Salvador", "Francisco",
    "Rubén", "Ruben", "Augusto", "Ricardo", "Alberto", "Adolfo", "Arturo",
    "Ignacio", "Gustavo", "Benito", "Hernán", "Hernan", "Simón", "Simon",
    "Sebastián", "Sebastian", "Diego", "Rodrigo", "Andrés", "Andres",
    "Alejandro", "Nicolás", "Nicolas", "Daniel", "Iván", "Ramón", "Ramon",
    "Álvaro", "Alvaro", "Javier", "Sergio", "César", "Cesar", "Octavio",
    "Isabel", "Carmen", "María", "Maria", "Laura", "Sofía", "Sofia", "Ana",
    "Lucía", "Lucia", "Rosa", "Elena", "Pilar", "Dolores", "Margarita",
    "Beatriz", "Patricia", "Cristina", "Teresa", "Alicia", "Gloria",
    "Julia", "Mónica", "Monica", "Clara", "Claudia", "Silvia", "Catalina",
    "Mercedes", "Consuelo", "Amparo", "Lola",
})

# 스페인/중남미 이름 (한글 음역) — 복합 성씨 감지용
_SPANISH_GIVEN_NAMES_KOREAN = frozenset({
    "파블로", "가브리엘", "호르헤", "루이스", "미겔", "카를로스", "마누엘", "후안",
    "페드로", "알프레도", "라파엘", "페르난도", "에두아르도", "안토니오", "호세",
    "로베르토", "에르네스토", "훌리오", "마리오", "엔리케", "살바도르", "프란시스코",
    "루벤", "아우구스토", "리카르도", "알베르토", "아돌포", "아르투로", "이그나시오",
    "구스타보", "베니토", "에르난", "시몬", "세바스티안", "디에고", "로드리고",
    "안드레스", "알레한드로", "니콜라스", "다니엘", "라몬", "알바로",
    "하비에르", "세르히오", "세사르", "옥타비오",
    "이사벨", "카르멘", "마리아", "라우라", "소피아", "아나", "루시아", "로사",
    "엘레나", "필라르", "돌로레스", "마르가리타", "베아트리스", "파트리시아",
    "크리스티나", "테레사", "알리시아", "글로리아", "훌리아", "모니카",
    "클라라", "클라우디아", "실비아", "카탈리나", "메르세데스",
})

# 대문자 입자: 뒤에 오는 단어와 함께 복합 성씨를 구성
_SURNAME_PARTICLES_UPPER = frozenset({
    "De", "Du", "Des", "Le", "La", "Les", "Von", "Van",
    "Di", "Della", "Del", "Da", "El", "Al",
})

_HONORIFIC_PREFIX_RE = re.compile(
    r"^(?:Sir|Dame|Lord|Lady|Baron(?:ess)?|Earl|Count(?:ess)?|"
    r"Dr\.?|Prof\.?|Professor|Rev\.?|Reverend|"
    r"Mr\.?|Mrs\.?|Ms\.?|Miss)\s+",
    re.IGNORECASE,
)


def _normalize_jp_kanji(s: str) -> str:
    t = (s or "").strip()
    for wrong, right in _JP_KANJI_CHAR_FIX.items():
        t = t.replace(wrong, right)
    return t


# ============================================================
# 공통 유틸
# ============================================================
def is_org(name: str) -> bool:
    n = name.strip()
    if any(kw in n.lower() for kw in ORG_KEYWORDS):
        return True
    # 일본 출판사·기관 음역: 한글 3음절 이상이고 '사'(社)로 끝남 (강담사·주부의벗사·문예춘추사 등)
    hangul_syllables = [c for c in n if "가" <= c <= "힣"]
    if len(hangul_syllables) >= 3 and n.endswith("사"):
        return True
    return False


def to_title_case(word: str) -> str:
    return "-".join(part.capitalize() for part in word.split("-"))


def remove_series(title: str) -> str:
    """괄호로 묶인 총서명 제거: "젊은 베르테르의 슬픔 (먼슬리 클래식)" → "젊은 베르테르의 슬픔" """
    return re.sub(r"\s*\([^)]+\)\s*$", "", title).strip()


def remove_year(text: str) -> str:
    """연도 괄호 제거: "Title (1774년)" → "Title" """
    return re.sub(r"\s*\(\d{4}년?\)\s*$", "", text).strip()


def clean_subtitle(subtitle: str) -> str:
    """부제목에서 마케팅/수상 키워드 제거. 수상작·특정 문학상 한 줄은 부표제로 두지 않음."""
    if not subtitle:
        return subtitle
    st = subtitle.strip()
    if re.search(r"아쿠타가와", st):
        return ""
    if re.search(
        r"제\s*\d+\s*회.*(나오키|본야도|서점\s*대상|일본\s*서점|아쿠타가와)",
        st,
        re.I | re.S,
    ):
        return ""
    if re.search(r"(수상\s*작|수상작)\s*$", st, re.I):
        return ""
    for pattern in SUBTITLE_NOISE_PATTERNS:
        if re.search(pattern, st, re.I | re.S):
            return ""
    for sep in [" · ", " - ", " | ", " / "]:
        if sep in st:
            parts = st.split(sep)
            cleaned = [p for p in parts if not any(re.search(pat, p.strip(), re.I | re.S) for pat in SUBTITLE_NOISE_PATTERNS)]
            return sep.join(cleaned).strip() if cleaned else ""
    return st


def strip_award_suffix_from_title(title: str) -> str:
    """표제 문자열에만 붙은 ' : 제○회 … 수상' 등은 부표제($b)가 아니므로 표제에서 제거."""
    t = title.strip()
    for sep in (" - ", " – ", " : ", "：", ":"):
        if sep not in t:
            continue
        a, b = t.split(sep, 1)
        bs = b.strip()
        if not bs:
            continue
        if clean_subtitle(bs) == "":
            return a.strip()
    return t


def strip_honorifics(name: str) -> str:
    """이름 앞 경칭(Sir, Dame, Dr. 등) 제거: 'Sir Arthur Stanley Eddington' → 'Arthur Stanley Eddington'"""
    return _HONORIFIC_PREFIX_RE.sub("", name).strip()


def korean_name_reverse(name: str) -> str | None:
    """서양식 한글 표기 역순: "요한 볼프강 폰 괴테" → "괴테, 요한 볼프강 폰" """
    if not re.search(r"[가-힣]", name):
        return None
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def english_name_reverse(name: str) -> str:
    """
    서양 저자명 도치.
    - 소문자 입자(de, von, van 등): 이름 쪽에 유지
    - 대문자 입자(De, Le, Van 등): 성씨의 일부로 처리
    """
    parts = (name or "").strip().split()
    if len(parts) < 2:
        return name
    if len(parts) == 2:
        return f"{parts[-1]}, {parts[0]}"

    if parts[-2] in _SURNAME_PARTICLES_UPPER:
        surname = f"{parts[-2]} {parts[-1]}"
        given   = " ".join(parts[:-2])
        return f"{surname}, {given}" if given else surname

    first = parts[0].rstrip(".,")
    second = parts[1].rstrip(".,")
    if first in _SPANISH_GIVEN_NAMES_LATIN and second not in _SPANISH_GIVEN_NAMES_LATIN:
        surname = " ".join(p.rstrip(".,") for p in parts[1:])
        return f"{surname}, {first}"

    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def _looks_like_roman_orig_display(s: str) -> bool:
    """500 토큰이 로마자 원저 표기인지(한글·한자·가나 없음)."""
    t = (s or "").strip()
    if not t:
        return False
    if re.search(r"[가-힣぀-ヿ一-鿿㐀-䶿]", t):
        return False
    return bool(re.search(r"[A-Za-z]", t))


def _orig_500_token_has_hangul(s: str) -> bool:
    """500 목록에 넣으면 안 되는 한글 표기(서양 번역권)."""
    return bool(re.search(r"[가-힣]", (s or "").strip()))


def _is_hangul_only_orig_name_for_500(s: str) -> bool:
    """한글 음역 표기만(한자·가나·로마자 없음) — 500 원저자명에 넣지 않음."""
    t = (s or "").strip()
    if not t or not re.search(r"[가-힣]", t):
        return False
    if re.search(r"[぀-ヿ一-鿿A-Za-z]", t):
        return False
    return True


def kanji_type(name: str) -> str:
    """한자명 문자 구성 판별"""
    has_kanji    = bool(re.search(r"[一-鿿㐀-䶿]", name))
    has_hiragana = bool(re.search(r"[぀-ゟ]", name))
    has_katakana = bool(re.search(r"[゠-ヿ]", name))
    has_kana     = has_hiragana or has_katakana
    if has_kanji and has_kana:
        return "kanji_kana"
    elif has_kanji:
        return "kanji_only"
    elif has_kana:
        return "kana_only"
    else:
        return "other"


def kanji_to_korean_reading(name: str) -> str | None:
    """한자 이름을 한국 음독으로 변환: 村上春樹 → 촌상춘수"""
    if HANJA_AVAILABLE:
        try:
            result = hanja.translate(name, "substitution")
            if re.search(r"[가-힣]", result):
                return result
        except Exception:
            pass
    result = []
    for ch in name:
        if ch in HANJA_READING:
            result.append(HANJA_READING[ch])
        elif re.match(r"[一-鿿㐀-䶿]", ch):
            return None
    return "".join(result) if result else None


def _build_katakana_hangul_maps() -> tuple[dict[str, str], dict[str, str]]:
    yo: dict[str, str] = {
        "キャ": "캬", "キュ": "큐", "キョ": "쿄", "シャ": "샤", "シュ": "슈", "ショ": "쇼",
        "チャ": "차", "チュ": "추", "チョ": "초", "ニャ": "냐", "ニュ": "뉴", "ニョ": "뇨",
        "ヒャ": "햐", "ヒュ": "휴", "ヒョ": "효", "ミャ": "먀", "ミュ": "뮤", "ミョ": "묘",
        "リャ": "랴", "リュ": "류", "リョ": "료", "ギャ": "갸", "ギュ": "규", "ギョ": "교",
        "ジャ": "쟈", "ジュ": "주", "ジョ": "조", "ヂャ": "쟈", "ヂュ": "주", "ヂョ": "조",
        "ビャ": "뱌", "ビュ": "뷰", "ビョ": "뵤", "ピャ": "퍄", "ピュ": "표", "ピョ": "표",
        "デャ": "댜", "デュ": "듀", "デョ": "됴",
    }
    one: dict[str, str] = {}
    one.update(zip("アイウエオ", "아이우에오"))
    one.update(zip("カキクケコ", "카키크케코"))
    one.update(zip("ガギグゲゴ", "가기구게고"))
    one.update(zip("サシスセソ", "사시스세소"))
    one.update(zip("ザジズゼゾ", "자지즈제조"))
    one.update(zip("タチツテト", "타치츠테토"))
    one.update(zip("ダヂヅデド", "다지즈데도"))
    one.update(zip("ナニヌネノ", "나니누네노"))
    one.update(zip("ハヒフヘホ", "하히후헤호"))
    one.update(zip("バビブベボ", "바비부베보"))
    one.update(zip("パピプペポ", "파피푸페포"))
    one.update(zip("マミムメモ", "마미무메모"))
    one.update(zip("ヤユヨ", "야유요"))
    one.update(zip("ラリルレロ", "라리루레로"))
    one["ワ"] = "와"
    one["ヲ"] = "오"
    one["ン"] = "응"
    one["ヴ"] = "브"
    one["ヵ"] = "카"
    one["ヶ"] = "케"
    return yo, one


_KATA_YOON2, _KATA1 = _build_katakana_hangul_maps()


def _katakana_to_hangul(kata: str) -> str | None:
    if not kata:
        return None
    out: list[str] = []
    i = 0
    while i < len(kata):
        c = kata[i]
        if c in " \t\n　":
            i += 1
            continue
        if c in "ッっ":
            i += 1
            continue
        if c == "ー":
            i += 1
            continue
        if i + 1 < len(kata):
            pair = kata[i : i + 2]
            if pair in _KATA_YOON2:
                out.append(_KATA_YOON2[pair])
                i += 2
                continue
        if c in _KATA1:
            out.append(_KATA1[c])
            i += 1
            continue
        if c in "ァィゥェォャュョヮ":
            i += 1
            continue
        i += 1
    s = "".join(out)
    return s if s else None


def _jp_name_reading_hangul(script: str) -> str | None:
    """
    500의 일본 원문 표기(한자·가나) → 일본어 음을 가타카나 경유 한글로(900용, 245 한글 음역과 구분).
    """
    if not _PYKAKASI_JACONV:
        return None
    s = (script or "").strip()
    if not s:
        return None
    s = s.translate({0x9751: 0x9752})  # 靑 → 青
    try:
        kks = pykakasi.kakasi()
        kks.setMode("J", "H")
        kks.setMode("K", "H")
        kks.setMode("H", "H")
        hira = kks.getConverter().do(s)
    except Exception:
        return None
    if not hira or re.search(r"[一-鿿㐀-䶿]", hira):
        return None
    kata = jaconv.hira2kata(hira)
    return _katakana_to_hangul(kata)


def aladin_item_description_blob(item: dict) -> str:
    """알라딘 ItemLookUp 본문 — 상품 페이지 크롤링 실패 시 원저자 영문 힌트용."""
    parts: list[str] = []
    for key in ("fullDescription2", "fullDescription", "description"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    sub = item.get("subInfo")
    if isinstance(sub, dict):
        for val in sub.values():
            if isinstance(val, str) and len(val) > 20:
                parts.append(val)
    return "\n".join(parts)


def extract_english_author_after_korean_paren(text: str, limit: int = 16000) -> str | None:
    """'한글명 (English Name)' 패턴에서 영문명 추출 (상세설명·저자소개 등)."""
    if not text:
        return None
    chunk = text[:limit]
    for m in re.finditer(
        r"[가-힣][가-힣\s]*\(([A-Z][a-z]+(?:\s+[A-Za-z.\-\']+){1,})\)",
        chunk,
    ):
        candidate = re.sub(r"\s+", " ", m.group(1)).strip()
        words = candidate.split()
        if len(words) >= 2 and all(re.match(r"^[A-Za-z.\-\']+$", w) for w in words):
            return candidate
    return None


def _extract_paren_english_names_from_blob(text: str, limit: int = 220000) -> list[str]:
    """
    상세설명 등에서 '한글… (English…)' 괄호 안 영문명을 순서대로 수집.
    합집·다수 원저자(영문) 보강용. 이니셜 포함 단일 토큰도 허용.
    """
    if not text:
        return []
    chunk = text[:limit]
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"[가-힣][^()\n]{0,52}\(\s*([^)\n]{2,160})\s*\)",
        chunk,
    ):
        inner = re.sub(r"\s+", " ", m.group(1)).strip()
        if not inner or re.search(r"[가-힣぀-ヿ一-鿿]", inner):
            continue
        if not re.search(r"[A-Za-z]", inner):
            continue
        for piece in re.split(r",\s*", inner):
            p = piece.strip()
            if len(p) < 2:
                continue
            key = p.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def parse_authors(author_str: str) -> list[dict]:
    """
    알라딘 author 문자열 파싱.
    '저1, 저2, …, 저N (지은이), 역자 (옮긴이)' 처럼 앞 이름에는 (역할)이 없고
    마지막 저자에만 (지은이)가 붙는 합저 표기가 많음.
    """
    author_str = (author_str or "").strip()
    if not author_str:
        return []

    parts   = [p.strip() for p in author_str.split(",") if p.strip()]
    result: list[dict] = []
    pending: list[str] = []

    for part in parts:
        role: str | None = None
        name_part = part
        if part.endswith(")") and "(" in part:
            open_i = part.rfind("(")
            if open_i > 0:
                inner = part[open_i + 1 : -1].strip()
                cand = part[:open_i].strip()
                if cand and inner:
                    name_part, role = cand, inner
        if role is not None:
            for pn in pending:
                result.append({"name": pn, "role": role, "is_org": is_org(pn)})
            pending.clear()
            result.append({"name": name_part, "role": role, "is_org": is_org(name_part)})
        else:
            pending.append(part)

    for pn in pending:
        result.append({"name": pn.strip(), "role": "", "is_org": is_org(pn)})

    return result


def to_isbn13(isbn: str) -> str:
    if len(isbn) == 13:
        return isbn
    base  = "978" + isbn[:9]
    check = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
    return base + str((10 - check % 10) % 10)
