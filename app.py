"""
app.py
FastAPI 애플리케이션 진입점 — i2m_kormarc 통합 골격.

이번 골격(skeleton) 단계 범위(통합_계획.md 참고):
  - 260(발행사항)/300(형태사항)은 260+300 폴더의 로직을 그대로 이관해 실제로 동작한다.
  - 041/245/500/700/710/653은 core/fields/*.py에 스텁만 있고 아직 호출하지 않는다.
    아래 _run_conversion() 안에 TODO 주석으로 연결 지점을 표시해 두었다.

엔드포인트:
  POST /api/convert        — 단일 ISBN → MARC 변환 (260/300만 실제 생성)
  POST /api/convert/batch  — 다중 ISBN 일괄 변환
  GET  /api/kpipa/{isbn}   — KPIPA 공식 API 직접 조회
  POST /api/feedback       — 사서 수정값 DB 저장
  GET  /health             — 헬스체크
"""

from __future__ import annotations

import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 내부 모듈 — 새 골격 경로
from core.config import Settings, get_settings, load_streamlit_secrets_into_env
from core.marc_builder import MarcBuilder
from core.fields.marc_260 import build_260_field
from core.fields.marc_300 import build_300_field
from api.aladin_client import get_aladin_item_by_isbn
from api.kpipa_client import get_kpipa_book_detail
from api.publisher_db import build_pub_location_bundle
from database.feedback_logger import init_db, save_feedback_record

# TODO(041 이식 시 주석 해제): from core.fields.marc_041 import build_041_546
# TODO(245 이식 시 주석 해제): from core.fields.marc_245 import build_245_family
# TODO(700/710 이식 시 주석 해제): from core.fields.marc_500_700_710 import build_500_700_710
# TODO(653 이식 시 주석 해제): from core.fields.marc_653 import build_653_field
# TODO(041/245/653 이식 시 주석 해제): from api.openai_client import build_openai_client

logger = logging.getLogger("i2m_kormarc")


# ============================================================
# Lifespan (앱 시작·종료 시 실행)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_streamlit_secrets_into_env()
    init_db()
    logger.info("DB 초기화 완료")
    yield
    logger.info("서버 종료")


# ============================================================
# FastAPI 앱 인스턴스
# ============================================================

app = FastAPI(
    title="I2M KORMARC 통합 변환 API",
    description="알라딘·KPIPA·행안부·OpenAI를 활용한 KORMARC 자동 생성 백엔드 (골격 단계: 260/300만 실동작)",
    version="0.1.0-skeleton",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Pydantic 스키마
# ============================================================

class ConvertRequest(BaseModel):
    isbn: str = Field(
        ...,
        min_length=10,
        max_length=17,
        json_schema_extra={"example": "9788937462849"},
    )


class ConvertResult(BaseModel):
    isbn:           str
    mrk_text:       str
    marc_bytes_b64: str
    meta:           dict
    error:          Optional[str] = None


class BatchRequest(BaseModel):
    jobs: list[ConvertRequest]


class BatchResult(BaseModel):
    results: list[ConvertResult]


class FeedbackRequest(BaseModel):
    isbn:            str = Field(..., json_schema_extra={"example": "9788937462849"})
    field_tag:       str = Field(..., json_schema_extra={"example": "300"})
    ai_value:        str = Field(..., description="AI가 생성한 원본 값")
    corrected_value: str = Field(..., description="사서가 수정한 최종 값")
    librarian_note:  str = Field(default="", description="선택 메모")


class FeedbackResult(BaseModel):
    status: str
    id:     Optional[int] = None


class KpipaResult(BaseModel):
    isbn:  str
    data:  dict
    error: Optional[str] = None


# ============================================================
# 헬퍼
# ============================================================

def _settings_to_secrets(settings: Settings) -> dict:
    """
    core.config.Settings → 기존 함수들이 기대하는 평범한 secrets dict로 변환.

    api/publisher_db.load_publisher_db()는 os.environ["GSPREAD_CREDENTIALS"]를
    직접 읽으므로, .env로만 설정된 경우에도 동작하도록 여기서 한 번 더 주입해 둔다
    (Streamlit secrets.toml 경로는 lifespan의 load_streamlit_secrets_into_env가 이미 처리).
    """
    if settings.gspread_credentials:
        os.environ.setdefault("GSPREAD_CREDENTIALS", settings.gspread_credentials)

    return {
        "ALADIN_TTB_KEY":  settings.aladin_ttb_key,
        "ALADIN_TTB_KEY2": settings.aladin_ttb_key2,
        "ALADIN_TTB_KEY3": settings.aladin_ttb_key3,
        "OPENAI_API_KEY":  settings.openai_api_key,
        "KPIPA_API_KEY":   settings.kpipa_api_key,
        "DATA_GO_KR":      settings.data_go_kr,
        "NLK_CERT_KEY":    settings.nlk_cert_key,
        "NAVER_SEARCH_KEY_ID":     settings.naver_search_key_id,
        "NAVER_SEARCH_KEY_SECRET": settings.naver_search_key_secret,
    }


def _run_conversion(req: ConvertRequest, secrets: dict) -> ConvertResult:
    """
    단일 ISBN 변환 핵심 로직 — 골격 단계에서는 260/300만 실제로 생성한다.

    041/245/500/700/710/653을 이식할 때는 아래 TODO 지점에 각 필드 빌더 호출을
    추가하고, all_tags에 반환된 태그 문자열을 append하면 된다. 041/653은 원본이
    OpenAI를 직접 호출하므로 build_openai_client(get_settings())로 만든 클라이언트를
    함께 넘긴다. 653은 async 함수이므로 이 함수 자체를 async def로 바꾸고
    나머지 동기 호출부는 asyncio.to_thread(...)로 감싸야 한다
    (core/fields/marc_653.py 상단 docstring 참고).
    """
    try:
        isbn = req.isbn.strip().replace("-", "")
        item, aladin_err = get_aladin_item_by_isbn(isbn, secrets)
        if aladin_err:
            return ConvertResult(
                isbn=isbn, mrk_text="", marc_bytes_b64="",
                meta={"isbn": isbn}, error=aladin_err,
            )

        publisher_raw = (item or {}).get("publisher", "") or ""
        pubdate = (item or {}).get("pubDate", "") or ""
        pubyear = pubdate[:4] if len(pubdate) >= 4 else ""

        all_tags: list[str] = []

        # TODO(041 이식 시): openai_client = build_openai_client(get_settings())
        # TODO(041 이식 시): tag_041, tag_546 = build_041_546(item, detail={}, openai_client=openai_client)
        # TODO(041 이식 시): all_tags += [t for t in (tag_041, tag_546) if t]

        # TODO(245 이식 시): field_245_bundle = build_245_family(item, secrets=secrets)
        # TODO(245 이식 시): all_tags += [v for v in field_245_bundle.values() if v]

        # ── 260 ──────────────────────────────────────────────
        bundle = build_pub_location_bundle(isbn, publisher_raw, secrets)
        secondary_pub = bundle.get("secondary_publisher", "")
        tag_260, f_260 = build_260_field(
            place_display=bundle["place_display"],
            publisher_name=publisher_raw,
            pubyear=pubyear,
            publisher_name2=secondary_pub,
        )
        all_tags.append(tag_260)

        # TODO(500/700/710 이식 시): field_770_bundle = build_500_700_710(item, secrets=secrets)
        # TODO(500/700/710 이식 시): all_tags += [...]

        # ── 300 ──────────────────────────────────────────────
        tag_300, f_300, illus_diag = build_300_field(item, isbn=isbn, secrets=secrets)
        all_tags.append(tag_300)

        # TODO(653 이식 시): tag_653, err_653 = await build_653_field(item, secrets=secrets, openai_client=openai_client)
        # TODO(653 이식 시): all_tags.append(tag_653) if not err_653 else None

        # ── Record 조립 ────────────────────────────────────
        builder = MarcBuilder()
        if f_260:
            builder.rec.add_field(f_260)
        if f_300:
            builder.rec.add_field(f_300)

        mrk_text = "\n".join(filter(None, all_tags))
        marc_bytes = builder.rec.as_marc()

        meta = {
            "isbn": isbn,
            "aladin_title": (item or {}).get("title", ""),
            "publisher_raw": publisher_raw,
            "place_display": bundle.get("place_display", ""),
            "pubyear": pubyear,
            "tag_260": tag_260 or "",
            "tag_300": tag_300 or "",
            "category_id":   (item or {}).get("categoryId", ""),
            "category_name": (item or {}).get("categoryName", ""),
            "toc_text": illus_diag.get("toc_text", ""),
            "illus_diagnosis": illus_diag.get("illus_diagnosis", {}),
            "bundle_source": bundle.get("source"),
            "secondary_publisher": secondary_pub,
            "debug_lines": bundle.get("debug", []),
        }

        return ConvertResult(
            isbn=isbn,
            mrk_text=mrk_text,
            marc_bytes_b64=base64.b64encode(marc_bytes).decode(),
            meta=meta,
        )

    except Exception as e:
        logger.exception(f"변환 오류: {req.isbn}")
        return ConvertResult(isbn=req.isbn, mrk_text="", marc_bytes_b64="", meta={}, error=str(e))


# ============================================================
# 엔드포인트
# ============================================================

@app.get("/health", tags=["운영"])
async def health():
    return {"status": "ok"}


@app.post("/api/convert", response_model=ConvertResult, tags=["MARC 변환"])
async def convert_single(req: ConvertRequest):
    """단일 ISBN을 MARC 레코드로 변환한다. (골격 단계: 260/300만 생성)"""
    secrets = _settings_to_secrets(get_settings())
    result = _run_conversion(req, secrets)
    if result.error:
        raise HTTPException(status_code=500, detail=result.error)
    return result


@app.post("/api/convert/batch", response_model=BatchResult, tags=["MARC 변환"])
async def convert_batch(req: BatchRequest):
    """여러 ISBN을 일괄 변환한다. 일부 실패해도 나머지는 계속 처리한다."""
    secrets = _settings_to_secrets(get_settings())
    results = [_run_conversion(job, secrets) for job in req.jobs]
    return BatchResult(results=results)


@app.get("/api/kpipa/{isbn}", response_model=KpipaResult, tags=["KPIPA"])
async def kpipa_detail(isbn: str):
    """KPIPA 공식 OpenAPI로 ISBN 도서 상세 정보를 조회한다."""
    settings = get_settings()
    clean_isbn = isbn.strip().replace("-", "")
    data, err = get_kpipa_book_detail(clean_isbn, settings.kpipa_api_key)
    return KpipaResult(isbn=clean_isbn, data=data, error=err)


@app.post("/api/feedback", response_model=FeedbackResult, tags=["피드백"])
async def feedback(req: FeedbackRequest):
    """사서가 수정한 필드값을 DB에 저장한다."""
    try:
        record_id = save_feedback_record(
            isbn=req.isbn,
            field_tag=req.field_tag,
            ai_value=req.ai_value,
            corrected_value=req.corrected_value,
            librarian_note=req.librarian_note,
        )
        return FeedbackResult(status="ok", id=record_id)
    except Exception as e:
        logger.exception("피드백 저장 오류")
        raise HTTPException(status_code=500, detail=str(e))
