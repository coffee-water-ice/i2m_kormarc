"""
pages/1_ISBN_변환.py
041(언어코드)/546(언어주기) + 245/246/500/700/710/900/940(245 계열) +
260(발행사항)/300(형태사항) + 653(자유주제어) 변환 페이지 —
streamlit_app.py(Home)에서 분리.

원래 streamlit_app.py 전체였던 내용을 그대로 옮겼다. Streamlit 멀티페이지 구조에서는
루트의 streamlit_app.py가 진입점 겸 Home이 되고, pages/ 안의 파일들이 사이드바에
자동으로 추가 페이지로 노출된다.
"""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from api_client import convert_isbn, convert_batch


st.set_page_config(page_title="ISBN 변환 | I2M KORMARC", page_icon="📚", layout="wide")
st.title("KORMARC 자동 생성 시스템(I2M)")
st.caption("FastAPI 백엔드(`/api/convert`)를 호출해 MARC 결과를 보여줍니다.")

# NOTE: build_pub_location_bundle()의 실제 source 값 기준 (2026-07-08 정리 후).
# 원본 260+300/streamlit_app.py는 "KPIPA_API→MCST"/"ALADIN→MCST"라는, 이미 폐기된
# 문체부(MCST) 경로의 라벨을 쓰고 있었다 — 실제로는 행안부(MOIS) API로 대체되었으므로
# 이관하면서 함께 바로잡았다.
_SOURCE_LABEL = {
    "ISBN_PREFIX_DB":      "📖 ISBN발행자번호-발행지 연결표",
    "KPIPA_API→DB":        "🔗 KPIPA API → 발행처명-주소 연결표",
    "ALADIN→DB":           "📚 알라딘 → 발행처명-주소 연결표",
    "ALADIN→IMPRINT→DB":   "📚 알라딘 → 임프린트 → 발행처명-주소 연결표",
    "ALADIN→IMPRINT→MOIS": "🏛️ 알라딘 → 임프린트 → 행정안전부 API",
    "FALLBACK":            "⚠️ 모든 경로 실패 (출판지 미상)",
}


def _extract_field(mrk_text: str, tag: str) -> str:
    """mrk_text에서 특정 태그 행만 추출."""
    for line in (mrk_text or "").splitlines():
        if line.startswith(f"={tag}"):
            return line
    return ""


def _sort_mrk_lines(mrk_text: str) -> str:
    """MRK 텍스트를 태그(3자리 숫자) 오름차순으로 정렬. 같은 태그가 여러 줄이면
    원래 순서를 유지한다(sorted()는 stable sort). 태그를 못 읽는 줄은 맨 뒤로 보낸다."""
    lines = [line for line in (mrk_text or "").splitlines() if line.strip()]

    def _tag_key(line: str) -> int:
        m = re.match(r"^=(\d{3})", line)
        return int(m.group(1)) if m else 999

    return "\n".join(sorted(lines, key=_tag_key))


def _results_to_dataframe(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        meta = r.get("meta") or {}
        mrk = r.get("mrk_text", "")
        rows.append({
            "ISBN":       r.get("isbn", ""),
            "제목":       meta.get("aladin_title", ""),
            "발행처":     meta.get("publisher_raw", ""),
            "발행지":     meta.get("place_display", ""),
            "발행년도":   meta.get("pubyear", ""),
            "245필드":    _extract_field(mrk, "245"),
            "246필드":    _extract_field(mrk, "246"),
            "700필드":    _extract_field(mrk, "700"),
            "260필드":    _extract_field(mrk, "260"),
            "300필드":    _extract_field(mrk, "300"),
            "발행지 출처": _SOURCE_LABEL.get(meta.get("bundle_source", ""), meta.get("bundle_source", "")),
            "오류":       r.get("error", "") or "",
        })
    return pd.DataFrame(rows)


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ── 탭 구성 ────────────────────────────────────────────────────
tab_single, tab_batch = st.tabs(["단건 변환", "일괄 변환 (엑셀 다운로드)"])


# ══════════════════════════════════════════════════════════════
# 탭 1: 단건 변환
# ══════════════════════════════════════════════════════════════
with tab_single:
    isbn = st.text_input("ISBN-13", placeholder="예: 9788937462849").strip()

    if st.button("변환 실행", type="primary", key="btn_single"):
        if not isbn:
            st.warning("ISBN을 입력해 주세요.")
        else:
            with st.spinner("변환 중..."):
                st.session_state["single_result"] = convert_isbn(isbn)
            # 직접 수정 textarea의 key에 쓰는 일련번호 — ISBN만으로 key를 잡으면
            # 같은 ISBN을 다시 변환했을 때 Streamlit이 새 value를 무시하고 이전에
            # 사용자가 편집한(혹은 이전 결과로 채워졌던) 위젯 상태를 그대로 재사용해
            # 새로 변환한 내용이 화면에 반영되지 않는 문제가 있었다. 매 변환마다
            # 값을 늘려 항상 새 위젯 인스턴스로 취급되게 한다.
            st.session_state["single_result_seq"] = st.session_state.get("single_result_seq", 0) + 1

    # 결과를 session_state에 보관 — 아래 직접 수정 textarea를 편집할 때마다
    # Streamlit이 스크립트를 다시 실행하는데, 그때도 버튼을 다시 누르지 않고
    # 마지막 변환 결과가 계속 표시되도록 하기 위함.
    result = st.session_state.get("single_result")
    if result is not None:
        if result.get("error"):
            st.error(result["error"])
        else:
            st.success("변환 완료")
            meta = result.get("meta", {})

            # ── 소요시간 · 토큰 사용량 (간단히 한 줄로) ──────────────
            elapsed_ms = meta.get("elapsed_ms")
            token_usage = meta.get("token_usage") or {}
            total_tokens = token_usage.get("total_tokens", 0)
            if elapsed_ms is not None:
                st.caption(f"⏱️ 소요시간 **{elapsed_ms / 1000:.1f}초**  ·  🔢 GPT 토큰 **{total_tokens:,}개**")

            # ── 직접 수정 파트 (별도 이름 없이, 태그 오름차순 정렬 상태로 표시) ──
            sorted_mrk = _sort_mrk_lines(result.get("mrk_text", ""))
            seq = st.session_state.get("single_result_seq", 0)
            edited_mrk = st.text_area(
                "MRK 직접 수정",
                value=sorted_mrk,
                height=280,
                key=f"mrk_edit_{result.get('isbn', '')}_{seq}",
                label_visibility="collapsed",
            )

            # ── MRK 텍스트 — 위에서 수정한 내용을 그대로 반영 ──────
            st.subheader("MRK 텍스트")
            st.code(edited_mrk, language="text")

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


# ══════════════════════════════════════════════════════════════
# 탭 2: 일괄 변환
# ══════════════════════════════════════════════════════════════
with tab_batch:
    st.markdown("ISBN을 한 줄에 하나씩 입력하거나, ISBN 열이 있는 엑셀/CSV 파일을 업로드하세요.")

    col_text, col_file = st.columns([1, 1], gap="large")

    with col_text:
        st.markdown("**직접 입력**")
        raw_text = st.text_area(
            "ISBN 목록 (한 줄에 하나)",
            placeholder="9788937462849\n9791162540091\n9788936434120",
            height=200,
            key="batch_text",
        )

    with col_file:
        st.markdown("**파일 업로드** (Excel / CSV)")
        uploaded = st.file_uploader(
            "ISBN 열 이름: `isbn` 또는 `ISBN`",
            type=["xlsx", "xls", "csv"],
            key="batch_file",
        )

    # ISBN 목록 수집
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

            col_name = next(
                (c for c in file_df.columns if c.strip().lower() == "isbn"), None
            )
            if col_name:
                for val in file_df[col_name].dropna():
                    cleaned = re.sub(r"[^0-9X]", "", str(val).strip().upper())
                    if len(cleaned) in (10, 13):
                        isbn_list.append(cleaned)
                st.success(f"파일에서 ISBN {len(isbn_list)}건 인식")
            else:
                st.warning("파일에 `isbn` 또는 `ISBN` 열이 없습니다.")
        except Exception as e:
            st.error(f"파일 읽기 실패: {e}")

    # 중복 제거, 순서 유지
    seen: set[str] = set()
    unique_isbns = [x for x in isbn_list if not (x in seen or seen.add(x))]

    if unique_isbns:
        st.info(f"변환 대상: **{len(unique_isbns)}건** (중복 제거 후)")

    if st.button("일괄 변환 실행", type="primary", key="btn_batch", disabled=not unique_isbns):
        progress = st.progress(0, text="변환 준비 중...")
        status_text = st.empty()

        # 10건씩 나눠서 진행률 표시
        chunk_size = 10
        all_results: list[dict] = []
        total = len(unique_isbns)

        for i in range(0, total, chunk_size):
            chunk = unique_isbns[i : i + chunk_size]
            status_text.text(f"{i + 1} ~ {min(i + chunk_size, total)} / {total} 변환 중...")
            jobs = [[isbn] for isbn in chunk]
            chunk_results = convert_batch(jobs)
            all_results.extend(chunk_results)
            progress.progress(min(i + chunk_size, total) / total, text=f"{min(i + chunk_size, total)}/{total} 완료")

        progress.empty()
        status_text.empty()

        df = _results_to_dataframe(all_results)
        success_count = df["오류"].eq("").sum()
        fail_count = total - success_count

        st.success(f"변환 완료 — 성공 {success_count}건 / 실패 {fail_count}건")
        st.dataframe(df, width="stretch", hide_index=True)

        csv_bytes = _to_csv_bytes(df)
        st.download_button(
            label="CSV 파일 다운로드 (.csv)",
            data=csv_bytes,
            file_name="marc_변환결과.csv",
            mime="text/csv",
        )
