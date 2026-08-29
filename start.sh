#!/usr/bin/env bash
# HF Space 컨테이너 기동 스크립트 — 백엔드·스트림릿·React를 한 컨테이너에서
# 함께 띄운다. 공개 포트(7860)는 nginx가 받고, uvicorn·streamlit은 내부 전용
# 포트로 물러난다(nginx.conf 참고).
set -euo pipefail

# 2025년 원본 코드가 st.secrets로 읽는 키들을 secrets.toml로 만들어 둔다.
# secrets.toml이 없으면 st.secrets 접근 순간 StreamlitSecretNotFoundError가 나면서
# 「2025 I2M」 페이지와 「평가시스템」의 '기존 I2M' 실행이 통째로 실패한다.
# 원본 코드는 고치지 않는다는 원칙이라 환경 쪽을 맞춰준다.
python deploy_write_secrets.py

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

# 스트림릿도 이제 내부 전용(7861)이다 — 공개 포트(7860)는 nginx가 받아서
# /app(React)·/api(FastAPI)·나머지(이 스트림릿)로 나눠준다(nginx.conf 참고).
# 백그라운드로 띄우는 이유: 이 스크립트의 마지막 프로세스(=공개 포트를 실제로
# 붙잡는 프로세스)는 nginx여야 하기 때문이다.
streamlit run streamlit_app.py \
  --server.port 7861 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false &
STREAMLIT_PID=$!

# 백엔드나 스트림릿 둘 중 하나라도 죽으면 컨테이너를 내린다. 그대로 두면
# nginx만 살아서 절반 죽은 상태(예: 스트림릿만 죽어도 /api는 계속 응답)로
# 서비스되거나, 반대로 nginx가 계속 502를 돌려주는 상태가 된다.
#
# 서브셸 안에서 wait는 쓸 수 없다 — wait는 자기 자식만 기다릴 수 있는데
# uvicorn/streamlit은 부모 셸의 자식이라 "pid N is not a child of this shell"로
# 실패한다(첫 배포 로그에서 실제로 확인). kill -0 폴링은 그 제약을 받지 않는다.
(
  while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$STREAMLIT_PID" 2>/dev/null; do
    sleep 5
  done
  echo "[start] 백엔드 또는 스트림릿 종료 — 컨테이너를 내린다" >&2
  kill -TERM 1
) &

# nginx가 쓸 임시 디렉터리(nginx.conf의 *_temp_path) — 보통 nginx가 알아서
# 만들지만, 혹시 몰라 미리 만들어둔다(/tmp라 권한 문제 없음).
mkdir -p /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi

# /app(React)·/api(FastAPI)를 auth_gate.py와 같은 APP_PASSWORD로 잠근다 —
# 그 게이트는 스트림릿 페이지 코드 안에서만 동작해서 nginx가 새로 여는 이
# 경로들은 원래 보호를 못 받는다(nginx.conf 참고). APP_PASSWORD가 비어있으면
# auth_gate.py 자신도 잠금을 비활성화하므로(로컬 개발 편의) 여기도 그에 맞춘다.
if [ -n "${APP_PASSWORD:-}" ]; then
  htpasswd -bc /tmp/nginx-htpasswd i2m "$APP_PASSWORD"
  cat > /tmp/nginx-auth.conf <<'EOF'
auth_basic "I2M KORMARC";
auth_basic_user_file /tmp/nginx-htpasswd;
EOF
  echo "[start] /app, /api Basic Auth 활성화"
else
  : > /tmp/nginx-auth.conf
  echo "[start] APP_PASSWORD 미설정 — /app, /api 잠금 비활성(로컬 개발 가정)" >&2
fi

# Space는 7860 포트를 외부에 노출한다 — nginx가 그 창구다.
exec nginx -c "$(pwd)/nginx.conf" -g 'daemon off;'
