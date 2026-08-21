"""
로컬 API 키 파일(i2m_kormarc_2026_api_keys.env)의 값을 HF Space에 반영한다.

Space 설정 화면에서 키를 하나씩 옮겨 넣는 것은 오타가 나기 쉽고, 로컬과 배포의
값이 언제 어긋났는지 알기 어렵다. 이 스크립트는 로컬 파일을 기준으로 Space를
맞춰준다.

사용법:
    python deploy_sync_secrets.py            # 무엇이 바뀔지만 보여준다(기본)
    python deploy_sync_secrets.py --apply    # 실제로 반영한다

주의:
  - 값은 절대 출력하지 않는다. 이름과 자릿수만 표시한다.
  - 로컬에서 비어 있는 항목은 건드리지 않는다. Space에만 등록해 둔 키를 실수로
    지우지 않기 위함이다. 지우려면 Space 설정 화면에서 직접 삭제할 것.
  - HF 인증이 필요하다: `hf auth login` 또는 HF_TOKEN 환경변수.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SPACE_ID = "I2M/i2m-kormarc"
ENV_FILE = Path(__file__).resolve().parent.parent / "i2m_kormarc_2026_api_keys.env"

# 민감한 값 — Space "Secret"으로 등록(값 조회 불가)
SECRET_KEYS = [
    "ALADIN_TTB_KEY", "ALADIN_TTB_KEY2", "ALADIN_TTB_KEY3",
    "OPENAI_API_KEY", "KPIPA_API_KEY", "DATA_GO_KR", "NLK_CERT_KEY",
    "GSPREAD_CREDENTIALS", "APP_PASSWORD",
]

# 민감하지 않은 설정 — Space "Variable"로 등록(설정 화면에서 값이 보인다)
VARIABLE_KEYS = [
    "KDC_MODEL_DIR", "KDC_MODEL_VERSION", "KDC_EDITION", "KDC_MAX_LEN",
    "KDC_KEYWORD_TOKEN_BUDGET", "KDC_TOC_TOKEN_BUDGET", "KDC_DESC_TOKEN_BUDGET",
]


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        print(f"키 파일이 없습니다: {path}", file=sys.stderr)
        raise SystemExit(1)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def main() -> int:
    ap = argparse.ArgumentParser(description="로컬 키 파일을 HF Space에 반영")
    ap.add_argument("--apply", action="store_true", help="실제로 반영(기본은 미리보기)")
    ap.add_argument("--space", default=SPACE_ID)
    args = ap.parse_args()

    values = read_env(ENV_FILE)

    from huggingface_hub import HfApi
    api = HfApi()
    # 인증 실패와 네트워크 오류를 구분한다. 예전에는 모든 예외를 "인증 필요"로
    # 안내해서, 일시적인 연결 끊김(ConnectError)에도 `hf auth login`을 다시 하게
    # 만들었다. 원인이 다르면 대응도 다르다.
    try:
        who = api.whoami()
    except Exception as e:
        name = type(e).__name__
        if "Connect" in name or "Timeout" in name or "Network" in name:
            print(f"HF 서버 연결 실패({name}). 네트워크 문제일 수 있으니 잠시 후 다시 실행하세요.",
                  file=sys.stderr)
        else:
            print(f"HF 인증이 필요합니다. `hf auth login`을 먼저 실행하세요. ({name})", file=sys.stderr)
        return 1
    print(f"계정: {who.get('name')} → Space: {args.space}")
    print("모드:", "반영" if args.apply else "미리보기 (--apply 를 붙이면 실제 반영)")

    print("\n── Secrets ──")
    for key in SECRET_KEYS:
        value = values.get(key, "")
        if not value:
            print(f"  건너뜀  {key:26s} (로컬에 값 없음)")
            continue
        if args.apply:
            api.add_space_secret(args.space, key=key, value=value)
        print(f"  {'등록' if args.apply else '등록 예정'}    {key:26s} ({len(value)}자)")

    print("\n── Variables ──")
    for key in VARIABLE_KEYS:
        value = values.get(key, "")
        if not value:
            print(f"  건너뜀  {key}")
            continue
        # 모델 위치는 로컬 경로가 아니라 Hub 저장소 ID여야 한다. 로컬 경로를 그대로
        # 올리면 Space에서 "경로 없음"이 되어 056만 조용히 빠진다.
        if key == "KDC_MODEL_DIR" and not (value.count("/") == 1 and "\\" not in value and ":" not in value):
            print(f"  건너뜀  {key} — 로컬 경로라 Space에 맞지 않음 (현재 값 유지)")
            continue
        if args.apply:
            api.add_space_variable(args.space, key=key, value=value)
        print(f"  {'등록' if args.apply else '등록 예정'}    {key:26s} = {value}")

    if not args.apply:
        print("\n실제로 반영하려면: python deploy_sync_secrets.py --apply")
    else:
        print("\n반영 완료. Space가 자동으로 재시작됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
