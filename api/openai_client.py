"""
api/openai_client.py
OpenAI 클라이언트 생성 — 얇은 팩토리 함수만 제공한다.

통합 원칙(INTEGRATION_PRINCIPLES.md #2, #3):
  - 클라이언트 "생성"만 여기서 공통화한다. chat.completions vs responses 같은
    호출 스타일은 강제로 통일하지 않고 각 필드 모듈(marc_041/245/300/653)이
    041 방식(함수 인자로 주입받기)을 따라 자유롭게 선택한다.
  - app.py가 시작 시 build_openai_client() 로 클라이언트 1개를 만들어
    모든 필드 모듈에 넘기면 된다 — 각 모듈이 os.environ이나 get_settings()를
    직접 호출하지 않아 테스트 시 monkeypatch 없이도 목 클라이언트를 주입할 수 있다.
"""

from __future__ import annotations

import openai

from core.config import Settings


def build_openai_client(settings: Settings) -> openai.OpenAI:
    return openai.OpenAI(api_key=settings.openai_api_key)
