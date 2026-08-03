"""
streamlit_app.py
Streamlit 멀티페이지 앱의 진입점 겸 Home.

041/245/653/260+300 4개 폴더 + 2025년 코드 이식이 모두 끝나 전 필드가 실동작하므로,
이 페이지는 더 이상 "어떤 필드가 스텁인지"를 보여줄 필요가 없다. 대신 배포된
백엔드의 시스템 상태(연결 여부·주소·마지막 배포 시각·외부 API 키 설정 여부)를
확인하는 용도로 쓴다.

실제 변환 UI는 pages/1_ISBN_변환.py 로 옮겼다.
"""

from __future__ import annotations

import streamlit as st

from api_client import check_backend_health, get_backend_url

st.set_page_config(page_title="I2M KORMARC 통합 시스템", page_icon="📚", layout="wide")

st.title("I2M KORMARC 통합 변환 시스템")
st.caption("041 / 245 / 653 / 260+300 + 2025년 코드 — 통합 완료, 전 필드 실동작")

# ── 시스템 상태 ────────────────────────────────────────────────
st.subheader("시스템 상태")

health = check_backend_health()

if health["ok"]:
    st.success(f"백엔드 연결 정상 ({health['detail']})")
else:
    st.error(
        f"백엔드에 연결할 수 없습니다: {health['detail']}\n"
        "터미널에서 `uvicorn app:app --reload`로 백엔드를 먼저 실행하세요."
    )

st.markdown(f"🔗 백엔드 주소: `{get_backend_url()}`")

version = health.get("version") or {}
if version.get("deployed_at"):
    st.caption(f"마지막 배포(갱신) 시각: {version['deployed_at']} (KST)")

# 외부 API 키 설정 여부 — 기본 크기의 1/2~1/3 정도로 축소해 한 줄로 표시
st.markdown("**외부 API 키 설정 여부**")
secrets_configured = health.get("secrets_configured")
if secrets_configured:
    _SECRET_LABELS = {
        "aladin_ttb_key":      "알라딘",
        "openai_api_key":      "OpenAI",
        "kpipa_api_key":       "KPIPA",
        "data_go_kr":          "행정안전부",
        "nlk_cert_key":        "국립중앙도서관(NLK)",
        "naver_search":        "네이버 검색",
        "gspread_credentials": "Google Sheets",
    }
    items = []
    for key, label in _SECRET_LABELS.items():
        ok = secrets_configured.get(key, False)
        icon = "✅" if ok else "⚠️"
        items.append(f"{icon} {label}")
    st.markdown("  ·  ".join(items))
else:
    st.caption("백엔드에 연결되지 않아 확인할 수 없습니다.")

st.divider()

# ── 지원 필드 목록 ────────────────────────────────────────────
st.subheader("지원 MARC 필드")
st.markdown(
    "020 · 041 · 546 · 245 · 246 · 500 · 700 · 710 · 900 · 940 · "
    "007 · 008 · 490 · 830 · 260 · 300 · 653 · 950 — "
    "모두 `pages/1_ISBN_변환.py`에서 실제로 생성됩니다."
)

st.divider()
st.markdown(
    "왼쪽 사이드바에서 페이지를 선택하세요.\n\n"
    "- **1 ISBN 변환** — 위 필드를 실제로 생성하는 단건/일괄 변환 페이지"
)

with st.expander("문서"):
    st.markdown(
        "- `docs/INTEGRATION_SURVEY.md` — 4개 폴더 구조/내용 설명서\n"
        "- `docs/INTEGRATION_PRINCIPLES.md` — 통합 원칙\n"
        "- `README.md` — 실행 방법, 디렉토리 구조"
    )
