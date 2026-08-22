"""
환경변수를 읽어 .streamlit/secrets.toml을 만든다.

2025년 원본 코드(legacy_2025_code/1215_main.py)는 키를 st.secrets로 읽는다.
대부분은 `os.getenv(...) or st.secrets.get(...)` 형태라 환경변수가 있으면 st.secrets에
닿지도 않지만, 몇 군데는 st.secrets를 먼저 본다:

    153행  DEFAULT_MODEL = (st.secrets.get("openai", {}) or {}).get("model") or os.getenv(...)
    3728행 creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gspread"], ...)
    3759행 ttbkey = st.secrets["aladin"]["ttbkey"]

secrets.toml이 아예 없으면 st.secrets에 접근하는 순간 StreamlitSecretNotFoundError가
나면서 모듈 임포트가 통째로 실패한다. 실제로 HF Space에서 「2025 I2M」 페이지가 이
오류로 열리지 않았고, 같은 모듈을 쓰는 「평가시스템」의 '기존 I2M' 실행도 불가능했다.

원본 코드는 한 글자도 고치지 않는다는 원칙이 있으므로, 코드를 바꾸는 대신 원본이
기대하는 형태의 secrets.toml을 기동 시점에 만들어준다.

값은 출력하지 않는다. 어떤 키를 썼는지와 자릿수만 로그로 남긴다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TARGET = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"

# 원본이 평문으로 읽는 키들
FLAT_KEYS = ["OPENAI_API_KEY", "ALADIN_TTB_KEY", "NLK_CERT_KEY", "KPIPA_API_KEY", "DATA_GO_KR"]


def _toml_escape(value: str) -> str:
    """TOML 기본 문자열 이스케이프. 서비스 계정 private_key의 개행(\\n)이 특히 중요하다."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def build_toml() -> tuple[str, list[str]]:
    lines: list[str] = ["# 자동 생성 — deploy_write_secrets.py. 직접 수정하지 말 것.", ""]
    used: list[str] = []

    for key in FLAT_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value:
            lines.append(f'{key} = "{_toml_escape(value)}"')
            used.append(f"{key}({len(value)}자)")
    lines.append("")

    # [openai] — 원본 153행이 model을 여기서 찾는다. 없으면 gpt-4o-mini로 떨어진다.
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o").strip()
    lines += ["[openai]", f'model = "{_toml_escape(model)}"']
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if api_key:
        lines.append(f'api_key = "{_toml_escape(api_key)}"')
    lines.append("")
    used.append(f"openai.model={model}")

    # [aladin] — 원본 3759행이 ttbkey를 여기서 찾는다.
    ttbkey = (os.environ.get("ALADIN_TTB_KEY") or "").strip()
    if ttbkey:
        lines += ["[aladin]", f'ttbkey = "{_toml_escape(ttbkey)}"', ""]
        used.append("aladin.ttbkey")

    # [gspread] — 원본 3728행이 서비스 계정 dict 전체를 기대한다.
    raw = (os.environ.get("GSPREAD_CREDENTIALS") or "").strip()
    if raw:
        try:
            creds = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[secrets] GSPREAD_CREDENTIALS가 JSON이 아니라 건너뜀: {e}")
        else:
            lines.append("[gspread]")
            for k, v in creds.items():
                lines.append(f'{k} = "{_toml_escape(str(v))}"')
            lines.append("")
            used.append(f"gspread({len(creds)}개 필드)")

    return "\n".join(lines) + "\n", used


def main() -> int:
    content, used = build_toml()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    try:
        TARGET.chmod(0o600)
    except OSError:
        pass  # Windows 등에서는 무시
    print(f"[secrets] {TARGET} 생성 — {', '.join(used) if used else '설정된 키 없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
