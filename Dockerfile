# HuggingFace Space(Docker SDK)용 이미지.
#
# 이 앱은 FastAPI 백엔드와 Streamlit 프론트 두 프로세스로 되어 있는데, Space는
# 컨테이너 하나만 띄운다. 그래서 한 컨테이너 안에서 uvicorn(내부 8000)과
# streamlit(공개 7860)을 함께 돌린다. api_client.py가 백엔드 주소를 못 찾으면
# localhost:8000으로 폴백하므로 애플리케이션 코드는 손대지 않는다.
#
# 056 모델(1.28GB)은 이미지에 넣지 않는다. 실행 시 HF Hub 비공개 저장소에서
# 받아 캐시한다 — KDC_MODEL_DIR과 HF_TOKEN을 Space Secrets로 주입할 것.

FROM python:3.11-slim

# git: huggingface_hub이 일부 경로에서 사용. curl: 헬스체크용.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Space는 UID 1000으로 실행된다. root로 만든 파일에는 쓸 수 없으므로
# 사용자를 먼저 만들고 이후 작업을 그 사용자로 수행한다.
RUN useradd -m -u 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 모델 캐시 위치. HF_HOME이 아니라 HF_HUB_CACHE를 쓴다 — HF_HOME을 바꾸면
# 토큰 캐시까지 함께 옮겨가 비공개 저장소 인증이 끊긴다(실측으로 확인).
ENV HF_HUB_CACHE=/home/user/.cache/huggingface/hub

WORKDIR /home/user/app

# 의존성을 먼저 설치해 레이어 캐시를 살린다. torch는 CPU 휠로 받는다 —
# 기본 인덱스의 CUDA 빌드는 수 GB라 Space 이미지 한도를 넘긴다.
COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt \
    && pip install --no-cache-dir --user \
        --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir --user transformers

# ── 056 모델을 이미지에 포함시킨다 ────────────────────────────────
#
# 실행 시점에 받게 두면 컨테이너가 슬립에서 깨어날 때마다 1.28GB를 다시 내려받아
# 첫 요청이 2~3분 걸린다(빈 캐시 기준 실측 188초). 빌드 때 한 번 받아 이미지에
# 넣어두면 깨어난 뒤 로컬 디스크에서 로드만 하면 되고, 실측으로 로드 0.8초 +
# 첫 추론 약 1초다.
#
# 대가는 이미지가 약 1.3GB 커지고 모델 교체 시 재빌드가 필요하다는 것이다.
# 모델 갱신은 몇 달에 한 번이지만 슬립 복귀는 매일 일어나므로 이쪽이 이득이다.
#
# 저장소가 비공개라 빌드에도 토큰이 필요하다. Space 설정에서 HF_TOKEN을
# "Secret"으로 등록하면 아래 --mount=type=secret 으로 읽을 수 있다. ENV로 받지
# 않는 이유는 ENV 값이 이미지 레이어에 그대로 남기 때문이다.
ARG KDC_MODEL_REPO=I2Muser/kdc-model12
ENV KDC_MODEL_DIR=${KDC_MODEL_REPO}

# 다운로드 로직은 별도 파일에 둔다. Dockerfile 안에 긴 python -c를 역슬래시로
# 이어붙이면 따옴표·개행 처리에서 실수하기 쉽고, 그 실패가 빌드 단계에서야 드러난다.
COPY --chown=user deploy_fetch_model.py ./
RUN --mount=type=secret,id=HF_TOKEN,mode=0444 \
    HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" \
    python deploy_fetch_model.py

# 런타임에도 HF_TOKEN이 필요하다 — 캐시가 있어도 비공개 저장소는 최신 리비전을
# 확인하는 요청을 한 번 보내기 때문이다(확인만 하고 파일은 캐시에서 쓰므로 빠르다).
# Space 설정에서 HF_TOKEN을 Secret으로 등록하면 환경변수로 주입된다.
#
# 참고: 모델을 다른 저장소로 바꾸려면 Space Secret의 KDC_MODEL_DIR만 바꾸면 되지만,
# 그 경우 이미지에 없는 모델이라 첫 기동에서 새로 내려받는다. 상시 쓸 모델이라면
# 위 ARG KDC_MODEL_REPO를 바꿔 재빌드하는 편이 낫다.

COPY --chown=user . .

# 피드백 DB는 컨테이너 재시작 시 사라진다(Space 파일시스템은 영속이 아니다).
# 영속 저장이 필요해지면 Space Persistent Storage나 외부 DB로 옮길 것.
ENV FEEDBACK_DB_PATH=/tmp/feedback.db

EXPOSE 7860

CMD ["bash", "start.sh"]
