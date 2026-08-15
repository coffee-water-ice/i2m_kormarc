"""
Docker 이미지 빌드 중에 056 모델을 내려받아 이미지에 포함시킨다.

실행 시점에 받게 두면 컨테이너가 슬립에서 깨어날 때마다 1.28GB를 다시 받아
첫 요청이 수 분 걸린다(빈 캐시 실측 188초). 빌드 때 한 번 받아두면 깨어난 뒤
로컬 캐시에서 로드만 하면 된다(실측 로드 0.8초).

이 파일은 배포에만 쓰인다 — 앱 실행 경로에서는 import되지 않는다.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    repo = (os.environ.get("KDC_MODEL_DIR") or "").strip()
    if not repo:
        print("KDC_MODEL_DIR 미설정 — 모델을 이미지에 넣지 않고 넘어간다", flush=True)
        return 0

    # 로컬 경로 형태면 빌드 단계에서 받을 것이 없다(개발자가 직접 마운트한 경우).
    if "/" not in repo or repo[1:2] == ":" or repo.count("/") > 1:
        print(f"'{repo}'는 Hub 저장소 ID가 아니다 — 건너뛴다", flush=True)
        return 0

    token = (os.environ.get("HF_TOKEN") or "").strip() or None
    if not token:
        print("경고: HF_TOKEN이 없다. 비공개 저장소면 실패한다.", flush=True)

    from huggingface_hub import snapshot_download

    try:
        path = snapshot_download(repo, token=token)
    except Exception as e:
        print(f"모델 다운로드 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        # 빌드를 중단시킨다. 조용히 넘어가면 배포 후 첫 요청에서야 문제가 드러난다.
        return 1

    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    print(f"모델 이미지 포함 완료: {repo} ({total / 1024 / 1024:.0f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
