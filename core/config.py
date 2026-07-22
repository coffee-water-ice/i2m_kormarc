"""
core/config.py
통합 설정 — 653 폴더의 pydantic-settings 패턴(INTEGRATION_PRINCIPLES.md #4)을
전체 표준으로 채택하고, 041/245/260/300/653 5개 필드가 필요로 하는 키를 모두 선언한다.

653은 아직 스텁이라 해당 키들은 기본값("")만 채워둔 상태이며, 실제 로직으로
이식할 때 값을 채우면 코드 변경 없이 바로 동작한다.

Streamlit Cloud처럼 .env 파일이 없는 배포 환경을 위해, load_streamlit_secrets_into_env()로
.streamlit/secrets.toml → os.environ 브릿지를 제공한다(pydantic-settings 앞단의
"소스" 어댑터로만 사용 — 두 설정 체계를 경쟁시키지 않는다, INTEGRATION_PRINCIPLES.md #4).
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parents[1]
# 로컬 개발용 실제 키는 저장소 바깥(부모 폴더)의 i2m_2026.env에 둔다.
# git 저장소(i2m_kormarc/) 밖에 있어 .gitignore와 무관하게 커밋될 수 없다.
# Render/Streamlit Cloud 등 배포 환경에는 이 파일이 없고 환경변수를 직접 주입하므로
# 존재하지 않아도(pydantic-settings가 조용히 무시) 문제가 없다.
_ENV_FILE = _ROOT_DIR.parent / "i2m_2026.env"
_SECRETS_TOML = _ROOT_DIR / ".streamlit" / "secrets.toml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 알라딘 (041/245/260/300/653 공통) ────────────────────────
    aladin_ttb_key: str = Field(default="", description="알라딘 TTB API 키 (1순위)")
    aladin_ttb_key2: str = Field(default="", description="알라딘 TTB API 키 (2순위 fallback)")
    aladin_ttb_key3: str = Field(default="", description="알라딘 TTB API 키 (3순위 fallback)")

    # ── OpenAI (필드별 모델을 강제 통일하지 않음 — INTEGRATION_PRINCIPLES.md #2) ──
    openai_api_key: str = Field(default="", description="OpenAI API 키")
    openai_model_041: str = Field(default="gpt-4o", description="041/546 언어 판정 모델")
    openai_model_245: str = Field(default="gpt-4o", description="245 계열 원저자/원제 조회 모델")
    openai_model_300: str = Field(default="gpt-4o-mini", description="300 $b 삽화 판정 모델")
    openai_model_653: str = Field(default="gpt-4o", description="653 자유주제어 생성 모델")

    # ── KPIPA ─────────────────────────────────────────────────
    kpipa_api_key: str = Field(default="", description="KPIPA 출판유통통합전산망 OpenAPI 서비스키")

    # ── 행정안전부(MOIS) ──────────────────────────────────────
    data_go_kr: str = Field(default="", description="공공데이터포털 인증키 (행안부 출판사 조회)")

    # ── 국립중앙도서관(NLK) — 245/653 스텁 이식 시 사용 ─────────
    nlk_cert_key: str = Field(default="", description="국립중앙도서관 OpenAPI 인증키")

    # ── 네이버 (300 책소개 보강) ──────────────────────────────
    naver_search_key_id: str = Field(default="", description="네이버 검색 API Client ID")
    naver_search_key_secret: str = Field(default="", description="네이버 검색 API Client Secret")

    # ── Google Sheets (출판사 DB, 653 골든데이터) ───────────────
    gspread_credentials: str = Field(
        default="", description="Google 서비스 계정 JSON 문자열 (GSPREAD_CREDENTIALS)"
    )

    # ── 피드백 DB ─────────────────────────────────────────────
    feedback_db_path: str = Field(default="./feedback.db", description="SQLite 피드백 DB 경로")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_streamlit_secrets_into_env() -> None:
    """
    .streamlit/secrets.toml이 있으면 그 값을 os.environ에 먼저 주입한다.
    이후 Settings()가 이를 표준 방식(.env와 동일한 우선순위 규칙)으로 읽는다.
    환경변수가 이미 설정되어 있으면(배포 환경) secrets.toml 값으로 덮어쓰지 않는다.
    """
    if not _SECRETS_TOML.exists():
        return
    with _SECRETS_TOML.open("rb") as f:
        data = tomllib.load(f)
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            continue
        os.environ.setdefault(key.upper(), str(value))
