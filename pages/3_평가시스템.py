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
- "식별기호 삭제 + 정규화": MRK의 "$a"/"$b" 같은 서브필드 식별기호는 컬럼 이름으로 흡수되고
  셀 값에는 남지 않는다. 같은 서브필드가 한 필드 안에서 반복되면 ", "로, 같은 태그가 필드
  자체로 반복되면(700/710/653 등 다권/다저자) " ; "로 이어붙인다. 020만 예외적으로 반복
  발생 시 첫 번째는 020 계열 고정 컬럼, 두 번째는 "02010$a" 고정 컬럼(세트 ISBN 등)에
  각각 담는다 — 첨부 파일의 실제 값(세트 ISBN이 "02010$a"에 들어있음)을 보고 역산한 규칙.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from api_client import convert_isbn

st.set_page_config(page_title="평가 시스템 | I2M KORMARC", page_icon="🧪", layout="wide")
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


def _normalize_row(no: int, isbn: str, mrk_text: str, error: str) -> dict[str, str]:
    row: dict[str, str] = {"no.": str(no), "isbn": isbn}
    for h in FIXED_HEADERS:
        row.setdefault(h, "")

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
    seen = set(FIXED_HEADERS)
    dynamic_cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                dynamic_cols.append(k)
    all_headers = FIXED_HEADERS + dynamic_cols
    return pd.DataFrame([{h: row.get(h, "") for h in all_headers} for row in rows])


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
# 화면 구성
# ══════════════════════════════════════════════════════════════

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
    progress = st.progress(0, text="준비 중...")
    status = st.empty()

    # (isbn, mrk_text, error)
    results: list[tuple[str, str, str]] = []

    if system.startswith("고도화"):
        # ISBN마다 개별 HTTP 요청(convert_isbn)을 보낸다 — 10건씩 convert_batch()로 묶으면
        # 백엔드가 그 10건을 완전 순차 처리하는 동안 Render 앞단 프록시의 요청 타임아웃을
        # 넘겨 연결이 끊기는 문제가 실측으로 확인됐다(위 모듈 docstring 참고).
        for i, isbn in enumerate(unique_isbns, start=1):
            status.text(f"{i} / {total} 생성 중... (고도화 I2M)")
            r = convert_isbn(isbn)
            results.append((r.get("isbn", isbn), r.get("mrk_text", ""), r.get("error") or ""))
            progress.progress(i / total, text=f"{i}/{total} 완료")
    else:
        legacy_module, source_label = _get_legacy_module()
        st.caption(f"실행 소스: {source_label}")
        for i, isbn in enumerate(unique_isbns, start=1):
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
            results.append((isbn, mrk_text, err))
            progress.progress(i / total, text=f"{i}/{total} 완료")

    progress.empty()
    status.empty()

    rows = [
        _normalize_row(no, isbn, mrk_text, err)
        for no, (isbn, mrk_text, err) in enumerate(results, start=1)
    ]
    df = _build_dataframe(rows)

    success_count = sum(1 for _, _, err in results if not err)
    fail_count = total - success_count
    st.success(f"생성 완료 — 성공 {success_count}건 / 실패 {fail_count}건")

    if fail_count:
        failed = [isbn for isbn, _, err in results if err]
        with st.expander(f"실패 목록 ({fail_count}건)"):
            st.write(", ".join(failed))

    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "CSV 파일 다운로드 (.csv)",
        data=csv_bytes,
        file_name="평가결과.csv",
        mime="text/csv",
    )
