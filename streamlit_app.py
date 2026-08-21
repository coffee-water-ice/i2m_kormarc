"""
streamlit_app.py
Streamlit 멀티페이지 앱의 진입점 겸 Home.

041/245/653/260+300 4개 폴더 + 2025년 코드 이식이 모두 끝나 전 필드가 실동작하므로,
이 페이지는 더 이상 "어떤 필드가 스텁인지"를 보여줄 필요가 없다. 대신 배포된
백엔드의 시스템 상태(연결 여부·주소·마지막 배포 시각·외부 API 키 설정 여부)를
확인하는 용도로 쓴다.

실제 변환 UI는 pages/1_2026_ISBN_변환.py 로 옮겼다.
"""

from __future__ import annotations

import streamlit as st

from api_client import check_backend_health, get_backend_url
from auth_gate import require_password

st.set_page_config(page_title="I2M KORMARC 통합 시스템", page_icon="📚", layout="wide")

# 공개 배포 시 비밀번호 잠금. APP_PASSWORD 미설정이면 아무 일도 하지 않는다.
# 페이지마다 각자 실행되므로 모든 진입점에서 호출해야 한다.
require_password()


@st.cache_data(ttl=60, show_spinner="🔄️ Render 콜드 스타트 중... (최대 1분 정도 걸릴 수 있습니다)")
def _cached_health_check() -> dict:
    """
    check_backend_health()를 60초간 캐싱한다. Streamlit은 페이지의 위젯을
    조작할 때마다 스크립트 전체를 다시 실행하므로, 캐싱이 없으면 방문할
    때마다 매번 백엔드까지 새로 왕복하게 된다 — 특히 Render 무료/스타터
    플랜은 슬립 상태에서 깨어나는 데 수십 초가 걸릴 수 있어(콜드 스타트)
    체감 지연이 컸다. show_spinner 문구로 그 대기 중임을 알려준다.
    """
    return check_backend_health()


st.title("I2M KORMARC 통합 변환 시스템")
st.caption("041 / 245 / 653 / 260+300 +2025년 코드 - 통합 완료, 전 필드 실동작")

# ── 시스템 상태 ────────────────────────────────────────────────
st.subheader("시스템 상태")

health = _cached_health_check()
version = health.get("version") or {}
secrets_configured = health.get("secrets_configured")

st.markdown("**백엔드 및 배포**")

# 백엔드 주소를 그대로 보여주면 배포 환경에서 "localhost:8000"으로 표시되어
# 이용자가 "내 PC에서만 동작하나?"로 오해한다. 실제로는 Streamlit이 서버에서
# 화면을 그리므로, 이 localhost는 방문자 PC가 아니라 컨테이너 내부를 가리킨다.
# 주소를 감추지는 않되(디버깅에 필요) 무엇을 뜻하는지 함께 표시한다.
_backend_url = get_backend_url()
if "localhost" in _backend_url or "127.0.0.1" in _backend_url:
    st.markdown(
        f"🔗 백엔드 주소: `{_backend_url}` "
        "<span style='color:gray'>— 같은 서버 안에서 통신하는 내부 주소입니다. "
        "이용자 PC와 무관하며 어디서 접속해도 동일하게 동작합니다.</span>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(f"🔗 백엔드 주소: `{_backend_url}`")
if health["ok"]:
    st.markdown(f"✅ 백엔드 연결 정상 ({health['detail']})")
else:
    st.markdown(f'⛔ "{health["detail"]}"')
if version.get("deployed_at"):
    commit = version.get("commit", "?")
    commit_msg = version.get("commit_message", "")
    commit_display = f"{commit}: {commit_msg}" if commit_msg else commit
    st.markdown(f"🔄️ 마지막 배포(갱신) 시각: {version['deployed_at']} (KST) · 커밋: `{commit_display}`")

st.markdown("**외부 API 키 설정 여부**")
if secrets_configured:
    _SECRET_LABELS = {
        "aladin_ttb_key":      "알라딘",
        "openai_api_key":      "OpenAI",
        "kpipa_api_key":       "KPIPA",
        "data_go_kr":          "행정안전부",
        "nlk_cert_key":        "국립중앙도서관(NLK)",
        "gspread_credentials": "Google Sheets",
    }
    # 키가 설정되어 있어도 제공처가 서비스를 종료하면 기능은 동작하지 않는다.
    # ✅만 보고 "된다"고 읽지 않도록 알려진 사례를 별도 표시한다.
    _KNOWN_ISSUES = {
        "naver_search": "제공처 API 종료 — 키와 무관하게 사용 불가",
    }
    items = []
    for key, label in _SECRET_LABELS.items():
        ok = secrets_configured.get(key, False)
        if ok and key in _KNOWN_ISSUES:
            items.append(f"⚠️ {label}")
        else:
            items.append(f"{'✅' if ok else '⛔'} {label}")
    st.markdown("  ·  ".join(items))
    st.caption("✅ 키 설정됨 · ⛔ 키 없음 · ⚠️ 키는 있으나 사용 불가")
    for key, reason in _KNOWN_ISSUES.items():
        if secrets_configured.get(key):
            st.caption(f"⚠️ {_SECRET_LABELS[key]}: {reason}")
else:
    st.markdown("⛔ 백엔드에 연결되지 않아 확인할 수 없습니다.")

st.divider()

# ── 지원 필드 목록 ────────────────────────────────────────────
st.subheader("지원 MARC 필드")
st.markdown(
    "020 · 041 · 546 · 245 · 246 · 500 · 700 · 710 · 900 · 940 · "
    "007 · 008 · 490 · 830 · 260 · 300 · 653 · 950 — "
    "모두 `pages/1_2026_ISBN_변환.py`에서 실제로 생성됩니다."
)

st.divider()
st.markdown(
    "왼쪽 사이드바에서 페이지를 선택하세요.\n\n"
    "- **2026 ISBN 변환** — 위 필드를 실제로 생성하는 단건/일괄 변환 페이지\n"
    "- **2025 I2M** — 통합 이전 '2025년 코드' 원본을 그대로 실행해 결과를 비교하는 페이지"
)

with st.expander("문서"):
    st.markdown(
        "- `docs/INTEGRATION_SURVEY.md` — 4개 폴더 구조/내용 설명서\n"
        "- `docs/INTEGRATION_PRINCIPLES.md` — 통합 원칙\n"
        "- `README.md` — 실행 방법, 디렉토리 구조"
    )
