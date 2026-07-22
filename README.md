# i2m_kormarc — KORMARC 통합 변환 시스템

041/245/653/260+300 4개 폴더를 하나의 시스템으로 합치는 통합 프로젝트다.
자세한 배경은 상위 폴더의 `통합_계획.md`, `docs/INTEGRATION_SURVEY.md`,
`docs/INTEGRATION_PRINCIPLES.md`를 참고할 것.

## 현재 상태

041/245/653/260+300 4개 폴더 통합이 모두 끝나 전 필드가 실제로 동작한다.

- **041**(언어코드/546) — 041 폴더의 `LangFieldBuilder` 이관 (`core/fields/marc_041.py`)
- **245/246/500/700/710/900/940** — 245 폴더 이관 (`core/fields/marc_245.py`, `marc_500_700_710.py`)
- **260/300**(발행사항/형태사항) — 260+300 폴더 이관 (`core/fields/marc_260.py`, `marc_300.py`)
- **653**(자유주제어) — 653 폴더의 `ai_service.py`(18개 분야별 GPT 프롬프트 + 키워드
  필터링 파이프라인) 이관 (`core/fields/marc_653.py`). 알라딘 상세페이지 크롤링·KPIPA
  ONIX 목차·NLK 부가기호 보강도 함께 이식했으며, KPIPA/NLK 보강은 원본과 동일하게
  기본 비활성(opt-in, `core.config.Settings.kpipa_enable_653`/`nlk_enable_653`)이다.

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
│   ├── fields/
│   │   ├── marc_041.py          # 실동작 (041/546, LangFieldBuilder)
│   │   ├── marc_245.py          # 실동작 (245/246/940 + collect_orig_info)
│   │   ├── marc_500_700_710.py  # 실동작 (500/700/710/900)
│   │   ├── marc_260.py          # 실동작
│   │   ├── marc_300.py          # 실동작
│   │   ├── marc_653.py          # 실동작 (653, 18개 분야별 GPT 프롬프트 + 키워드 필터링)
│   │   └── few_shots_653.json   # 653 GPT 프롬프트용 few-shot 예시 데이터
│   └── name_data/               # 실동작 (245 이름판별 데이터: 한국/일본 성씨, 출생신고 이름 통계)
├── api/
│   ├── aladin_client.py         # 실동작 (OPT_RESULT_FULL)
│   ├── aladin_scraper.py        # 실동작 (상품페이지·저자프로필 크롤링, GPT 원제/원저자 웹 검색,
│   │                             #          653용 getContents.aspx 책소개/목차 크롤링)
│   ├── nlk_client.py            # 실동작 (245 원서명/원저자명 폴백 + 653 부가기호 content_code)
│   ├── kpipa_client.py          # 실동작 (출판사명 조회 + 653 ONIX 목차 추출)
│   ├── mois_client.py           # 실동작
│   ├── publisher_db.py          # 실동작 (build_pub_location_bundle)
│   └── openai_client.py         # 실동작 (클라이언트 팩토리만)
├── database/
│   └── feedback_logger.py       # 실동작 (SQLite, field_tag로 041~653 전 필드 공용)
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
