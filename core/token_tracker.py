"""
core/token_tracker.py
한 번의 변환(ISBN 1건)에서 사용한 OpenAI 토큰 사용량을 누적하는 공용 카운터.

core/debug_log.py와 동일한 패턴(모듈 전역 상태, app.py가 변환 시작/종료 시점에
clear/get 호출)을 그대로 따른다. 041/245/300/653 각 필드 모듈이 GPT를 호출한
직후 add()를 호출해 누적하고, app.py가 변환 1건이 끝난 뒤 get_total()로
합계를 meta에 담는다.
"""

from __future__ import annotations

_prompt_tokens = 0
_completion_tokens = 0


def add(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    global _prompt_tokens, _completion_tokens
    _prompt_tokens += max(0, prompt_tokens or 0)
    _completion_tokens += max(0, completion_tokens or 0)


def get_total() -> dict[str, int]:
    return {
        "prompt_tokens": _prompt_tokens,
        "completion_tokens": _completion_tokens,
        "total_tokens": _prompt_tokens + _completion_tokens,
    }


def clear() -> None:
    global _prompt_tokens, _completion_tokens
    _prompt_tokens = 0
    _completion_tokens = 0
