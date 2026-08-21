"""
pages/3_평가시스템.py
기존 I2M(2025년 코드 원본) / 고도화 I2M(2026 신규 통합 파이프라인) 평가 시스템.

목적: ISBN을 대량(약 200개 안팎)으로 넣고 두 시스템 중 하나를 골라 일괄 생성한 뒤,
결과를 필드·서브필드 단위로 정규화한(MARC 식별기호 $x를 지우고 태그+서브필드별
컬럼으로 분해한) CSV로 저장한다. 평가용 페이지라 개별 ISBN 결과를 화면에 하나씩
보여주지 않고, 전체 완료 후 요약(성공/실패 건수, 실패 목록)과 CSV 다운로드만 제공한다.

절대 원칙(사용자 지시):
- 이 페이지는 완전히 새로 추가하는 파일이다 — i2m_kormarc의 기존 코드
  (1_2026_ISBN_변환.py, 2_2025_I2M.py, api_client.py, core/, legacy_2025_code/1215_main.py 등)와
  "통합 이전 코드" 폴더는 단 한 글자도 수정하지 않는다.
  - 고도화 I2M: api_client.convert_isbn()(단건 변환, page1의 "단건 변환" 탭과 동일 경로)을
    ISBN마다 한 번씩 호출한다. 처음엔 convert_batch()로 10건씩 묶었었는데, 실측 결과 150건
    배치에서 초반 청크부터 바로 에러가 났다 — 백엔드 /api/convert/batch가 10건을 완전
    순차 처리(app.py의 병렬 없는 리스트 컴프리헨션)라 10건 처리 시간이 Render 앞단
    프록시의 요청 타임아웃(클라이언트 쪽 240초×10=2400초보다 훨씬 짧은, 보통 1~2분대로
    추정)을 넘겨서 프록시가 먼저 연결을 끊는 것으로 보인다. 건별 호출은 이미 단건 변환
    탭에서 안정적으로 쓰이고 있어 이 문제가 없다.
  - 기존 I2M: legacy_2025_code/1215_main.py(원본)의 run_and_export()를 읽기 전용으로
    임포트해서 그대로 재사용한다. 경로 이원화(로컬 원본 우선 → 저장소 내 사본 폴백) 규칙은
    2_2025_I2M.py와 동일하되, sys.modules 키 이름을 다르게 써서(legacy_2025_code_eval)
    2_2025_I2M.py와 동시에 열려도 서로 충돌하지 않게 한다.
- run_and_export()는 preview_in_streamlit=False로 호출해도 내부 곳곳(generate_all_oneclick
  등)에서 st.write/st.warning/st.error/st.expander 같은 디버그 출력을 직접 그린다(원본
  코드라 고칠 수 없음). ISBN 200개를 그대로 두면 화면이 그 출력으로 뒤덮이므로, 매 ISBN
  호출을 임시 st.empty() 컨테이너 안에서 실행한 뒤 즉시 비워서(placeholder.empty()) 화면에
  남기지 않는다 — "개별 ISBN 결과를 확인할 필요 없다"는 요구사항과, 원본을 고치지 않는다는
  원칙을 동시에 지키는 방법이다. 같은 이유로 모듈 임포트(하단의 st.header/st.form UI 포함)도
  1회만 세션에 캐시하면서 동일한 방식으로 화면에서 지운다.

CSV 컬럼 구성:
- 첨부된 "산출결과.csv"의 헤더 33개(no., isbn, 007, 008, 020 계열 4개, 041/056/245/246/260/
  300/490/500/546/653/700/710/830/900/940/950)를 고정으로 사용한다. 생성 결과에 해당 필드가
  없으면 빈 값으로 둔다.
- 고정 컬럼에 없는 태그·서브필드(또는 020의 3번째 이상 반복처럼 고정 컬럼이 다루지 않는
  반복분)가 새로 나오면, 처음 발견된 순서대로 헤더를 동적으로 추가한다(사용자 지시).
- 위 33개 뒤에 056 채점 전용 컬럼 10개(EVAL_056_HEADERS)를 붙인다. 2·3순위 후보, 1·2위
  확률과 그 비율, 입력 결손(653/목차/책소개) 여부로, 056 채점기준표(공통_056 시트)의
  R~Y열에 대응한다. 이 값들은 MRK 문자열에는 남지 않고 백엔드 응답 meta에만 있어서
  체크포인트에 meta를 함께 저장한다. 기존 I2M은 2·3순위가 원리적으로 없어 "미생성".
- "식별기호 삭제 + 정규화": MRK의 "$a"/"$b" 같은 서브필드 식별기호는 컬럼 이름으로 흡수되고
  셀 값에는 남지 않는다. 같은 서브필드가 한 필드 안에서 반복되면 ", "로, 같은 태그가 필드
  자체로 반복되면(700/710/653 등 다권/다저자) " ; "로 이어붙인다. 020만 예외적으로 반복
  발생 시 첫 번째는 020 계열 고정 컬럼, 두 번째는 "02010$a" 고정 컬럼(세트 ISBN 등)에
  각각 담는다 — 첨부 파일의 실제 값(세트 ISBN이 "02010$a"에 들어있음)을 보고 역산한 규칙.

중간 결과 저장(체크포인트):
- 150건 실행 도중 Streamlit 세션/브라우저 연결이 끊기면 그동안 만든 결과가 통째로
  날아가는 문제가 있어서 추가했다. ISBN 한 건이 끝날 때마다 결과를 output/eval_checkpoints/
  아래 JSONL 파일에 즉시 append + fsync한다(메모리에만 쌓다가 맨 끝에 CSV로 뽑는 방식이면
  중간에 죽었을 때 아무것도 못 건진다). 파일명은 (시스템, ISBN 목록) 해시로 정해지므로,
  같은 입력으로 "생성 실행"을 다시 누르면 이미 끝난 건은 자동으로 건너뛰고 이어서 처리한다.
  화면 상단 "저장된 실행 결과"에서 실행 중이 아니어도 지금까지의 결과를 CSV로 내려받거나
  지울 수 있다. CSV의 컬럼 구성(정규화 규칙)은 완료 시 다운로드와 동일하게 _normalize_row/
  _build_dataframe을 그대로 재사용한다.
- (실측: 150건 중 약 40건에서 에러 없이 조용히 멈추는 현상 확인 — Streamlit 세션/브라우저
  연결이 끊기는 것으로 추정되며, 정확한 원인은 미확정.) 이 경우 사용자가 원본 ISBN
  목록을 다시 붙여넣지 않고도 재개할 수 있어야 해서, 체크포인트 메타에 대상 ISBN 목록
  전체(isbns)를 같이 저장하고, "저장된 실행 결과" 각 항목에 "이어서 실행" 버튼을 추가했다.
  이 버튼은 체크포인트에 저장된 ISBN 목록만으로 나머지를 처리한다 — 몇 번을 끊겨도 그
  버튼만 계속 누르면 된다. (이 필드가 없는 이전 버전 체크포인트 파일은 버튼이 비활성화된다.)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from api_client import convert_isbn
from auth_gate import require_password

st.set_page_config(page_title="평가 시스템 | I2M KORMARC", page_icon="🧪", layout="wide")
require_password()
st.title("I2M 평가 시스템")
st.caption(
    "ISBN을 대량으로 넣고 기존 I2M(2025년 코드) 또는 고도화 I2M(2026 통합 파이프라인) 중 "
    "하나로 일괄 생성한 뒤, 필드·서브필드 단위로 정규화한 CSV로 저장합니다. "
    "개별 ISBN 결과는 화면에 표시하지 않고, 완료 후 요약과 CSV 다운로드만 제공합니다."
)
st.divider()


# ══════════════════════════════════════════════════════════════
# 고정 CSV 헤더 — 첨부된 "산출결과.csv" 그대로
# ══════════════════════════════════════════════════════════════
FIXED_HEADERS: list[str] = [
    "no.", "isbn", "007", "008",
    "020  $a", "020  $g", "020  $c", "02010$a",
    "041 $a", "041 $h",
    "056 $a",
    "245 $a", "245 $b", "245 $d", "245 $e",
    "246 $a",
    "260 $a", "260 $b", "260 $c",
    "300 $a", "300 $b", "300 $c",
    "490 $a", "490 $v",
    "500 $a",
    "546 $a",
    "653 $a",
    "700 $a",
    "710 $a",
    "830 $a", "830 $v",
    "900 $a",
    "940 $a",
    "950 $b",
]

# ── 056 평가 전용 컬럼 ──────────────────────────────────────────
# 056 채점기준표(공통_056 시트)는 최종 분류기호 하나만으로는 채울 수 없다. 2·3순위
# 후보, 1·2위 확률 비율, 입력 결손 여부가 각각 별도 열로 들어간다. 이 값들은 백엔드가
# 이미 응답 meta에 담아 보내주고 있으므로(app.py의 kdc_candidates/kdc_margin_ratio/
# kdc_input_presence) 모델을 다시 돌릴 필요 없이 옮겨 적기만 하면 된다.
#
# 기존 I2M(2025년 코드)은 GPT가 분류기호 하나만 답하는 구조라 2·3순위와 확률이
# 아예 존재하지 않는다. 빈칸으로 두면 "실행은 됐는데 값이 안 담긴 것"과 구분이
# 안 되므로 명시적으로 "미생성"이라고 적는다.
EVAL_056_HEADERS: list[str] = [
    "056 2순위", "056 3순위",
    "056 1위확률", "056 2위확률",
    "056 1·2위비율", "056 검토필요(1/0)",
    "056 653유무(1/0)", "056 목차유무(1/0)", "056 책소개유무(1/0)",
    "056 미생성사유",
]

_LEGACY_NA = "미생성"

# "02010$a" = 020 필드가 두 번 나올 때(개별 ISBN + 세트 ISBN 등) 두 번째 반복의 $a.
# 020 계열 나머지 헤더("020  $a/$g/$c")는 첫 번째 반복만 담는다 — 그래서 아래에서
# 020만 occurrence를 "agg"(전체 집계)가 아니라 특정 회차로 고정해 처리한다.
_HEADER_OVERRIDE: dict[str, tuple[str, str, int]] = {"02010$a": ("020", "a", 2)}

_CONTROL_TAGS = {"001", "002", "003", "004", "005", "006", "007", "008", "009"}


def _column_spec(header: str) -> tuple[str, str, int | str] | None:
    """고정 헤더 문자열 → (tag, code, occurrence). occurrence는 1-based 특정 회차 또는
    "agg"(모든 회차 집계). "no."/"isbn"/"007"/"008"은 별도 처리라 None을 반환한다."""
    if header in ("no.", "isbn", "007", "008"):
        return None
    if header in _HEADER_OVERRIDE:
        return _HEADER_OVERRIDE[header]
    m = re.match(r"^(\d{3})\s*\$(\w)$", header)
    if not m:
        return None
    tag, code = m.group(1), m.group(2)
    return (tag, code, 1 if tag == "020" else "agg")


# ══════════════════════════════════════════════════════════════
# MRK 파싱 & 정규화
# ══════════════════════════════════════════════════════════════

def _parse_mrk_fields(mrk_text: str) -> list[dict]:
    """MRK 텍스트 한 줄씩 파싱. 각 항목: {"tag": str, "subfields": [(code, value), ...], "raw": str}.
    LDR/제어필드(007/008 등)는 subfields가 비고 raw에 원문 데이터가 그대로 들어간다.
    core/marc_builder.py의 record_to_mrk()와 legacy_2025_code의 record_to_mrk_from_record()가
    똑같이 "={tag}  {ind1}{ind2}$a...$b..." 형식으로 찍기 때문에 두 시스템 모두 이 파서로 처리된다.
    """
    fields = []
    for line in (mrk_text or "").splitlines():
        if not line.startswith("="):
            continue
        m = re.match(r"^=(\S+)  (.*)$", line)
        if not m:
            continue
        tag, rest = m.group(1), m.group(2)
        if tag == "LDR" or tag in _CONTROL_TAGS:
            fields.append({"tag": tag, "subfields": [], "raw": rest})
            continue
        sub_str = rest[2:]  # 앞 2글자(지시기호) 건너뜀
        subs = [
            (part[1], part[2:])
            for part in re.split(r"(?=\$)", sub_str)
            if len(part) >= 2 and part[0] == "$"
        ]
        fields.append({"tag": tag, "subfields": subs, "raw": rest})
    return fields


def _control_value(fields: list[dict], tag: str) -> str:
    vals = [f["raw"].strip() for f in fields if f["tag"] == tag and f["raw"].strip()]
    return " ; ".join(vals)


def _occurrence_value(occ: list[tuple[str, str]], code: str) -> str:
    """한 필드 occurrence 안에서 같은 서브필드 코드가 반복되면 ", "로 잇는다."""
    vals = [v.strip() for c, v in occ if c == code and v.strip()]
    return ", ".join(vals)


def _aggregate_subfield(occurrences: list[list[tuple[str, str]]], code: str) -> str:
    """같은 태그가 필드 자체로 여러 번 나오면(700/710/653 등) occurrence 사이는 " ; "로 잇는다."""
    per_occurrence = [_occurrence_value(occ, code) for occ in occurrences]
    return " ; ".join(v for v in per_occurrence if v)


def _056_eval_values(meta: dict | None, is_legacy: bool) -> dict[str, str]:
    """응답 meta의 056 진단 정보를 채점기준표 열 형식으로 옮긴다.

    is_legacy=True(기존 I2M)면 2·3순위·확률이 원리적으로 존재하지 않으므로 "미생성"을
    넣는다. 입력 결손 열도 마찬가지로 기존 I2M은 모델 입력이라는 개념 자체가 없어
    비워 둔다 — 이 열은 고도화 I2M의 오답 원인을 가리기 위한 것이다.
    """
    out = {h: "" for h in EVAL_056_HEADERS}
    if is_legacy:
        for h in ("056 2순위", "056 3순위", "056 1위확률", "056 2위확률",
                  "056 1·2위비율", "056 검토필요(1/0)"):
            out[h] = _LEGACY_NA
        return out

    meta = meta or {}
    cands = meta.get("kdc_candidates") or []
    # candidates는 [{"kdc": "33", "prob": 0.71}, ...] 형태이며 확률 내림차순이다.
    if len(cands) > 1:
        out["056 2순위"] = str(cands[1].get("kdc", ""))
        out["056 2위확률"] = f"{cands[1].get('prob', ''):.4f}" if isinstance(cands[1].get("prob"), (int, float)) else ""
    if len(cands) > 2:
        out["056 3순위"] = str(cands[2].get("kdc", ""))
    if cands and isinstance(cands[0].get("prob"), (int, float)):
        out["056 1위확률"] = f"{cands[0]['prob']:.4f}"

    ratio = meta.get("kdc_margin_ratio")
    if isinstance(ratio, (int, float)):
        out["056 1·2위비율"] = str(ratio)
    # low_confidence는 항상 True/False로 오지만, 056 자체가 안 만들어진 건은
    # 판정 대상이 아니라 빈칸이어야 한다(0으로 적으면 "검토 불필요"로 읽힌다).
    if meta.get("tag_056"):
        out["056 검토필요(1/0)"] = "1" if meta.get("kdc_low_confidence") else "0"

    presence = meta.get("kdc_input_presence") or {}
    for header, key in (
        ("056 653유무(1/0)", "keywords"),
        ("056 목차유무(1/0)", "toc"),
        ("056 책소개유무(1/0)", "description"),
    ):
        if key in presence:
            out[header] = "1" if presence[key] else "0"

    out["056 미생성사유"] = meta.get("kdc_reason", "") or ""
    return out


def _normalize_row(
    no: int,
    isbn: str,
    mrk_text: str,
    error: str,
    meta: dict | None = None,
    is_legacy: bool = False,
) -> dict[str, str]:
    row: dict[str, str] = {"no.": str(no), "isbn": isbn}
    for h in FIXED_HEADERS:
        row.setdefault(h, "")
    row.update(_056_eval_values(meta, is_legacy))

    if error or not (mrk_text or "").strip():
        return row

    fields = _parse_mrk_fields(mrk_text)
    row["007"] = _control_value(fields, "007")
    row["008"] = _control_value(fields, "008")

    by_tag: dict[str, list[list[tuple[str, str]]]] = {}
    for f in fields:
        if f["tag"] == "LDR" or f["tag"] in _CONTROL_TAGS:
            continue
        by_tag.setdefault(f["tag"], []).append(f["subfields"])

    covered: set[tuple[str, str, int | str]] = set()
    for h in FIXED_HEADERS:
        spec = _column_spec(h)
        if spec is None:
            continue
        tag, code, occurrence = spec
        occs = by_tag.get(tag, [])
        if occurrence == "agg":
            row[h] = _aggregate_subfield(occs, code)
        else:
            idx = occurrence - 1
            row[h] = _occurrence_value(occs[idx], code) if idx < len(occs) else ""
        covered.add((tag, code, occurrence))

    # 고정 컬럼이 다루지 않는 태그/서브필드/회차 → 동적 컬럼으로 추가
    for tag, occs in by_tag.items():
        for occ_idx, occ in enumerate(occs, start=1):
            for code, value in occ:
                if not value.strip():
                    continue
                if (tag, code, "agg") in covered or (tag, code, occ_idx) in covered:
                    continue
                col_name = f"{tag} ${code}" if occ_idx == 1 else f"{tag}({occ_idx}) ${code}"
                row[col_name] = (
                    (row[col_name] + " ; " if col_name in row and row[col_name] else "")
                    + value.strip()
                )

    return row


def _build_dataframe(rows: list[dict[str, str]]) -> pd.DataFrame:
    base_headers = FIXED_HEADERS + EVAL_056_HEADERS
    seen = set(base_headers)
    dynamic_cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                dynamic_cols.append(k)
    all_headers = base_headers + dynamic_cols
    return pd.DataFrame([{h: row.get(h, "") for h in all_headers} for row in rows])


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ══════════════════════════════════════════════════════════════
# 중간 결과 저장(체크포인트) — output/eval_checkpoints/*.jsonl
# ══════════════════════════════════════════════════════════════

CHECKPOINT_DIR = Path(__file__).resolve().parents[1] / "output" / "eval_checkpoints"
_SYSTEM_SLUG = {"고도화": "advanced", "기존": "legacy"}

# 체크포인트에 남길 meta 키 — 056 채점에 실제로 쓰는 것만. meta에는 debug_lines처럼
# 건당 수십 KB짜리 값도 들어있어 통째로 저장하면 200건에 수 MB가 된다.
_META_KEEP_KEYS = {
    "kdc_candidates", "kdc_low_confidence", "kdc_margin_ratio",
    "kdc_edition", "kdc_reason", "kdc_model_version", "kdc_input_presence",
    "tag_056", "tag_653", "aladin_title", "category_name",
}


def _system_slug(system_label: str) -> str:
    return _SYSTEM_SLUG["고도화"] if system_label.startswith("고도화") else _SYSTEM_SLUG["기존"]


def _checkpoint_path(system_label: str, isbns: list[str]) -> Path:
    """(시스템, ISBN 목록)이 같으면 항상 같은 파일을 가리키게 한다 — 그래야 같은 입력으로
    "생성 실행"을 다시 눌렀을 때 이전 체크포인트를 찾아 이어서 처리할 수 있다."""
    key_src = _system_slug(system_label) + "|" + ",".join(sorted(isbns))
    digest = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:12]
    return CHECKPOINT_DIR / f"{_system_slug(system_label)}_{len(isbns)}건_{digest}.jsonl"


def _init_checkpoint(path: Path, system_label: str, isbns: list[str]) -> None:
    """파일이 없을 때만 메타 정보(1번째 줄)를 써서 새로 만든다. 이미 있으면(이어서 진행하는
    상황) 손대지 않는다. 대상 ISBN 목록 전체(isbns)를 같이 저장해두는 이유: 실행이 도중에
    끊겼을 때, 사용자가 원본 ISBN 목록을 다시 붙여넣지 않아도 "이어서 실행" 버튼 하나로
    체크포인트만 보고 나머지를 처리할 수 있게 하기 위함."""
    if path.exists():
        return
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "meta": {
            "system": system_label,
            "total": len(isbns),
            "isbns": isbns,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def _load_checkpoint(path: Path) -> tuple[dict | None, dict[str, dict]]:
    """저장된 중간 결과를 읽는다. (메타 정보, {isbn: {"mrk_text","error"}}) 반환.
    파일이 없으면 (None, {})."""
    meta = None
    done: dict[str, dict] = {}
    if not path.exists():
        return meta, done
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "meta" in rec:
                meta = rec["meta"]
            elif "isbn" in rec:
                done[rec["isbn"]] = rec
    return meta, done


def _append_checkpoint(
    path: Path, isbn: str, mrk_text: str, error: str, meta: dict | None = None
) -> None:
    """ISBN 한 건이 끝나는 즉시 디스크에 기록 + fsync. 세션이 중간에 끊기거나 죽어도
    여기까지 처리된 결과는 남아서, 다음에 같은 입력으로 다시 실행하면 이어서 처리된다.

    meta에는 056 후보·확률처럼 MRK 문자열에는 남지 않는 진단값이 들어 있다. 예전에는
    저장하지 않아 CSV를 뽑을 때 이미 받아온 값이 버려졌다. 다만 meta 전체는 디버그
    로그까지 포함해 건당 수십 KB라 체크포인트가 불필요하게 커지므로, 채점에 쓰는
    키만 골라 남긴다.
    """
    slim = {k: v for k, v in (meta or {}).items() if k in _META_KEEP_KEYS}
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"isbn": isbn, "mrk_text": mrk_text, "error": error, "meta": slim},
                ensure_ascii=False,
            )
            + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def _list_checkpoints() -> list[Path]:
    if not CHECKPOINT_DIR.exists():
        return []
    return sorted(CHECKPOINT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _checkpoint_dataframe(path: Path) -> pd.DataFrame:
    """체크포인트에 지금까지 저장된 결과를(진행 중이든 완료든) 그 자리에서 정규화 CSV로 만든다."""
    meta, done = _load_checkpoint(path)
    is_legacy = not str((meta or {}).get("system", "")).startswith("고도화")
    rows = [
        _normalize_row(
            no, rec["isbn"], rec.get("mrk_text", ""), rec.get("error") or "",
            meta=rec.get("meta"), is_legacy=is_legacy,
        )
        for no, rec in enumerate(done.values(), start=1)
    ]
    return _build_dataframe(rows)


# ══════════════════════════════════════════════════════════════
# 기존 I2M(2025년 코드 원본) 읽기 전용 로딩
# ══════════════════════════════════════════════════════════════

def _get_legacy_module():
    """legacy_2025_code/1215_main.py(원본)를 읽기 전용으로 1회만 임포트해 세션에 캐시.
    2_2025_I2M.py와 동일한 경로 이원화 규칙(로컬 원본 우선 → 저장소 내 사본 폴백)을 따른다.
    모듈을 import(exec)하면 원본 하단의 Streamlit UI(st.header/st.form 등)가 함께 그려지므로,
    임시 placeholder에 담았다가 즉시 지운다. 원본 파일은 전혀 수정하지 않는다."""
    if "eval_legacy_module" in st.session_state:
        return st.session_state["eval_legacy_module"], st.session_state["eval_legacy_source"]

    original_path = (
        Path(__file__).resolve().parents[2] / "통합 이전 코드" / "2025년 코드" / "1215_main.py"
    )
    copy_path = Path(__file__).resolve().parents[1] / "legacy_2025_code" / "1215_main.py"

    if original_path.exists():
        legacy_path, source_label = original_path, "로컬 원본"
    elif copy_path.exists():
        legacy_path, source_label = copy_path, "저장소 내 사본(legacy_2025_code/)"
    else:
        st.error("기존 I2M(2025년 코드) 원본 파일을 찾을 수 없습니다.")
        st.info(f"- 로컬 원본: `{original_path}`\n- 저장소 내 사본: `{copy_path}`")
        st.stop()

    sys.dont_write_bytecode = True
    # 2_2025_I2M.py가 쓰는 모듈명("legacy_2025_code")과 겹치지 않게 별도 이름을 쓴다 —
    # 두 페이지를 같은 세션/프로세스에서 함께 열어도 sys.modules 충돌이 없도록.
    module_name = "legacy_2025_code_eval"
    spec = importlib.util.spec_from_file_location(module_name, legacy_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    placeholder = st.empty()
    with st.spinner("기존 I2M(2025년 코드) 로딩 중... (세션당 최초 1회)"):
        with placeholder.container():
            spec.loader.exec_module(module)
    placeholder.empty()  # 원본 하단 UI(폼/헤더)가 그려졌던 자리를 지운다 — 함수만 취한다

    st.session_state["eval_legacy_module"] = module
    st.session_state["eval_legacy_source"] = source_label
    return module, source_label


# ══════════════════════════════════════════════════════════════
# 배치 실행 + 결과 표시 — "생성 실행" 버튼과 "이어서 실행" 버튼이 공유한다
# ══════════════════════════════════════════════════════════════

def _run_batch(
    system_label: str,
    target_isbns: list[str],
    ckpt_path: Path,
    done_map: dict[str, dict],
) -> list[tuple[str, str, str, dict]]:
    """target_isbns를 순서대로 처리한다. done_map(체크포인트에 이미 있는 결과)에 있는 건
    재처리하지 않고 그대로 쓰고, 없는 건 새로 생성해서 즉시 체크포인트에 저장한다.
    (isbn, mrk_text, error, meta) 리스트를 target_isbns 순서 그대로 반환한다."""
    total = len(target_isbns)
    progress = st.progress(0, text="준비 중...")
    status = st.empty()
    results: list[tuple[str, str, str, dict]] = []

    if system_label.startswith("고도화"):
        # ISBN마다 개별 HTTP 요청(convert_isbn)을 보낸다 — 10건씩 convert_batch()로 묶으면
        # 백엔드가 그 10건을 완전 순차 처리하는 동안 Render 앞단 프록시의 요청 타임아웃을
        # 넘겨 연결이 끊기는 문제가 실측으로 확인됐다(위 모듈 docstring 참고).
        for i, isbn in enumerate(target_isbns, start=1):
            if isbn in done_map:
                rec = done_map[isbn]
                results.append(
                    (isbn, rec.get("mrk_text", ""), rec.get("error") or "", rec.get("meta") or {})
                )
            else:
                status.text(f"{i} / {total} 생성 중... (고도화 I2M)")
                r = convert_isbn(isbn)
                mrk_text, err = r.get("mrk_text", ""), r.get("error") or ""
                meta = r.get("meta") or {}
                _append_checkpoint(ckpt_path, isbn, mrk_text, err, meta)
                results.append((isbn, mrk_text, err, meta))
            progress.progress(i / total, text=f"{i}/{total} 완료")
    else:
        legacy_module, source_label = _get_legacy_module()
        st.caption(f"실행 소스: {source_label}")
        for i, isbn in enumerate(target_isbns, start=1):
            if isbn in done_map:
                rec = done_map[isbn]
                results.append(
                    (isbn, rec.get("mrk_text", ""), rec.get("error") or "", rec.get("meta") or {})
                )
            else:
                status.text(f"{i} / {total} 생성 중... (기존 I2M)")
                ph = st.empty()
                try:
                    with ph.container():
                        _, _, mrk_text, _ = legacy_module.run_and_export(
                            isbn,
                            use_ai_940=True,
                            save_dir="./output",
                            preview_in_streamlit=False,
                        )
                    err = ""
                except Exception as e:
                    mrk_text, err = "", str(e)
                ph.empty()  # 원본 내부의 st.write/warning/expander 디버그 출력을 지운다
                # 기존 I2M은 run_and_export()가 MRK 문자열만 돌려준다 — 056 후보·확률
                # 같은 진단값이 애초에 없으므로 meta는 빈 dict다.
                _append_checkpoint(ckpt_path, isbn, mrk_text, err, {})
                results.append((isbn, mrk_text, err, {}))
            progress.progress(i / total, text=f"{i}/{total} 완료")

    progress.empty()
    status.empty()
    return results


def _show_results(
    results: list[tuple[str, str, str, dict]], ckpt_path: Path, system_label: str
) -> None:
    total = len(results)
    is_legacy = not system_label.startswith("고도화")
    rows = [
        _normalize_row(no, isbn, mrk_text, err, meta=meta, is_legacy=is_legacy)
        for no, (isbn, mrk_text, err, meta) in enumerate(results, start=1)
    ]
    df = _build_dataframe(rows)

    success_count = sum(1 for _, _, err, _ in results if not err)
    fail_count = total - success_count
    st.success(f"생성 완료 — 성공 {success_count}건 / 실패 {fail_count}건")

    if fail_count:
        failed = [isbn for isbn, _, err, _ in results if err]
        with st.expander(f"실패 목록 ({fail_count}건)"):
            st.write(", ".join(failed))

    # 056은 채점 대상이라 몇 건이 실제로 생성됐는지 여기서 바로 보여준다. 200건을
    # 다 돌린 뒤 CSV를 열어서야 "056이 절반만 나왔네"를 알게 되면 늦다.
    made_056 = sum(1 for r in rows if r.get("056 $a"))
    line = f"056 생성: {made_056}/{total}건"
    if not is_legacy:
        review = sum(1 for r in rows if r.get("056 검토필요(1/0)") == "1")
        no_kw = sum(1 for r in rows if r.get("056 653유무(1/0)") == "0")
        line += f" · 1·2위 경합(검토 필요) {review}건 · 653 결손 {no_kw}건"
    st.info(line)

    st.download_button(
        "CSV 파일 다운로드 (.csv)",
        data=_to_csv_bytes(df),
        file_name="평가결과.csv",
        mime="text/csv",
        key=f"final_dl_{ckpt_path.stem}",
    )
    st.caption(f"💾 중간 저장 파일: `{ckpt_path.name}` — 위 '저장된 실행 결과'에서 언제든 다시 받거나 지울 수 있습니다.")


# ══════════════════════════════════════════════════════════════
# 화면 구성
# ══════════════════════════════════════════════════════════════

_checkpoints = _list_checkpoints()

# 가장 최근에 끊긴 실행을 굳이 목록에서 찾아 고르지 않아도 바로 이어서 진행할 수 있게,
# 접혀 있는 "저장된 실행 결과" 패널과 별개로 눈에 바로 띄는 배너 하나를 최상단에 둔다.
_resumable = None
for _ckpt_path in _checkpoints:
    _meta, _done = _load_checkpoint(_ckpt_path)
    _target_isbns = (_meta or {}).get("isbns") or []
    if _target_isbns and len(_done) < len(_target_isbns):
        _resumable = (_ckpt_path, _meta, _done, _target_isbns)
        break  # _checkpoints는 최신순 정렬 — 가장 최근 것 하나만 쓴다

if _resumable is not None:
    _r_path, _r_meta, _r_done, _r_isbns = _resumable
    _r_remaining = len(_r_isbns) - len(_r_done)
    st.warning(
        f"⏸️ 중단된 실행이 있습니다 — **{_r_meta.get('system', '')}**, "
        f"{len(_r_done)}/{len(_r_isbns)}건 완료 ({_r_remaining}건 남음)."
    )
    if st.button(f"▶️ 바로 이어서 실행 ({_r_remaining}건 남음)", type="primary", key="quick_resume"):
        st.session_state["eval_resume_ckpt"] = str(_r_path)
        st.rerun()
    st.divider()

with st.expander(f"💾 저장된 실행 결과 (중단된 실행 복구) — {len(_checkpoints)}개", expanded=False):
    if not _checkpoints:
        st.caption("아직 저장된 실행이 없습니다.")
    else:
        st.caption(
            "실행 도중 끊겨도 그때까지 처리된 결과는 여기 남습니다. '이어서 실행'을 누르면 "
            "ISBN 목록을 다시 붙여넣지 않아도 이 체크포인트에 저장된 목록만으로 나머지를 "
            "처리합니다 — 몇 번을 끊겨도 이 버튼만 계속 누르면 됩니다. 지금 상태 그대로 "
            "받고 싶으면 CSV 다운로드로 바로 받으세요."
        )
        for _ckpt_path in _checkpoints:
            _meta, _done = _load_checkpoint(_ckpt_path)
            _total_target = (_meta or {}).get("total", "?")
            _system_label = (_meta or {}).get("system", "?")
            _created_at = (_meta or {}).get("created_at", "")
            _target_isbns = (_meta or {}).get("isbns") or []
            _can_resume = bool(_target_isbns) and len(_done) < len(_target_isbns)

            col_info, col_resume, col_dl, col_del = st.columns([3, 1, 1, 1])
            with col_info:
                st.write(f"**{_system_label}** — {len(_done)}/{_total_target}건 완료 (생성: {_created_at})")
                if not _target_isbns and _total_target != "?":
                    st.caption("(이전 버전 체크포인트라 ISBN 목록이 없어 '이어서 실행'을 못 씁니다 — CSV만 받을 수 있습니다.)")
            with col_resume:
                if st.button("이어서 실행", key=f"resume_{_ckpt_path.stem}", disabled=not _can_resume):
                    st.session_state["eval_resume_ckpt"] = str(_ckpt_path)
                    st.rerun()
            with col_dl:
                st.download_button(
                    "CSV 다운로드",
                    data=_to_csv_bytes(_checkpoint_dataframe(_ckpt_path)),
                    file_name=f"평가결과_중간저장_{_ckpt_path.stem}.csv",
                    mime="text/csv",
                    key=f"dl_{_ckpt_path.stem}",
                )
            with col_del:
                if st.button("삭제", key=f"del_{_ckpt_path.stem}"):
                    _ckpt_path.unlink(missing_ok=True)
                    st.rerun()

# "이어서 실행" 버튼을 눌렀으면(위 목록에서 트리거) 여기서 바로 처리한다 — 사용자가 원본
# ISBN 목록을 다시 입력할 필요 없이, 체크포인트에 저장해둔 목록만으로 나머지를 처리한다.
if "eval_resume_ckpt" in st.session_state:
    _resume_path = Path(st.session_state.pop("eval_resume_ckpt"))
    _resume_meta, _resume_done = _load_checkpoint(_resume_path)
    if _resume_meta and _resume_meta.get("isbns"):
        st.subheader(f"이어서 실행 중 — {_resume_meta.get('system', '')}")
        _resume_results = _run_batch(
            _resume_meta["system"], _resume_meta["isbns"], _resume_path, _resume_done
        )
        _show_results(_resume_results, _resume_path, _resume_meta["system"])
        st.divider()
    else:
        st.error("이 체크포인트에는 ISBN 목록이 저장되어 있지 않아 이어서 실행할 수 없습니다.")

system = st.radio(
    "평가할 시스템",
    ["고도화 I2M (2026 신규 통합 파이프라인)", "기존 I2M (2025년 코드 원본)"],
    horizontal=True,
)

st.subheader("ISBN 입력")
col_text, col_file = st.columns([1, 1], gap="large")

with col_text:
    st.markdown("**직접 입력** (한 줄에 하나, 200개 안팎 권장)")
    raw_text = st.text_area(
        "ISBN 목록",
        placeholder="9788937462849\n9791162540091\n9788936434120",
        height=220,
        key="eval_batch_text",
        label_visibility="collapsed",
    )

with col_file:
    st.markdown("**파일 업로드** (Excel / CSV, `isbn` 열)")
    uploaded = st.file_uploader(
        "ISBN 열 이름: `isbn` 또는 `ISBN`",
        type=["xlsx", "xls", "csv"],
        key="eval_batch_file",
    )

isbn_list: list[str] = []
if raw_text.strip():
    for line in raw_text.splitlines():
        cleaned = re.sub(r"[^0-9X]", "", line.strip().upper())
        if len(cleaned) in (10, 13):
            isbn_list.append(cleaned)

if uploaded is not None:
    try:
        if uploaded.name.endswith(".csv"):
            file_df = pd.read_csv(uploaded, dtype=str)
        else:
            file_df = pd.read_excel(uploaded, dtype=str)
        col_name = next((c for c in file_df.columns if c.strip().lower() == "isbn"), None)
        if col_name:
            before = len(isbn_list)
            for val in file_df[col_name].dropna():
                cleaned = re.sub(r"[^0-9X]", "", str(val).strip().upper())
                if len(cleaned) in (10, 13):
                    isbn_list.append(cleaned)
            st.success(f"파일에서 ISBN {len(isbn_list) - before}건 인식")
        else:
            st.warning("파일에 `isbn` 또는 `ISBN` 열이 없습니다.")
    except Exception as e:
        st.error(f"파일 읽기 실패: {e}")

seen_isbn: set[str] = set()
unique_isbns = [x for x in isbn_list if not (x in seen_isbn or seen_isbn.add(x))]

if unique_isbns:
    st.info(f"평가 대상: **{len(unique_isbns)}건** (중복 제거 후)")

st.caption(
    "⚠️ 실제 외부 API(알라딘/OpenAI/KPIPA/행안부 등)를 호출하므로 건수가 많으면 시간이 "
    "오래 걸리고 실제 API 사용량(비용)이 발생합니다. 특히 '기존 I2M'은 건별 순차 처리라 "
    "200건이면 상당히 오래 걸릴 수 있습니다."
)

if st.button("생성 실행", type="primary", disabled=not unique_isbns):
    total = len(unique_isbns)

    # 체크포인트 — (시스템, ISBN 목록)이 같으면 항상 같은 파일. 이미 끝난 건이 있으면
    # 건너뛰고 이어서 처리한다(같은 입력으로 재실행 = 자동 이어하기).
    ckpt_path = _checkpoint_path(system, unique_isbns)
    _init_checkpoint(ckpt_path, system, unique_isbns)
    _, done_map = _load_checkpoint(ckpt_path)
    if done_map:
        st.info(f"저장된 중간 결과 발견 — {len(done_map)}/{total}건은 건너뛰고 이어서 진행합니다.")

    results = _run_batch(system, unique_isbns, ckpt_path, done_map)
    _show_results(results, ckpt_path, system)
