"""
core/debug_log.py
필드 생성 과정의 판단 근거를 누적하는 공용 디버그 로거.

원본: 260+300/core/field_rules.py 상단의 _dbg()/_dbg_err() (모듈 전역이라 260/300 전용이었음).
통합 원칙(INTEGRATION_PRINCIPLES.md #7)에 따라 모든 필드 모듈(041/245/260/300/653)이
이 모듈 하나를 공유해서 meta["debug_lines"]로 한 번에 노출한다.
호출하는 쪽에서 메시지 앞에 "[260]", "[041]" 같은 필드 프리픽스를 직접 붙인다.
"""

from __future__ import annotations

_debug_lines: list[str] = []


def dbg(*args) -> None:
    msg = " ".join(str(a) for a in args)
    _debug_lines.append(msg)


def dbg_err(*args) -> None:
    msg = " ".join(str(a) for a in args)
    _debug_lines.append(f"ERROR: {msg}")


def get_debug_lines() -> list[str]:
    return list(_debug_lines)


def clear_debug_lines() -> None:
    _debug_lines.clear()
