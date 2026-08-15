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

COPY --chown=user . .

# 피드백 DB는 컨테이너 재시작 시 사라진다(Space 파일시스템은 영속이 아니다).
# 영속 저장이 필요해지면 Space Persistent Storage나 외부 DB로 옮길 것.
ENV FEEDBACK_DB_PATH=/tmp/feedback.db

EXPOSE 7860

CMD ["bash", "start.sh"]
