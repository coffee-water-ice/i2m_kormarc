"""
pages/2_2025년_코드_원본.py
"통합 이전 코드 > 2025년 코드"(1215_main.py, 5284줄) 원본을 그대로 구동하는 비교용 페이지.

목적: 새로 통합된 파이프라인(1_ISBN_변환.py + FastAPI 백엔드)과 원본 2025년 코드가
같은 ISBN에 대해 어떤 MARC 결과를 내는지 나란히 비교하기 위함.

절대 원칙(사용자 지시):
- 원본 파일 `통합 이전 코드/2025년 코드/1215_main.py`은 단 한 글자도 수정하지 않는다.
  이 페이지는 그 파일을 읽어서(read-only) exec()로 재생(replay)할 뿐이다. 원본이
  이미 완결된 자체 Streamlit 앱(자체 st.header/st.form UI 포함)이므로, 로직을
  다시 옮겨 적지 않고 파일 전체를 이 페이지의 실행 컨텍스트 안에서 그대로 돌린다.
- 이 페이지는 우리 FastAPI 백엔드(app.py)나 Render를 전혀 거치지 않는다.
  원본 코드가 원래 하던 대로, 알라딘/OpenAI/구글시트 등 외부 API를 이 Streamlit
  프로세스 안에서 직접 호출한다(api_client.py 미사용).

실행에 필요한 비밀키:
  원본 코드는 os.getenv(...) 우선, 없으면 st.secrets로 폴백하되, 구글시트
  연동(st.secrets["gspread"])과 일부 알라딘 조회(st.secrets["aladin"]["ttbkey"])는
  st.secrets만 직접 참조한다(원본 코드 그대로이므로 여기서 바꿀 수 없다).
  로컬에서는 .streamlit/secrets.toml에 i2m_kormarc_2026_api_keys.env와 동일한
  값을 채워 두었다(git에는 올라가지 않음). Streamlit Cloud 등 다른 환경에
  배포할 경우, 그 배포 환경의 시크릿 관리 화면에도 동일한 키
  (OPENAI_API_KEY / ALADIN_TTB_KEY / NLK_CERT_KEY / [aladin].ttbkey / [gspread]…)를
  등록해야 이 페이지가 정상 동작한다.

부수 효과: 원본 코드의 run_and_export()가 ./output/ 아래에 .mrc/.mrk 파일을
그대로 저장한다(원본 동작 그대로, .gitignore 처리됨).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="2025년 코드(원본) | I2M KORMARC", page_icon="🗄️", layout="wide"
)
st.title("2025년 코드 (원본, 비교용)")
st.caption(
    "통합 이전 '2025년 코드'(1215_main.py, 5284줄)를 수정 없이 그대로 실행합니다. "
    "새 통합 파이프라인(← ISBN 변환 페이지)과의 결과 차이를 비교하는 용도입니다. "
    "이 페이지는 FastAPI 백엔드/Render를 거치지 않고, 원본이 원래 하던 대로 "
    "외부 API를 이 Streamlit 프로세스에서 직접 호출합니다."
)
st.divider()

_LEGACY_PATH = (
    Path(__file__).resolve().parents[2]
    / "통합 이전 코드"
    / "2025년 코드"
    / "1215_main.py"
)

if not _LEGACY_PATH.exists():
    st.error(f"원본 파일을 찾을 수 없습니다: {_LEGACY_PATH}")
    st.info(
        "이 페이지는 `I2M 통합 코드/통합 이전 코드/2025년 코드/1215_main.py`가 "
        "i2m_kormarc와 같은 저장소 상위 경로에 있어야 동작합니다."
    )
    st.stop()

# 원본 파일을 있는 그대로, 정식 모듈 로딩 방식으로 실행한다 — 읽기만 하고
# 한 글자도 바꾸지 않는다. importlib을 쓰는 이유: 원본이 @dataclass를 쓰는데,
# dataclasses 내부 구현이 cls.__module__로 sys.modules를 다시 찾아보기 때문에
# (KW_ONLY 등 문자열 애너테이션 해석용) 단순 exec(code, {"__name__": ...})만으로는
# sys.modules에 그 이름이 없어 AttributeError가 난다. importlib의 표준 절차
# (module_from_spec → sys.modules 등록 → exec_module)를 그대로 따라야 한다.
_MODULE_NAME = "legacy_2025_code"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _LEGACY_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = _module
_spec.loader.exec_module(_module)
