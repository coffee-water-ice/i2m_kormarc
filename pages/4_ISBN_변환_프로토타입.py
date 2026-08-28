"""
pages/4_ISBN_변환_프로토타입.py
`prototypes/mrk_editor_prototype.html`(정적 HTML/JS 목업)의 "필드별로 직접 클릭해서 고치는"
MRK 편집 UX를 참고해 만든 **프로토타입** 페이지.

스트림릿은 그 목업이 쓰는 contenteditable 클릭 편집·Alt+글자 서브필드 삽입·Enter 다음 필드
이동 같은 세밀한 DOM 조작을 기본 위젯으로 지원하지 않는다. 그래서 픽셀 단위 재현이 아니라
"필드를 표 형태로 구조화해서 셀 단위로 바로 고친다"는 핵심 아이디어만 `st.data_editor`로
재해석했다. (사용자 승인: 스트림릿 네이티브 재해석 방식.)

주의: 이 페이지는 pages/1_2026_ISBN_변환.py를 대체하지 않는다 — 그 페이지는 이 작업으로
한 글자도 바뀌지 않았다. 아래 헬퍼 상당수(_KDC_CLASS_NAME/_kdc_label/_replace_056/
_SOURCE_LABEL, 소요시간·토큰 배너, 056 후보 막대그래프)는 pages/1의 것과 의도적으로
동일하게 중복시켰다 — 이 프로젝트는 페이지 파일끼리 서로 import하지 않는 관례를 따른다.
"""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from api_client import convert_isbn
from auth_gate import require_password


st.set_page_config(page_title="ISBN 변환 프로토타입 | I2M KORMARC", page_icon="🧪", layout="wide")
require_password()
st.title("MRK 구조화 편집기 (프로토타입)")
st.caption(
    "`mrk_editor_prototype.html` 목업의 필드별 편집 아이디어를 스트림릿 위젯으로 재해석한 "
    "프로토타입입니다. 기존 **[ISBN 변환]** 페이지는 그대로 유지됩니다."
)


# ── pages/1과 동일한 헬퍼 (의도적 중복 — 위 docstring 참고) ──────────────
_SOURCE_LABEL = {
    "ISBN_PREFIX_DB":      "📖 ISBN발행자번호-발행지 연결표",
    "KPIPA_API→DB":        "🔗 KPIPA API → 발행처명-주소 연결표",
    "ALADIN→DB":           "📚 알라딘 → 발행처명-주소 연결표",
    "ALADIN→IMPRINT→DB":   "📚 알라딘 → 임프린트 → 발행처명-주소 연결표",
    "ALADIN→IMPRINT→MOIS": "🏛️ 알라딘 → 임프린트 → 행정안전부 API",
    "ALADIN(음차)→DB":      "🔤 알라딘(영문→한글 음차) → 발행처명-주소 연결표",
    "ALADIN(음차)→MOIS":    "🔤 알라딘(영문→한글 음차) → 행정안전부 API",
    "FALLBACK":            "⚠️ 모든 경로 실패 (출판지 미상)",
}

_KDC_CLASS_NAME = {
    "0": "총류", "1": "철학", "2": "종교", "3": "사회과학", "4": "자연과학",
    "5": "기술과학", "6": "예술", "7": "언어", "8": "문학", "9": "역사",
}


def _kdc_label(code: str) -> str:
    name = _KDC_CLASS_NAME.get((code or "")[:1], "")
    return f"{code} · {name}" if name else code


def _replace_056(mrk_text: str, kdc: str) -> str:
    lines = (mrk_text or "").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("=056"):
            lines[i] = re.sub(r"\$a[^$]*", f"$a{kdc}", line, count=1)
            break
    return "\n".join(lines)


# ── 프로토타입 전용: mrk_editor_prototype.html의 TAG_META/REQUIRED 이식 ──
_TAG_META = {
    "007": "자료유형 고정길이 부호", "008": "부호화정보(발행년·언어 등 고정 항목)",
    "020": "표준번호(ISBN)", "041": "언어부호", "056": "KDC 분류기호",
    "245": "표제와 책임표시", "246": "다른 표제",
    "260": "발행사항 — 발행지·발행처·발행년", "300": "형태사항 — 페이지·크기",
    "500": "일반주기", "546": "언어주기", "653": "비통제 주제어",
    "700": "부출표목 — 개인명", "900": "부출표목(원어 표기)", "950": "가격",
}
_REQUIRED = {"245": ["a"], "260": ["a", "b", "c"], "300": ["a"], "700": ["a"]}


def _is_control_tag(tag: str) -> bool:
    return tag.isdigit() and int(tag) < 10


def _mrk_to_rows(mrk_text: str) -> pd.DataFrame:
    """mrk_editor_prototype.html의 parseMrkText()를 파이썬으로 옮긴 것 —
    `=TAG  IND1IND2$코드값...` 형식을 표(행) 형태로 분해한다."""
    rows: list[dict] = []
    for line in (mrk_text or "").splitlines():
        # 008처럼 고정 길이 제어필드는 끝 공백이 자릿수를 채우는 의미 있는 값이라
        # rstrip()으로 지우면 안 된다(splitlines()가 이미 줄바꿈 문자는 제거해준다) —
        # 실제 백엔드 출력(008 마지막에 공백 2칸)으로 테스트하다가 발견한 문제.
        if not line.strip():
            continue
        m = re.match(r"^=(\d{3})\s{2}(.*)$", line)
        if not m:
            continue
        tag, rest = m.group(1), m.group(2)
        if _is_control_tag(tag):
            rows.append({"태그": tag, "Ind1": "", "Ind2": "", "내용": rest})
            continue
        ind1 = rest[0] if len(rest) > 0 else "\\"
        ind2 = rest[1] if len(rest) > 1 else "\\"
        rows.append({"태그": tag, "Ind1": ind1, "Ind2": ind2, "내용": rest[2:]})
    return pd.DataFrame(rows, columns=["태그", "Ind1", "Ind2", "내용"])


def _rows_to_mrk(df: pd.DataFrame) -> str:
    """serializeCard()를 옮긴 것 — 표를 다시 `.mrk` 텍스트로 합친다."""
    lines: list[str] = []
    for _, row in df.iterrows():
        tag = str(row.get("태그", "") or "").strip()
        if not tag:
            continue
        content = str(row.get("내용", "") or "")
        if _is_control_tag(tag):
            lines.append(f"={tag}  {content}")
            continue
        ind1 = (str(row.get("Ind1", "") or "").strip() or "\\")[:1]
        ind2 = (str(row.get("Ind2", "") or "").strip() or "\\")[:1]
        lines.append(f"={tag}  {ind1}{ind2}{content}")
    return "\n".join(lines)


def _missing_subfields(df: pd.DataFrame) -> list[str]:
    """REQUIRED 맵 기준 필수 서브필드 누락 목록 — recomputeRowWarning()에 대응."""
    problems = []
    for _, row in df.iterrows():
        tag = str(row.get("태그", "") or "").strip()
        need = _REQUIRED.get(tag)
        if not need:
            continue
        present = set(re.findall(r"\$(.)", str(row.get("내용", "") or "")))
        missing = [c for c in need if c not in present]
        if missing:
            problems.append(f"={tag}: $" + ", $".join(missing) + " 누락")
    return problems


# ── 세션 상태: 변환 내역 ──────────────────────────────────────────────
if "proto_history" not in st.session_state:
    st.session_state["proto_history"] = []  # list[dict]
if "proto_uid_counter" not in st.session_state:
    st.session_state["proto_uid_counter"] = 0
if "proto_current_uid" not in st.session_state:
    st.session_state["proto_current_uid"] = None


def _record_title(mrk_text: str) -> str:
    m = re.search(r"^=245\s{2}.*?\$a([^$]*)", mrk_text or "", re.MULTILINE)
    if not m:
        return "(제목 없음)"
    return m.group(1).strip().rstrip("/").strip() or "(제목 없음)"


# ── 사이드바: 변환 내역 ──────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**변환 내역** ({len(st.session_state['proto_history'])}건)")
    for rec in reversed(st.session_state["proto_history"]):
        active = rec["uid"] == st.session_state["proto_current_uid"]
        label = f"{'🟠 ' if rec['edited'] else ''}{rec['title']}\n\n`{rec['isbn']}`"
        if st.button(label, key=f"hist_btn_{rec['uid']}", type="primary" if active else "secondary",
                     width="stretch"):
            st.session_state["proto_current_uid"] = rec["uid"]
            st.rerun()
    st.caption("항목을 선택하면 편집 카드와 분류기호 패널이 함께 갱신됩니다.")


# ── 상단: ISBN 입력 + 변환 실행 ─────────────────────────────────────
col_isbn, col_btn = st.columns([3, 1])
with col_isbn:
    isbn = st.text_input("ISBN-13", placeholder="예: 9788937462849", key="proto_isbn_input").strip()
with col_btn:
    st.markdown("<div style='height:1.85em'></div>", unsafe_allow_html=True)
    convert_clicked = st.button("변환 실행", type="primary", key="proto_convert_btn")

if convert_clicked:
    if not isbn:
        st.warning("ISBN을 입력해 주세요.")
    else:
        with st.spinner("변환 중..."):
            result = convert_isbn(isbn)
        if result.get("error"):
            st.error(result["error"])
        else:
            uid = st.session_state["proto_uid_counter"]
            st.session_state["proto_uid_counter"] += 1
            mrk_text = result.get("mrk_text", "")
            st.session_state["proto_history"].append({
                "uid": uid,
                "isbn": isbn,
                "title": _record_title(mrk_text),
                "meta": result.get("meta", {}),
                "rows_df": _mrk_to_rows(mrk_text),
                "seq": 0,
                "edited": False,
            })
            st.session_state["proto_current_uid"] = uid
            st.rerun()


# ── 메인: 현재 선택된 레코드 편집 ────────────────────────────────────
current = next(
    (r for r in st.session_state["proto_history"] if r["uid"] == st.session_state["proto_current_uid"]),
    None,
)

if current is None:
    st.info("ISBN을 입력하고 **변환 실행**을 누르면 편집 화면이 나타납니다.")
else:
    meta = current["meta"]
    elapsed_ms = meta.get("elapsed_ms")
    token_usage = meta.get("token_usage") or {}
    total_tokens = token_usage.get("total_tokens", 0)
    if elapsed_ms is not None:
        st.markdown(
            f'<p style="font-size:1.2em; color:gray; margin:0 0 0.5rem 0;">'
            f"⏱️ 소요시간 <b>{elapsed_ms / 1000:.1f}초</b>"
            f"  ·  🔢 GPT 토큰 <b>{total_tokens:,}개</b></p>",
            unsafe_allow_html=True,
        )

    col_editor, col_class = st.columns([3, 2], gap="large")

    with col_editor:
        st.subheader("MRK 편집")
        st.caption("필드를 표에서 직접 클릭해 값을 고칠 수 있어요. 행 추가/삭제도 가능합니다.")

        editor_key = f"proto_editor_{current['uid']}_{current['seq']}"
        edited_df = st.data_editor(
            current["rows_df"],
            key=editor_key,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "태그": st.column_config.TextColumn("태그", width="small"),
                "Ind1": st.column_config.TextColumn("Ind1", width="small"),
                "Ind2": st.column_config.TextColumn("Ind2", width="small"),
                "내용": st.column_config.TextColumn("내용 ($코드값...)", width="large"),
            },
        )
        current["rows_df"] = edited_df

        problems = _missing_subfields(edited_df)
        if problems:
            st.warning("**필수 서브필드 누락**\n\n" + "\n\n".join(problems))

        with st.expander("필드 설명 (참고용)", expanded=False):
            st.caption(" · ".join(f"`{t}` {d}" for t, d in _TAG_META.items()))

        # ── 원본 텍스트 토글 ──────────────────────────────────────
        show_raw = st.toggle("⇄ 원본 텍스트 보기/수정", key=f"proto_raw_toggle_{current['uid']}")
        if show_raw:
            st.caption("여기서 직접 고친 뒤 아래 버튼으로 위 표에 반영할 수 있어요.")
            raw_key = f"proto_raw_text_{current['uid']}_{current['seq']}"
            raw_text = st.text_area(
                "원본 MRK 텍스트", value=_rows_to_mrk(edited_df), height=240,
                key=raw_key, label_visibility="collapsed",
            )
            if st.button("구조화된 편집에 반영", key=f"proto_raw_apply_{current['uid']}_{current['seq']}"):
                parsed = _mrk_to_rows(raw_text)
                if parsed.empty:
                    st.error('파싱할 수 있는 필드를 찾지 못했어요. "=245  00$a..." 형식인지 확인해주세요.')
                else:
                    current["rows_df"] = parsed
                    current["seq"] += 1
                    current["edited"] = True
                    st.rerun()

    with col_class:
        kdc_candidates = meta.get("kdc_candidates") or []
        final_df = edited_df.copy()

        if kdc_candidates:
            st.subheader("056 KDC 분류기호")

            ratio = meta.get("kdc_margin_ratio")
            if meta.get("kdc_low_confidence"):
                st.warning("**1순위와 2순위가 대등합니다 — 검토가 필요합니다.**")
            elif ratio:
                st.caption(f"1순위가 2순위보다 **{ratio:g}배** 우세합니다.")

            top_prob = max(c["prob"] for c in kdc_candidates) or 1.0
            bars = []
            for rank, c in enumerate(kdc_candidates, start=1):
                width = max(4, round(c["prob"] / top_prob * 100))
                shade = "#4a72c4" if rank == 1 else "#a9b6cd"
                bars.append(
                    f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0;">'
                    f'<span style="width:6.5em;font-weight:{600 if rank == 1 else 400};">'
                    f'{_kdc_label(c["kdc"])}</span>'
                    f'<span style="flex:0 0 {width}%;height:10px;background:{shade};'
                    f'border-radius:2px;"></span>'
                    f'<span style="color:gray;font-size:0.85em;">{c["prob"]:.1%}</span>'
                    f"</div>"
                )
            st.markdown("".join(bars), unsafe_allow_html=True)

            chosen = st.radio(
                "분류기호 선택", [c["kdc"] for c in kdc_candidates],
                format_func=_kdc_label, key=f"proto_kdc_pick_{current['uid']}_{current['seq']}",
            )
            detail = st.text_input(
                "세목 (직접 입력)", value="", max_chars=8, placeholder="예: 8 → 808",
                key=f"proto_kdc_detail_{current['uid']}_{current['seq']}",
            )

            final_kdc = f"{chosen}{detail.strip()}"
            edition = meta.get("kdc_edition", "")
            st.markdown(
                f"→ 적용될 값: `=056  \\\\$a{final_kdc}" + (f"$2{edition}" if edition else "") + "`"
            )

            if final_kdc != kdc_candidates[0]["kdc"]:
                mask = final_df["태그"].astype(str).str.strip() == "056"
                final_df.loc[mask, "내용"] = final_df.loc[mask, "내용"].apply(
                    lambda c: re.sub(r"\$a[^$]*", f"$a{final_kdc}", str(c), count=1)
                )
        elif meta.get("kdc_reason"):
            st.caption(f"056 미생성: {meta['kdc_reason']}")

    final_mrk = _rows_to_mrk(final_df)

    st.subheader("MRK 텍스트")
    st.code(final_mrk, language="text")

    dl_col, _ = st.columns([1, 3])
    with dl_col:
        st.download_button(
            "↓ .mrk 다운로드", data=final_mrk.encode("utf-8"),
            file_name=f"{current['isbn']}.mrk", mime="text/plain",
            key=f"proto_dl_{current['uid']}_{current['seq']}",
        )
    st.caption(
        "`.mrc`(ISO 2709 바이너리) 다운로드는 서버 측 변환 로직이 따로 필요해 "
        "이 프로토타입 범위에는 넣지 않았습니다."
    )

    source = meta.get("bundle_source", "")
    label = _SOURCE_LABEL.get(source, source or "알 수 없음")
    st.caption(f"발행지 출처: **{label}**")

    if meta.get("translation_book"):
        st.caption(
            f"번역서 판정: **원서명** `{meta.get('orig_title') or '(미확인)'}` · "
            f"**원저자명** `{meta.get('orig_author_en') or '(미확인)'}`"
        )

    with st.expander("메타 정보", expanded=False):
        st.json(meta)
