#!/usr/bin/env bash
# HF Space 컨테이너 기동 스크립트 — 백엔드와 프론트를 한 컨테이너에서 함께 띄운다.
set -euo pipefail

# 백엔드는 컨테이너 내부에서만 쓰므로 127.0.0.1에만 바인딩한다.
uvicorn app:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# 프론트가 먼저 떠서 "백엔드 연결 실패"를 표시하는 일이 없도록 잠깐 기다린다.
# 백엔드가 죽으면 여기서 바로 알 수 있게 종료 여부도 함께 본다.
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "[start] 백엔드 준비 완료"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[start] 백엔드가 기동 중 종료됨" >&2
    exit 1
  fi
  sleep 1
done

# 백엔드가 죽으면 컨테이너도 함께 내려가도록 한다. 그대로 두면 프론트만 살아남아
# 모든 변환이 실패하는 상태로 서비스된다.
#
# 서브셸 안에서 wait는 쓸 수 없다 — wait는 자기 자식만 기다릴 수 있는데
# uvicorn은 부모 셸의 자식이라 "pid N is not a child of this shell"로 실패한다
# (첫 배포 로그에서 실제로 확인). kill -0 폴링은 그 제약을 받지 않는다.
(
  while kill -0 "$BACKEND_PID" 2>/dev/null; do
    sleep 5
  done
  echo "[start] 백엔드 종료 — 컨테이너를 내린다" >&2
  kill -TERM 1
) &

# Space는 7860 포트를 외부에 노출한다.
exec streamlit run streamlit_app.py \
  --server.port 7860 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
