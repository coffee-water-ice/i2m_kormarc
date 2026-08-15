"""
auth_gate.py
공개 배포용 간단 비밀번호 잠금.

HuggingFace Space는 "비공개" 아니면 "공개"뿐이고 "링크를 아는 사람만"이라는
중간 단계가 없다. 공개로 두면 프로필 목록과 검색에 노출되므로, 들어온 사람이
변환을 실행해 OpenAI·알라딘 키를 소모할 수 있다(키 값은 안 보여도 키를 쓰는
행위는 가능하다). 그래서 앱 앞단에서 한 번 막는다.

APP_PASSWORD 환경변수가 없으면 잠금은 비활성이다 — 로컬 개발에서 매번 입력하는
번거로움을 없애기 위함이며, 배포 환경에서는 Space Secret으로 반드시 설정할 것.

한계를 분명히 해둔다. 이건 사용자 구분이 없는 공용 비밀번호이고, 비밀번호가
새면 그대로 뚫린다. 계정 단위 통제가 필요하면 Space를 비공개로 두고 HF 계정을
초대하는 방식을 써야 한다.

모든 페이지가 각자 실행되므로(Streamlit 멀티페이지 구조) 페이지마다 맨 위에서
require_password()를 호출해야 한다. 한 곳이라도 빠지면 그 페이지로 바로 들어올 수 있다.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st

_SESSION_KEY = "_auth_ok"


def _expected_password() -> str:
    return (os.environ.get("APP_PASSWORD") or "").strip()


def is_locked() -> bool:
    """잠금이 켜져 있는지(= APP_PASSWORD가 설정돼 있는지)."""
    return bool(_expected_password())


def require_password() -> None:
    """
    인증되지 않았으면 비밀번호 화면을 그리고 st.stop()으로 페이지 실행을 멈춘다.
    APP_PASSWORD가 없으면 아무 일도 하지 않는다.
    """
    expected = _expected_password()
    if not expected:
        return

    if st.session_state.get(_SESSION_KEY):
        return

    st.markdown("### 🔒 I2M KORMARC 통합 변환 시스템")
    st.caption("접근하려면 팀에서 공유한 비밀번호를 입력하세요.")

    with st.form("auth_form"):
        entered = st.text_input("비밀번호", type="password", label_visibility="collapsed")
        submitted = st.form_submit_button("입장")

    if submitted:
        # compare_digest: 앞자리부터 비교하다 틀리면 바로 반환하는 == 와 달리
        # 항상 같은 시간이 걸린다. 응답 시간 차이로 비밀번호를 알아내는 것을 막는다.
        if hmac.compare_digest(entered, expected):
            st.session_state[_SESSION_KEY] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")

    st.stop()
