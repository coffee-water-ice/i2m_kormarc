# i2m_kormarc — KORMARC 통합 변환 시스템

041/245/653/260+300 4개 폴더 + 2025년 코드(단일 파일 `1215_main.py`)를 하나의
시스템으로 합치는 통합 프로젝트다. 자세한 배경은 상위 폴더의 `통합_계획.md`,
`docs/INTEGRATION_SURVEY.md`, `docs/INTEGRATION_PRINCIPLES.md`를 참고할 것.

## 현재 상태

041/245/653/260+300 4개 폴더 + 2025년 코드 이식이 모두 끝나 전 필드가 실제로 동작한다.

- **041**(언어코드/546) — 041 폴더의 `LangFieldBuilder` 이관 (`core/fields/marc_041.py`)
- **245/246/500/700/710/900/940** — 245 폴더 이관 (`core/fields/marc_245.py`, `marc_500_700_710.py`)
- **260/300**(발행사항/형태사항) — 260+300 폴더 이관 (`core/fields/marc_260.py`, `marc_300.py`)
- **653**(자유주제어) — 653 폴더의 `ai_service.py`(18개 분야별 GPT 프롬프트 + 키워드
  필터링 파이프라인) 이관 (`core/fields/marc_653.py`). 알라딘 상세페이지 크롤링·KPIPA
  ONIX 목차·NLK 부가기호 보강도 함께 이식했으며, KPIPA/NLK 보강은 원본과 동일하게
  기본 비활성(opt-in, `core.config.Settings.kpipa_enable_653`/`nlk_enable_653`)이다.
- **007(형태자료 부호)/008(부호화정보)** — 2025년 코드의 규칙 기반 로직 이관
  (`core/fields/marc_007_008.py`). GPT 미사용. 041의 언어코드·260의 발행국코드를
  재계산 없이 그대로 재사용하고, 삽화/색인/문학형식/전기 여부는 제목+책소개+목차
  텍스트의 키워드 정규식으로 판정한다.
- **020(ISBN)/950(가격)** — 같은 2025년 코드에서 이관(`core/fields/marc_020_950.py`).
  GPT 미사용. NLK Seoji로 부가기호($g)·세트 ISBN·가격을 보강하고, 알라딘 정가가
  없을 때만 상품페이지 크롤링으로 폴백한다.
- **490(총서사항)/830(총서 부출표목)** — 같은 2025년 코드에서 이관
  (`core/fields/marc_490_830.py`). GPT 미사용. 알라딘 `seriesInfo.seriesName`
  말미의 숫자를 권차($v)로 분리해 기재한다(예: "민음사 세계문학전집 284" →
  `$a민음사 세계문학전집 ;$v284`).
- **056(KDC 분류기호)** — 딥러닝팀 분류 모델 연계(`core/fields/marc_056.py`,
  `core/kdc_model.py`). 다른 필드와 달리 GPT도 규칙도 아닌 **로컬 딥러닝 모델**을
  쓴다(klue/roberta-large 파인튜닝, KDC 2자리 95클래스). Top-3 후보와 확률을
  화면에 노출해 사서가 고르는 구조이며, 모델이 예측하는 것은 **강(2자리)까지**라
  세목은 사서가 채운다. 653 키워드가 모델 입력에 포함되므로 **653 이후에 실행**된다.
  모델 파일(1.3GB)은 저장소에 없다 — 아래 "056 모델 설정" 참고.

2025년 코드 이식 3건(007/008, 020/950, 490/830) 모두 원본이 가정했던 일부 분기
(하드코딩 지역 dict, `seriesInfo`가 list로 오는 경우, 별도 volume 필드 등)가 실제
알라딘 API 응답으로는 한 번도 실행되지 않는 죽은 코드임을 직접 호출해 확인하고
제외했다 — 실제로 쓰이는 경로만 이식했다. 950의 서브필드 표기(`$b` 값 앞 스트레이
백슬래시)는 사용자 확인을 거쳐 "원화기호(₩) + 가격"으로 바로잡았다.

부가 기능으로 변환 1건당 소요시간(`meta.elapsed_ms`)과 OpenAI 토큰 사용량
(`meta.token_usage`)을 집계해 Streamlit 화면에 표시한다(`core/token_tracker.py`).

## 설치 및 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

로컬 실행에 필요한 실제 키(알라딘/OpenAI/KPIPA/행안부/NLK/GSPREAD)는 `.env.example`을
참고해 이 저장소 **바깥**(부모 폴더, `i2m_kormarc/`와 같은 위치가 아니라 그 한 단계 위)에
`i2m_2026.env` 파일로 채워 넣는다(`core/config.py`의 `_ENV_FILE` 경로 참고). 저장소 바깥에
두므로 실수로 git에 커밋될 일이 없다. Render/Streamlit Cloud 등 배포 환경은 이 파일 없이
대시보드에 등록된 환경변수/secrets.toml을 그대로 쓴다.

```bash
# 백엔드
uvicorn app:app --reload        # http://127.0.0.1:8000/health

# 프론트엔드 (백엔드가 먼저 떠 있어야 함)
streamlit run streamlit_app.py  # http://localhost:8501
```

### 056 모델 설정 (선택)

056은 로컬 딥러닝 모델을 쓰는 유일한 필드다. **설정하지 않아도 나머지 필드는 그대로
동작하고 056만 빠진다** — 배포 환경(Render)은 현재 이 상태로 운영된다.

로컬에서 056까지 쓰려면 두 가지가 필요하다.

```bash
# 1) 추론 의존성 — requirements.txt에 넣지 않았다. 배포 이미지를 가볍게 유지하기 위함
#    (torch CPU 휠만 약 200MB).
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers
```

```ini
# 2) i2m_2026.env 에 모델 폴더 경로
KDC_MODEL_DIR=<딥러닝팀에게 받은 kdc_model8_large_swa 폴더 경로>
KDC_MODEL_VERSION=model8_large_swa
```

모델 폴더에는 `config.json`, `model.safetensors`, `tokenizer.json`, `vocab.txt` 등이
들어 있다. **경로만 바꾸면 model9·model10으로 교체된다** — 코드 수정이 필요 없다
(「056 분류모델 개선 및 I2M 연계 추진안」 4절 "모델 경로와 버전의 설정값 분리").

> **주의**: 모델 교체 시 학습 전처리(`prepare_data_vN.py`의 `build_text()`)가 바뀌었는지
> 확인할 것. 추론 입력이 학습 입력과 다르면 정확도가 떨어진다. `marc_056.py`의
> 구분자·토큰 예산 상수가 그 값을 그대로 복제한 것이다.

Windows에서는 경로 길이 제한(260자) 때문에 깊은 폴더 아래에 가상환경을 만들면
torch 설치가 실패할 수 있다. 그 경우 `C:\Users\<사용자>\venvs\i2m` 처럼 짧은 경로에
가상환경을 만들면 된다.

메모리는 추론 시 약 1.5GB를 쓴다(float32, 337M 파라미터). 이 때문에 현재 배포
환경에는 올리지 않았다.

## 디렉토리 구조

```
i2m_kormarc/
├── app.py                       # FastAPI 오케스트레이터
├── streamlit_app.py             # Streamlit Home(상태 대시보드)
├── pages/
│   └── 1_ISBN_변환.py           # 실제 변환 UI (단건/일괄)
├── api_client.py                # 프론트 → 백엔드 HTTP 클라이언트
├── core/
│   ├── config.py                # pydantic-settings 통합 설정
│   ├── debug_log.py             # 필드 공용 디버그 로거 (meta.debug_lines)
│   ├── token_tracker.py         # 필드 공용 OpenAI 토큰 카운터 (meta.token_usage)
│   ├── marc_builder.py          # pymarc.Record ↔ MRK 변환 (kormarc_tag_to_mrk 어댑터 포함)
│   ├── text_utils.py            # 245 계열 공용 텍스트/이름 유틸 (leaf 모듈, 순환참조 방지)
│   ├── kdc_model.py             # 056 공통 추론 모듈 (모델 로드/추론/토큰 절단, 모델 교체 지점)
│   ├── fields/
│   │   ├── marc_041.py          # 실동작 (041/546, LangFieldBuilder)
│   │   ├── marc_245.py          # 실동작 (245/246/940 + collect_orig_info)
│   │   ├── marc_500_700_710.py  # 실동작 (500/700/710/900)
│   │   ├── marc_260.py          # 실동작
│   │   ├── marc_300.py          # 실동작
│   │   ├── marc_653.py          # 실동작 (653, 18개 분야별 GPT 프롬프트 + 키워드 필터링)
│   │   ├── few_shots_653.json   # 653 GPT 프롬프트용 few-shot 예시 데이터
│   │   ├── marc_007_008.py      # 실동작 (007/008, 규칙 기반, 2025년 코드 이관)
│   │   ├── marc_020_950.py      # 실동작 (020/950, 규칙 기반, 2025년 코드 이관)
│   │   ├── marc_490_830.py      # 실동작 (490/830, 규칙 기반, 2025년 코드 이관)
│   │   └── marc_056.py          # 실동작 (056, 딥러닝 모델 — 모델 경로 설정 시에만)
│   └── name_data/               # 실동작 (245 이름판별 데이터: 한국/일본 성씨, 출생신고 이름 통계)
├── api/
│   ├── aladin_client.py         # 실동작 (OPT_RESULT_FULL)
│   ├── aladin_scraper.py        # 실동작 (상품페이지·저자프로필 크롤링, GPT 원제/원저자 웹 검색,
│   │                             #          653용 getContents.aspx 책소개/목차 크롤링,
│   │                             #          950용 알라딘 정가 크롤링 폴백)
│   ├── nlk_client.py            # 실동작 (245 원서명/원저자명 폴백 + 653 부가기호 content_code
│   │                             #          + 020 부가기호/세트ISBN/가격)
│   ├── kpipa_client.py          # 실동작 (출판사명 조회 + 653 ONIX 목차 추출)
│   ├── mois_client.py           # 실동작
│   ├── publisher_db.py          # 실동작 (build_pub_location_bundle)
│   └── openai_client.py         # 실동작 (클라이언트 팩토리만)
├── database/
│   └── feedback_logger.py       # 실동작 (SQLite, field_tag로 모든 필드 공용)
└── docs/
    ├── INTEGRATION_SURVEY.md
    └── INTEGRATION_PRINCIPLES.md
```

## 향후 개선 아이디어 (필수 아님)

- 653의 KPIPA/NLK 보강(`kpipa_enable_653`/`nlk_enable_653`)은 원본처럼 기본
  비활성 상태다 — 실제로 카테고리 라우팅 정확도가 아쉬운 경우에만 켜서 검증할 것.
- `core/fields/marc_300.py`는 알라딘 상세 페이지 HTTP 요청을 `api/aladin_scraper.py`를
  거치지 않고 직접 수행한다(원본 구조를 그대로 이관한 레이어링 잔재) — 크롤링
  일원화 리팩터링은 별도 작업으로 남겨둔다.
- 008의 삽화 부호(18-21) 판정 정규식에 "표" 한 글자가 단독으로 들어 있어("도표|표|
  차트|그래프") "대표작"·"발표" 같은 흔한 단어에도 오탐할 수 있다(2025년 코드 원본의
  기존 결함, 그대로 이식함) — 필요하면 별도로 수정할 것.

## 056 관련 남은 과제

- **모델 교체**: 현재 붙어 있는 model8은 세 라운드 중 성능이 가장 낮다
  (model8 Acc 0.8309 / Macro-F1 0.7414, model9 SWA 0.8421 / 0.7649,
  model10 plain 0.8343 / **0.7713**). 딥러닝팀에서 모델 폴더를 받아 `KDC_MODEL_DIR`만
  바꾸면 된다. 전체 정답률이 중요하면 model9, 희귀 분야까지 고르게 맞히는 것이
  중요하면 model10이다.
- **"검토 필요" 기준 재보정**: 현재 기준(1·2위 확률 비율 1.5 미만)은 **학습에 쓰인
  데이터** 400건으로 잡은 값이라 낙관적이다. 딥러닝팀에서 test셋의 (정답여부, 상위
  확률) 분포를 받아 다시 맞춰야 한다.
- **653 키워드 출처 차이**: 학습데이터의 `653키워드`는 사서가 실제로 부여한 값이지만,
  이 앱은 GPT가 방금 생성한 키워드를 넣는다. 성격이 다른 입력이므로 학습에 쓰이지
  않은 ISBN으로 영향을 확인할 필요가 있다(딥러닝팀 개선 로드맵의 "입력 필드 실험
  (653키워드 출처)" 항목과 같은 문제).
- **배포 방식 미결정**: 추론 시 약 1.5GB를 쓰므로 Render 무료(512MB)·Starter(512MB)에
  들어가지 않는다. 또 `model.safetensors`가 1.28GB라 GitHub 파일 크기 제한(100MB)
  때문에 저장소에 넣을 수도 없어, 유료 플랜으로 올리더라도 외부 스토리지에서
  내려받는 경로를 따로 만들어야 한다. 모델 경량화(양자화)와 별도 추론 서버 분리를
  함께 검토 중이다.
