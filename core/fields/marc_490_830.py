"""
core/fields/marc_490_830.py
KORMARC 490(총서사항)·830(총서 부출표목-통일표제) 필드 생성 모듈.

원본: 2025년 코드(1215_main.py)의 build_490_830_mrk_from_item(). GPT 호출 없는
순수 규칙 기반 필드다.

원본과 다르게 이식한 부분:
  - 원본은 item["seriesInfo"]가 list로도 올 수 있고 항목마다 별도 volume/vol
    필드가 있다고 가정했다. 실제 알라딘 API를 두 케이스로 직접 호출해 확인한 결과
    seriesInfo는 항상 dict이며(list로 오는 경우 없음), volume/vol 필드는 아예
    존재하지 않는다 — 권차 번호는 이미 seriesName 문자열 끝에 텍스트로 포함되어
    있었다(예: "민음사 세계문학전집 284"). 원본의 list 분기·volume 필드 폴백은
    실제로 한 번도 실행되지 않는 죽은 코드였다.
  - 대신 seriesName 말미의 숫자를 정규식으로 분리해 $v(권차)로 따로 기재하도록
    새로 작성했다(사용자 요청).
"""

from __future__ import annotations

import re

from core.debug_log import dbg

# 총서명 말미의 숫자(권차)를 분리한다. 예: "민음사 세계문학전집 284" → ("민음사 세계문학전집", "284")
_TRAILING_VOL_RE = re.compile(r"^(.*?)\s+(\d+)\s*$")


def build_490_830(item: dict) -> tuple[str, str]:
    """
    490/830 MRK 문자열 튜플을 반환한다. 총서 정보가 없으면 ("", "")를 반환한다.

    item["seriesInfo"]["seriesName"]만 사용한다(subInfo.seriesInfo에 오는 경우도
    방어적으로 함께 확인). GPT 호출·추가 API 조회 없음 — 041/653과 동일하게
    app.py가 이미 가져온 item을 그대로 재사용한다.
    """
    sub = (item or {}).get("subInfo") or {}
    series_info = (item or {}).get("seriesInfo") or sub.get("seriesInfo") or {}
    if not isinstance(series_info, dict):
        return "", ""

    series_name = (series_info.get("seriesName") or "").strip()
    if not series_name:
        return "", ""

    m = _TRAILING_VOL_RE.match(series_name)
    if m and m.group(1).strip():
        series_title, vol = m.group(1).strip(), m.group(2)
        dbg(f"[490/830] 총서명='{series_name}' → 총서명='{series_title}' 권차='{vol}'")
        tag_490 = f"=490  10$a{series_title} ;$v{vol}"
        tag_830 = f"=830  \\0$a{series_title} ;$v{vol}"
    else:
        dbg(f"[490/830] 총서명='{series_name}' (권차 없음)")
        tag_490 = f"=490  10$a{series_name}"
        tag_830 = f"=830  \\0$a{series_name}"

    return tag_490, tag_830
