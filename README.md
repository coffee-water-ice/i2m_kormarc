# i2m_kormarc — KORMARC 통합 변환 시스템

041/245/653/260+300 4개 폴더를 하나의 시스템으로 합치는 통합 프로젝트다.
자세한 배경은 상위 폴더의 `통합_계획.md`, `docs/INTEGRATION_SURVEY.md`,
`docs/INTEGRATION_PRINCIPLES.md`를 참고할 것.

## 현재 상태

- **실제로 동작함**: 245/246/500/700/710/900/940(245 폴더 이관), 260/300(260+300 폴더 이관).
- **스텁만 있음(호출 안 함)**: 041(언어코드/546), 653(자유주제어).
  `core/fields/marc_041.py`, `core/fields/marc_653.py`, `api/nlk_client.fetch_kdc_content_code_by_isbn`에
  이식 대상 함수 시그니처와 원본 파일 경로가 docstring/TODO로 명시되어 있다.

## 설치 및 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

cp .env.example .env            # 값 채우기 (알라딘/OpenAI/KPIPA/행안부/NLK/GSPREAD 키)

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
│   ├── debug_log.py             # 필드 공용 디버그 로거
│   ├── marc_builder.py          # pymarc.Record ↔ MRK 변환 (kormarc_tag_to_mrk 어댑터 포함)
│   ├── text_utils.py            # 245 계열 공용 텍스트/이름 유틸 (leaf 모듈, 순환참조 방지)
│   ├── fields/
│   │   ├── marc_041.py          # STUB
│   │   ├── marc_245.py          # 실동작 (245/246/940 + collect_orig_info)
│   │   ├── marc_500_700_710.py  # 실동작 (500/700/710/900)
│   │   ├── marc_260.py          # 실동작
│   │   ├── marc_300.py          # 실동작
│   │   └── marc_653.py          # STUB
│   └── name_data/               # 실동작 (245 이름판별 데이터: 한국/일본 성씨, 출생신고 이름 통계)
├── api/
│   ├── aladin_client.py         # 실동작 (OPT_RESULT_FULL)
│   ├── aladin_scraper.py        # 실동작 (상품페이지 크롤링 + GPT 원제/원저자 웹 검색)
│   ├── nlk_client.py            # 실동작 (245 원서명/원저자명 폴백) + 653용 함수는 STUB
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
2. 653 편입 → `core/fields/marc_653.py` (app.py를 async로 전환 필요), `api/nlk_client.fetch_kdc_content_code_by_isbn`
3. `app.py`의 TODO 주석 지점에 041/653 필드 호출 연결, `streamlit_app.py`/`pages/` UI 확장
