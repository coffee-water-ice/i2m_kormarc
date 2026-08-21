"""
core/llm_health.py
OpenAI API를 "실제로 호출할 수 있는지" 확인한다.

키가 설정되어 있는지(bool)만 보는 기존 점검으로는 잡히지 않는 실패가 있다.
실제로 겪은 사례: 선불 크레딧이 0원이 된 키. 인증은 통과하므로 화면에는 ✅로
표시되지만 모든 GPT 호출이 429(insufficient_quota)로 실패했고, 653이 조용히
빈 값으로 생성되어 평가 데이터가 오염될 뻔했다.

  GET  /v1/models           → 200  (키가 유효하기만 하면 통과 — 크레딧을 보지 않는다)
  POST /v1/chat/completions → 429  credit_balance_exhausted

따라서 점검은 반드시 **실제 생성 호출**이어야 한다. 비용을 최소화하기 위해
max_tokens=1로 한 토큰만 요청하고, 결과를 일정 시간 캐시한다.

이 모듈은 "호출이 가능한가"만 답한다. 개별 필드의 GPT 실패는 각 필드 모듈이
자체 로그로 남기며, 변환 1건 단위의 실패 여부는 token_tracker의 합계가
0인지로 판별한다(app.py의 gpt_called).
"""

from __future__ import annotations

import time

# (검사한 키의 지문, 결과) — 키가 바뀌면 캐시를 무시하고 다시 검사한다.
_cache: dict | None = None
_CACHE_TTL_SEC = 600  # 10분. 크레딧 소진은 실행 중에도 일어날 수 있어 길게 두지 않는다.

# 점검 전용 모델. 실제 사용 모델(gpt-4o 등)과 달라도 크레딧·조직 상태는 동일하게
# 걸리므로, 가장 싼 모델로 확인한다.
_PROBE_MODEL = "gpt-4o-mini"


def _fingerprint(api_key: str) -> str:
    """키 값을 저장하지 않고 동일성만 비교하기 위한 지문."""
    return f"{len(api_key)}:{api_key[-6:]}" if api_key else ""


def check_openai(api_key: str, *, force: bool = False) -> dict:
    """
    OpenAI 실호출 가능 여부를 확인한다.

    Returns:
        {
            "ok": bool,
            "code": str,     # "" | "no_key" | "credit_balance_exhausted" | "invalid_api_key" | ...
            "detail": str,   # 사람이 읽을 한 줄 설명
            "checked_at": float,
        }
    """
    global _cache

    if not api_key:
        return {"ok": False, "code": "no_key", "detail": "OpenAI 키가 설정되지 않았습니다.",
                "checked_at": time.time()}

    fp = _fingerprint(api_key)
    if (
        not force
        and _cache is not None
        and _cache.get("fingerprint") == fp
        and time.time() - _cache["result"]["checked_at"] < _CACHE_TTL_SEC
    ):
        return _cache["result"]

    result = _probe(api_key)
    _cache = {"fingerprint": fp, "result": result}
    return result


def _probe(api_key: str) -> dict:
    now = time.time()
    try:
        import openai

        client = openai.OpenAI(api_key=api_key, timeout=20.0, max_retries=0)
        client.chat.completions.create(
            model=_PROBE_MODEL,
            messages=[{"role": "user", "content": "1"}],
            max_tokens=1,
        )
        return {"ok": True, "code": "", "detail": "OpenAI 호출 정상", "checked_at": now}

    except Exception as e:
        code = getattr(e, "code", "") or ""
        status = getattr(e, "status_code", None)
        # openai SDK 예외는 code를 문자열로 담아준다. 잡히지 않으면 메시지에서 찾는다.
        message = str(e)
        if not code:
            for known in ("credit_balance_exhausted", "insufficient_quota",
                          "invalid_api_key", "rate_limit_exceeded", "model_not_found"):
                if known in message:
                    code = known
                    break

        detail = {
            "credit_balance_exhausted": "OpenAI 크레딧이 모두 소진되었습니다. 결제 후 사용 가능합니다.",
            "insufficient_quota": "OpenAI 사용 한도를 초과했습니다(크레딧 부족).",
            "invalid_api_key": "OpenAI 키가 유효하지 않습니다.",
            "rate_limit_exceeded": "OpenAI 호출 속도 제한에 걸렸습니다. 잠시 후 다시 시도하세요.",
            "model_not_found": f"점검용 모델({_PROBE_MODEL})을 사용할 수 없는 키입니다.",
        }.get(code)

        if not detail:
            detail = f"OpenAI 호출 실패({status or '?'}): {message[:160]}"

        return {"ok": False, "code": code or "error", "detail": detail, "checked_at": now}


def clear_cache() -> None:
    global _cache
    _cache = None
