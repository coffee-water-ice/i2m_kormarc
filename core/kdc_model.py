"""
core/kdc_model.py
056(KDC 분류기호) 예측용 로컬 딥러닝 모델 로더 — 필드 모듈이 공유하는 leaf 모듈.

모델은 RobertaForSequenceClassification(RoBERTa-large, 24층) 파인튜닝본으로
KDC 2자리(95개 클래스, 결번 05/09/26/46/97 제외)를 예측한다. 텍스트를 생성하지
않으며 GPT와 무관하다.

모델 파일(약 1.3GB)은 저장소에 포함되지 않는다(GitHub 파일당 100MB 제한).
KDC_MODEL_DIR 환경변수로 위치를 주입하며, 두 가지 형태를 모두 받는다.

  1. 로컬 폴더 경로 — 예: C:\\...\\kdc_model8_large_swa
  2. HuggingFace Hub 저장소 ID — 예: coffee-water-ice/kdc-model8

Hub 저장소가 비공개면 HF_TOKEN 환경변수가 필요하다. transformers가 알아서
내려받아 캐시하므로(HF_HOME으로 캐시 위치 조정), 두 경우 모두 아래 로드 코드는
같다 — from_pretrained()가 경로와 저장소 ID를 모두 수용한다.

미설정이거나 위치를 찾을 수 없으면 이 모듈은 조용히 비활성화되고 056 생성만
건너뛴다(다른 필드는 영향받지 않는다, INTEGRATION_PRINCIPLES.md #3의
"의존성 없으면 폴백" 방식과 동일).

torch/transformers도 선택적 의존성이다 — 설치되어 있지 않으면 역시 비활성화된다.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from core.debug_log import dbg, dbg_err

# 모델 로드는 수 초가 걸리고 메모리를 1.3GB 이상 쓰므로 프로세스당 한 번만 한다.
_LOCK = threading.Lock()
_STATE: dict = {"loaded": False, "tok": None, "model": None, "id2label": None, "reason": ""}

# 학습 설정과 반드시 일치해야 하는 값이라 모델마다 다르다 — 상수로 박지 않고 설정에서 읽는다.
#   model8   (prepare_data_v8.py)          : 384
#   model11+ (prepare_data_v11_longctx.py) : 512
# 어긋나면 학습 때 존재하지 않던 길이의 입력이 들어가 분포가 달라진다.
DEFAULT_MAX_LENGTH = 384


def max_length() -> int:
    """모델 입력 최대 토큰 수. KDC_MAX_LEN 미설정 시 model8 기준값."""
    raw = (os.environ.get("KDC_MAX_LEN") or "").strip()
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_MAX_LENGTH
    except ValueError:
        return DEFAULT_MAX_LENGTH


# HuggingFace Hub 저장소 ID 형태: "소유자/모델명". 소유자·모델명에는 영문·숫자와
# . _ - 만 쓸 수 있고 슬래시는 정확히 하나다. 로컬 경로(드라이브 문자, 역슬래시,
# 연속 슬래시)와 확실히 구분하기 위해 이 형태에만 해당할 때 Hub로 판단한다.
_HUB_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def model_source() -> tuple[str, str] | None:
    """
    모델 위치를 (종류, 값)으로 돌려준다. 종류는 "local" 또는 "hub".
    미설정이거나 로컬 경로가 존재하지 않으면 None.
    """
    raw = (os.environ.get("KDC_MODEL_DIR") or "").strip().strip('"')
    if not raw:
        return None
    if _HUB_REPO_RE.match(raw):
        return "hub", raw
    p = Path(raw)
    return ("local", str(p)) if p.is_dir() else None


def model_dir() -> Path | None:
    """로컬 폴더로 지정된 경우의 경로. Hub 저장소면 None."""
    src = model_source()
    if src and src[0] == "local":
        return Path(src[1])
    return None


def availability() -> tuple[bool, str]:
    """
    (사용 가능 여부, 사유) — UI 상태 표시용. 모델을 로드하거나 내려받지는 않는다.

    Hub 저장소는 실제 접근 가능 여부를 여기서 확인하지 않는다 — 네트워크 호출이
    필요해 화면 렌더링이 느려지기 때문이다. 접근 실패는 첫 추론 시점에 드러나며
    load_error()로 확인할 수 있다.
    """
    src = model_source()
    if src is None:
        raw = (os.environ.get("KDC_MODEL_DIR") or "").strip()
        if not raw:
            return False, "KDC_MODEL_DIR 미설정"
        return False, f"경로 없음: {raw}"

    kind, value = src
    if kind == "local" and not (Path(value) / "config.json").is_file():
        return False, f"config.json 없음: {value}"

    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as e:
        return False, f"의존성 미설치({e.name}) — pip install torch transformers"

    return True, value if kind == "local" else f"HF Hub: {value}"


def _load() -> bool:
    """모델을 한 번만 로드한다. 실패 사유는 _STATE['reason']에 남긴다."""
    if _STATE["loaded"]:
        return _STATE["model"] is not None

    with _LOCK:
        if _STATE["loaded"]:
            return _STATE["model"] is not None
        _STATE["loaded"] = True

        ok, reason = availability()
        if not ok:
            _STATE["reason"] = reason
            dbg("[056] 모델 비활성:", reason)
            return False

        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # from_pretrained()는 로컬 경로와 Hub 저장소 ID를 모두 받는다.
            # Hub인 경우 첫 호출에서 내려받아 캐시하므로 수 분이 걸릴 수 있다.
            kind, location = model_source()
            if kind == "hub":
                dbg("[056] HF Hub에서 모델 확보 중:", location, "(최초 1회 다운로드)")

            tok = AutoTokenizer.from_pretrained(location)
            model = AutoModelForSequenceClassification.from_pretrained(location)
            model.eval()
            torch.set_grad_enabled(False)

            _STATE["tok"] = tok
            _STATE["model"] = model
            _STATE["id2label"] = model.config.id2label
            dbg("[056] 모델 로드 완료:", location, f"({model.config.num_labels}개 클래스)")
            return True
        except Exception as e:
            _STATE["reason"] = f"로드 실패: {e}"
            dbg_err("[056] 모델 로드 실패:", e)
            return False


def load_error() -> str:
    """마지막 로드 실패 사유(성공했으면 빈 문자열)."""
    return _STATE.get("reason", "")


def truncate_by_tokens(text: str, budget: int) -> str:
    """
    문자가 아니라 토큰 개수 기준으로 자른다.

    학습 전처리(prepare_data_v8.truncate_by_tokens)와 동일한 방식이어야 하므로
    같은 토크나이저로 encode → 자르기 → decode 한다. 모델을 못 쓰는 상황이면
    원문을 그대로 돌려준다(이 경우 어차피 추론도 건너뛴다).
    """
    if not (text or "").strip() or budget <= 0:
        return ""
    if not _load():
        return text
    tok = _STATE["tok"]
    ids = tok(text, add_special_tokens=False, truncation=True, max_length=budget)["input_ids"]
    return tok.decode(ids, skip_special_tokens=True)


def predict_topk(text: str, k: int = 3) -> list[tuple[str, float]]:
    """
    입력 텍스트에 대해 KDC 2자리 상위 k개를 [(label, prob), ...]로 반환한다.
    모델을 쓸 수 없거나 입력이 비면 빈 리스트를 반환한다(예외를 올리지 않는다).
    """
    if not (text or "").strip():
        return []
    if not _load():
        return []

    try:
        import torch

        tok = _STATE["tok"]
        model = _STATE["model"]
        id2label = _STATE["id2label"]

        enc = tok(text, truncation=True, max_length=max_length(), return_tensors="pt")
        with torch.no_grad():
            logits = model(**enc).logits
        probs = torch.softmax(logits, dim=-1)[0]
        k = max(1, min(k, probs.numel()))
        top = torch.topk(probs, k)
        return [
            (str(id2label[idx]), float(score))
            for score, idx in zip(top.values.tolist(), top.indices.tolist())
        ]
    except Exception as e:
        dbg_err("[056] 추론 실패:", e)
        return []
