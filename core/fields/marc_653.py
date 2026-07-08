"""
653(자유주제어) 필드 생성 모듈 — STUB

원본: 653/backend/app/ai_service.py (1239줄, docs/INTEGRATION_SURVEY.md 653 섹션 참고).
이식 대상: finalize_653(...), generate_653_subfield_line(...), build_marc_653_line(...),
CATEGORY_PROMPTS(18개 분야별 프롬프트), few_shots.json 로딩 로직.

653은 원본에서 async 함수(httpx.AsyncClient, OpenAI Responses API)로 구현되어 있었다.
app.py의 _run_conversion()은 현재 동기 함수이므로, 이 스텁을 실제 로직으로 채울 때
app.py 오케스트레이터를 async def로 전환하고 260/300/041/245 동기 호출부는
asyncio.to_thread(...)로 감싸야 한다(INTEGRATION_PRINCIPLES.md에는 명시되지 않은
추가 이슈 — app.py의 _run_conversion 이식 시 함께 처리할 것).

few_shots.json은 data/few_shots.json 자리로 이식하고, quality_rubric.py(653의
streamlit 품질평가 로직)는 streamlit_app.py 확장 시 함께 반영한다.

적용할 원칙:
  - #2  653 원본은 OpenAI Responses API(client.responses.create, instructions 파라미터)를
        사용했다 — 강제로 chat.completions로 바꾸지 말고 그대로 유지할 것
  - #6  에러는 (tag, error) 튜플로 반환
  - #7  core.debug_log.dbg/dbg_err + "[653]" 프리픽스 사용 (원본은 표준 logging만 사용해
        사서용 판단 근거 추적성이 없었으므로 이식 시 보강 대상)
"""

from __future__ import annotations


async def build_653_field(item: dict, secrets: dict | None = None, openai_client=None) -> tuple[str | None, str | None]:
    """
    653 MRK 문자열을 반환한다.
    (미구현 — 653/backend/app/ai_service.py의 finalize_653 파이프라인 이식 필요)
    """
    raise NotImplementedError(
        "653/backend/app/ai_service.py의 18개 분야 프롬프트·필터링 파이프라인을 이식해야 합니다. "
        "docs/INTEGRATION_SURVEY.md의 653 섹션을 참고하세요."
    )
