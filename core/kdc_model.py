"""
core/kdc_model.py
056(KDC 분류기호) 예측용 로컬 딥러닝 모델 로더 — 필드 모듈이 공유하는 leaf 모듈.

모델은 RobertaForSequenceClassification(RoBERTa-large, 24층) 파인튜닝본으로
KDC 2자리(95개 클래스, 결번 05/09/26/46/97 제외)를 예측한다. 텍스트를 생성하지
않으며 GPT와 무관하다.

모델 파일(약 1.3GB)은 저장소에 포함되지 않는다. 로컬 경로를 KDC_MODEL_DIR
환경변수로 주입하며, 미설정이거나 경로가 없으면 이 모듈은 조용히 비활성화되고
056 생성만 건너뛴다(다른 필드는 영향받지 않는다, INTEGRATION_PRINCIPLES.md #3의
"의존성 없으면 폴백" 방식과 동일).

torch/transformers도 선택적 의존성이다 — 설치되어 있지 않으면 역시 비활성화된다.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from core.debug_log import dbg, dbg_err

# 모델 로드는 수 초가 걸리고 메모리를 1.3GB 이상 쓰므로 프로세스당 한 번만 한다.
_LOCK = threading.Lock()
_STATE: dict = {"loaded": False, "tok": None, "model": None, "id2label": None, "reason": ""}

# 학습 설정과 반드시 일치해야 한다 — model8은 train_runpod_v8.py에서 MAX_LEN=384로 학습됐다
# (학습보고서_model8.pdf 3절). 512로 두면 학습 때 잘린 적 없는 위치까지 입력이 들어가 분포가 달라진다.
MAX_LENGTH = 384


def model_dir() -> Path | None:
    """KDC_MODEL_DIR이 가리키는 모델 디렉터리. 미설정/부재면 None."""
    raw = (os.environ.get("KDC_MODEL_DIR") or "").strip().strip('"')
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def availability() -> tuple[bool, str]:
    """
    (사용 가능 여부, 사유) — UI 상태 표시용. 모델을 로드하지는 않는다.
    """
    p = model_dir()
    if p is None:
        raw = (os.environ.get("KDC_MODEL_DIR") or "").strip()
        if not raw:
            return False, "KDC_MODEL_DIR 미설정"
        return False, f"경로 없음: {raw}"
    if not (p / "config.json").is_file():
        return False, f"config.json 없음: {p}"
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as e:
        return False, f"의존성 미설치({e.name}) — pip install torch transformers"
    return True, str(p)


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

            path = str(model_dir())
            tok = AutoTokenizer.from_pretrained(path)
            model = AutoModelForSequenceClassification.from_pretrained(path)
            model.eval()
            torch.set_grad_enabled(False)

            _STATE["tok"] = tok
            _STATE["model"] = model
            _STATE["id2label"] = model.config.id2label
            dbg("[056] 모델 로드 완료:", path, f"({model.config.num_labels}개 클래스)")
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

        enc = tok(text, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
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
