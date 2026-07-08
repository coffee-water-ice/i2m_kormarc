# i2m_kormarc — KORMARC 통합 변환 시스템 (골격 단계)

041/245/653/260+300 4개 폴더를 하나의 시스템으로 합치기 위한 통합 골격(skeleton)이다.
자세한 배경은 상위 폴더의 `통합_계획.md`, `docs/INTEGRATION_SURVEY.md`,
`docs/INTEGRATION_PRINCIPLES.md`를 참고할 것.

## 현재 상태

- **실제로 동작함**: 260(발행사항), 300(형태사항) — `260+300` 폴더의 로직을 그대로 이관.
- **스텁만 있음(호출 안 함)**: 041(언어코드/546), 245/246/500/700/710/900, 653(자유주제어).
  `core/fields/marc_*.py`, `api/aladin_scraper.py`, `api/nlk_client.py`에 이식 대상 함수
  시그니처와 원본 파일 경로가 docstring/TODO로 명시되어 있다.

## 설치 및 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

cp .env.example .env            # 값 채우기 (알라딘/OpenAI/KPIPA/행안부/GSPREAD 키)

# 백엔드
uvicorn app:app --reload        # http://127.0.0.1:8000/health

# 프론트엔드 (백엔드가 먼저 떠 있어야 함)
streamlit run streamlit_app.py  # http://localhost:8501
```

## 디렉토리 구조

```
i2m_kormarc/
├── app.py                       # FastAPI 오케스트레이터 (260/300만 실제 호출)
├── streamlit_app.py             # Streamlit 프론트
├── api_client.py                # 프론트 → 백엔드 HTTP 클라이언트
├── core/
│   ├── config.py                # pydantic-settings 통합 설정
│   ├── debug_log.py             # 필드 공용 디버그 로거
│   ├── marc_builder.py          # pymarc.Record ↔ MRK 변환
│   ├── fields/
│   │   ├── marc_041.py          # STUB
│   │   ├── marc_245.py          # STUB
│   │   ├── marc_500_700_710.py  # STUB
│   │   ├── marc_260.py          # 실동작
│   │   ├── marc_300.py          # 실동작
│   │   └── marc_653.py          # STUB
│   └── name_data/               # STUB (245 이름판별 데이터 자리)
├── api/
│   ├── aladin_client.py         # 실동작 (OPT_RESULT_FULL)
│   ├── aladin_scraper.py        # STUB
│   ├── nlk_client.py            # STUB
│   ├── kpipa_client.py          # 실동작
│   ├── mois_client.py           # 실동작
│   ├── publisher_db.py          # 실동작 (build_pub_location_bundle)
│   └── openai_client.py         # 실동작 (클라이언트 팩토리만)
├── database/
│   └── feedback_logger.py       # 실동작 (SQLite)
└── docs/
    ├── INTEGRATION_SURVEY.md
    └── INTEGRATION_PRINCIPLES.md
```

## 다음 단계 (이식 순서 제안)

1. 041 편입 → `core/fields/marc_041.py`, `api/aladin_scraper.scrape_author_bio`
2. 245 편입 → `core/fields/marc_245.py` + `marc_500_700_710.py`, `core/name_data/`,
   `api/nlk_client.fetch_nlk_orig_info` 등
3. 653 편입 → `core/fields/marc_653.py` (app.py를 async로 전환 필요)
4. `app.py`의 TODO 주석 지점에 각 필드 호출 연결, `streamlit_app.py` UI 확장
