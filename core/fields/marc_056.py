"""
core/fields/marc_056.py
056(KDC 한국십진분류기호) 필드 생성 — 딥러닝팀 model8(klue/roberta-large 파인튜닝) 기반.

이 모듈은 "입력문 조립 → 모델 호출 → Top-3 + 신뢰도 → 056 조립"만 담당하고,
모델 로딩·추론 자체는 core/kdc_model.py가 맡는다(056 추진안 4절 "입력 전처리·모델
호출·Top-3 출력의 공통 추론 모듈화" — model9/model10으로 교체할 때 이 파일은 그대로 둔다).

입력문 조립은 학습 전처리 스크립트(prepare_data_v8.py의 build_text)를 그대로 재현한다.
추론 입력이 학습 입력과 한 글자라도 다르면 성능이 떨어지므로 임의로 바꾸지 말 것:

  " [SEP] ".join([본표제, 알라딘_카테고리, 653키워드(60토큰), 목차(150토큰), 책소개(100토큰)])

  - 본표제·카테고리는 예산 없이 전량 사용 (MAX_LEN 384에서 예산 합 310을 뺀 나머지가 이 몫)
  - 목차는 알라딘_목차 우선, 없으면 KPIPA_목차로 대체
  - 결측 필드는 자리를 비우지 않고 그냥 건너뛴다(구분자도 함께 빠진다)
  - clean()은 개행·중복 공백을 단일 공백으로 정규화

653 키워드가 입력에 포함되므로 이 필드는 반드시 **653 생성 이후**에 실행해야 한다
(「056 분류모델 개선 및 I2M 연계 추진안」 3절).

모델이 예측하는 것은 KDC "강"(2자리, 95클래스)까지다. 세목까지 완성된 분류기호가
아니므로 그대로 완성본처럼 쓰지 않는다 — 화면에는 Top-3 후보와 확률을 함께 노출해
사서가 고르거나 직접 수정하도록 한다(현황 보고서 10절).
"""

from __future__ import annotations

import os
import re

from core import kdc_model
from core.debug_log import dbg

# 구분자와 필드 순서는 model8~21에서 바뀌지 않았다.
FIELD_SEPARATOR = " [SEP] "

# ── 입력 스키마 ────────────────────────────────────────────────
# 모델 라운드에 따라 입력문에 들어가는 필드 세트가 다르다. 학습 스크립트와 한 글자라도
# 어긋나면 정확도가 조용히 떨어지므로(model8 실측 88.0% → 83.0%) 스키마를 명시적으로 나눈다.
#
#   v8   (prepare_data_v8.py / model8~12)
#        본표제 [SEP] 카테고리 [SEP] 653키워드 [SEP] 목차 [SEP] 책소개
#
#   v21  (prepare_data_v21_no653_richfields.py / model21)
#        본표제 [SEP] 카테고리 [SEP] 부제 [SEP] 발행자 [SEP] 부가기호
#        [SEP] 목차 [SEP] 책소개 [SEP] KPIPA목차 [SEP] KPIPA저자소개
#        — 653을 완전히 배제한다(653은 사서 수작업 필드라 "완전 자동" 기준에 맞지 않음).
SCHEMA_V8 = "v8"
SCHEMA_V21 = "v21"

_DEFAULT_BUDGETS = {
    "keyword": 60,        # v8 전용
    "toc": 150,           # v8 기본값. model11+ 및 v21은 200
    "desc": 100,          # v8 기본값. model11+ 및 v21은 140
    # v21 신설 — prepare_data_v21의 상수와 동일해야 한다
    "subtitle": 30,
    "publisher": 15,
    "addcode": 10,
    "kpipa_toc": 100,
    "kpipa_author": 100,
}


def input_schema() -> str:
    """
    입력 스키마 결정. KDC_INPUT_SCHEMA로 명시할 수 있고, 없으면 모델 버전명으로 추론한다.
    운영 중 모델만 바꾸고 스키마를 안 바꾸는 실수를 막기 위해 추론을 기본으로 둔다.
    """
    explicit = (os.environ.get("KDC_INPUT_SCHEMA") or "").strip().lower()
    if explicit in (SCHEMA_V8, SCHEMA_V21):
        return explicit
    version = (os.environ.get("KDC_MODEL_VERSION") or "").lower()
    return SCHEMA_V21 if "model21" in version else SCHEMA_V8


def _budget(name: str) -> int:
    raw = (os.environ.get(f"KDC_{name.upper()}_TOKEN_BUDGET") or "").strip()
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_BUDGETS[name]
    except ValueError:
        return _DEFAULT_BUDGETS[name]

# "검토 필요" 판정 기준 — 1순위 확률이 아니라 1·2순위의 격차를 본다.
#
# 이 모델은 확률 보정이 안 되어 있어 1순위 확률의 중앙값이 0.26에 불과하고,
# 확률이 낮은 구간의 정확도(86~89%)가 높은 구간(91~97%)과 거의 차이가 없다.
# 즉 절대 확률로는 맞은 예측과 틀린 예측을 가려낼 수 없다(학습데이터 400건 실측).
#
# 반면 1위/2위 비율은 유효한 신호였다:
#   비율 < 1.5  → 정확도 58.3% (전체의 3.0%)   ← 사실상 동전던지기, 검토 필요
#   비율 >= 1.5 → 정확도 91.5% (전체의 97.0%)
# 경고를 3%로 좁히면서도 실제 위험 구간만 잡아낸다.
#
# 주의: 이 수치는 학습에 쓰인 데이터로 잰 것이라 낙관적이다. 딥러닝팀에서 test셋의
# (정답여부, 확률) 분포를 받으면 다시 맞출 것.
LOW_CONFIDENCE_RATIO = 1.5

_WS_RE = re.compile(r"\s+")


def _clean(value: str) -> str:
    """
    개행·중복 공백을 단일 공백으로 정규화 — prepare_data_v8.clean()과 동일.

    HTML 태그를 제거하지 않는 것은 의도적이다. `< 코스모폴리스 >`처럼 꺾쇠로 감싼
    책 제목이 목차·책소개에 흔한데, 태그 제거 정규식이 이를 통째로 지워 학습 입력과
    달라진다(실측: 100건 중 4건이 어긋났고 top-1이 88.0%→83.0%로 떨어졌다).
    """
    if not value:
        return ""
    return _WS_RE.sub(" ", str(value).strip())


def build_model_input(
    *,
    title: str = "",
    category: str = "",
    keywords: str = "",
    toc: str = "",
    description: str = "",
) -> str:
    """
    model8 입력문을 조립한다 — prepare_data_v8.build_text()와 동일한 결과여야 한다.

    빈 필드는 자리를 비우지 않고 건너뛴다(학습 때도 결측 필드는 구분자와 함께 빠졌고,
    field-dropout 0.15로 일부 필드가 없는 입력에 대한 내성이 학습되어 있다).
    """
    parts: list[str] = []

    for value in (_clean(title), _clean(category)):
        if value:
            parts.append(value)  # 예산 없음 — 남은 토큰을 전부 쓴다

    for value, budget in (
        (_clean(keywords), _budget("keyword")),
        (_clean(toc), _budget("toc")),
        (_clean(description), _budget("desc")),
    ):
        if value:
            cut = kdc_model.truncate_by_tokens(value, budget)
            if cut:
                parts.append(cut)

    return FIELD_SEPARATOR.join(parts)


def build_model_input_v21(
    *,
    title: str = "",
    category: str = "",
    subtitle: str = "",
    publisher: str = "",
    addcode: str = "",
    toc: str = "",
    description: str = "",
    kpipa_toc: str = "",
    kpipa_author: str = "",
) -> str:
    """
    model21 입력문을 조립한다 — prepare_data_v21_no653_richfields.build_text()와 동일해야 한다.

    학습 스크립트에서 그대로 옮겨온, 직관에 어긋나 보이지만 반드시 지켜야 하는 두 가지:

    1. **KPIPA 목차가 두 번 들어갈 수 있다.** 알라딘 목차가 비면 KPIPA 목차가 대체값으로
       목차 자리에 들어가고, 그와 별개로 KPIPA 목차 슬롯에도 한 번 더 붙는다. 중복처럼
       보여도 학습이 그렇게 됐으므로 한 번만 넣으면 안 된다.
       (다만 학습데이터 10만 건에서는 이 대체가 실제로 한 번도 발생하지 않았다 —
        KPIPA 목차가 있는 12.1%는 전부 알라딘 목차도 있는 자료였다.)

    2. **본표제·카테고리는 순서가 고정**이다. 학습 시 --protect-category-field가 두 번째
       세그먼트를 위치로 카테고리라 보고 field-dropout에서 보호하므로, 순서를 바꾸면
       model12에서 고쳤던 학습-추론 불일치가 재발한다.

    653은 받지 않는다. model21은 653을 완전히 배제한 트랙이다.
    """
    parts: list[str] = []

    for value in (_clean(title), _clean(category)):
        if value:
            parts.append(value)  # 예산 없음

    for value, budget_name in (
        (_clean(subtitle), "subtitle"),
        (_clean(publisher), "publisher"),
        (_clean(addcode), "addcode"),
    ):
        if value:
            cut = kdc_model.truncate_by_tokens(value, _budget(budget_name))
            if cut:
                parts.append(cut)

    # 목차 — 알라딘 우선, 없으면 KPIPA로 대체
    toc_value = _clean(toc) or _clean(kpipa_toc)
    if toc_value:
        cut = kdc_model.truncate_by_tokens(toc_value, _budget("toc"))
        if cut:
            parts.append(cut)

    desc_value = _clean(description)
    if desc_value:
        cut = kdc_model.truncate_by_tokens(desc_value, _budget("desc"))
        if cut:
            parts.append(cut)

    # KPIPA 목차 — 위 대체와 무관하게 별도 슬롯으로 한 번 더
    for value, budget_name in (
        (_clean(kpipa_toc), "kpipa_toc"),
        (_clean(kpipa_author), "kpipa_author"),
    ):
        if value:
            cut = kdc_model.truncate_by_tokens(value, _budget(budget_name))
            if cut:
                parts.append(cut)

    return FIELD_SEPARATOR.join(parts)


def _keywords_from_653(tag_653: str | None) -> str:
    """
    앱이 방금 생성한 653 태그에서 키워드만 뽑아 학습데이터의 '653키워드' 열 형식
    ("키워드1; 키워드2; ...")으로 되돌린다.
    """
    if not tag_653:
        return ""
    parts = [p.strip() for p in str(tag_653).split("$a")[1:]]
    return "; ".join(p for p in parts if p)


def build_056_field(
    item: dict,
    *,
    tag_653: str | None = None,
    toc_text: str = "",
    kpipa_toc: str = "",
    subtitle: str = "",
    publisher: str = "",
    addcode: str = "",
    kpipa_author: str = "",
    top_k: int = 3,
) -> tuple[str | None, dict]:
    """
    056 MRK 문자열과 진단 정보를 반환한다.

    Args:
        item:         알라딘 API 결과 (title/categoryName/description)
        tag_653:      먼저 생성된 653 태그 — v8 스키마에서만 쓴다(model21은 653 미사용)
        toc_text:     알라딘 목차(300 처리 과정에서 이미 확보한 값을 재사용)
        kpipa_toc:    KPIPA ONIX 목차
        subtitle:     부제 — v21 전용 (245 $b에 대응)
        publisher:    발행자 — v21 전용 (260 $b에 대응)
        addcode:      부가기호 — v21 전용 (020 $g에 대응)
        kpipa_author: KPIPA 저자소개 — v21 전용
        top_k:        반환할 후보 개수

    Returns:
        (mrk_str_or_None, diag)
    """
    schema = input_schema()

    # input_presence: 모델 입력 필드가 각각 실제로 채워졌는지. 평가 시트의 "입력 결손"
    # 열이 이 값을 그대로 쓴다 — 틀린 예측이 모델 탓인지 입력이 비어서인지를 사후에
    # 가르기 위한 것이라, 모델 가용 여부와 무관하게 항상 채워야 한다.
    _keywords = _keywords_from_653(tag_653)
    _desc = (item or {}).get("description", "")
    presence = {
        "title": bool(_clean((item or {}).get("title", ""))),
        "category": bool(_clean((item or {}).get("categoryName", ""))),
        "toc": bool(_clean(toc_text) or _clean(kpipa_toc)),
        "description": bool(_clean(_desc)),
    }
    if schema == SCHEMA_V21:
        presence.update({
            "subtitle": bool(_clean(subtitle)),
            "publisher": bool(_clean(publisher)),
            "addcode": bool(_clean(addcode)),
            "kpipa_toc": bool(_clean(kpipa_toc)),
            "kpipa_author": bool(_clean(kpipa_author)),
            # model21은 653을 입력에 쓰지 않는다. 평가 시트의 653 열이 "결손"으로
            # 오해되지 않도록 None이 아니라 명시적으로 False를 넣지 않고 키 자체를 뺀다.
        })
    else:
        presence["keywords"] = bool(_clean(_keywords))

    diag: dict = {
        "candidates": [],
        "low_confidence": False,
        "input_chars": 0,
        "reason": "",
        "input_schema": schema,
        "input_presence": presence,
    }

    available, why = kdc_model.availability()
    if not available:
        diag["reason"] = why
        dbg("[056] 건너뜀 —", why)
        return None, diag

    if schema == SCHEMA_V21:
        text = build_model_input_v21(
            title=(item or {}).get("title", ""),
            category=(item or {}).get("categoryName", ""),
            subtitle=subtitle,
            publisher=publisher,
            addcode=addcode,
            toc=toc_text,
            description=_desc,
            kpipa_toc=kpipa_toc,
            kpipa_author=kpipa_author,
        )
    else:
        text = build_model_input(
            title=(item or {}).get("title", ""),
            category=(item or {}).get("categoryName", ""),
            keywords=_keywords,
            toc=toc_text or kpipa_toc,
            description=_desc,
        )
    diag["input_chars"] = len(text)
    if not text:
        diag["reason"] = "모델 입력으로 쓸 서지정보가 없습니다."
        dbg("[056] 건너뜀 — 입력 텍스트 없음")
        return None, diag

    preds = kdc_model.predict_topk(text, k=top_k)
    if not preds:
        diag["reason"] = kdc_model.load_error() or "모델 추론에 실패했습니다."
        dbg("[056] 추론 결과 없음 —", diag["reason"])
        return None, diag

    diag["candidates"] = [{"kdc": label, "prob": round(prob, 4)} for label, prob in preds]
    best_kdc, best_prob = preds[0]
    runner_up_prob = preds[1][1] if len(preds) > 1 else 0.0
    diag["margin_ratio"] = round(best_prob / runner_up_prob, 2) if runner_up_prob > 0 else 999.0
    diag["low_confidence"] = diag["margin_ratio"] < LOW_CONFIDENCE_RATIO

    dbg(
        f"[056] 입력 {len(text)}자 → 후보:",
        ", ".join(f"{c['kdc']}({c['prob']:.0%})" for c in diag["candidates"]),
        f"1·2위 비율 {diag['margin_ratio']}",
        "※ 1·2위 경합 — 검토 필요" if diag["low_confidence"] else "",
    )

    # KORMARC 056: 지시기호 2개 모두 공백. $a 분류기호, $2 판표시.
    # 정독도서관은 KDC 6판을 쓰므로 $2는 "6" 고정(KDC_EDITION으로 변경 가능).
    # 모델은 "강"(2자리)까지만 예측하므로 $a에 2자리만 넣는다 — 세목은 사서가 채운다.
    edition = (os.environ.get("KDC_EDITION") or "6").strip() or "6"
    diag["edition"] = edition
    return f"=056  \\\\$a{best_kdc}$2{edition}", diag
