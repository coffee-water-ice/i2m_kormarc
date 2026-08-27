"""
app.py
FastAPI 애플리케이션 진입점 — i2m_kormarc 통합 골격.

현재 상태:
  - 260(발행사항)/300(형태사항)은 260+300 팀원의 로직을 그대로 이관해 실제로 동작한다.
  - 245/246/500/700/710/900은 245 팀원의 로직을 이관해 실제로 동작한다
    (core/fields/marc_245.py, core/fields/marc_500_700_710.py).
  - 041(언어코드)/546(언어주기)은 041 팀원의 LangFieldBuilder를 이관해 실제로 동작한다
    (core/fields/marc_041.py).
  - 653(주제명 키워드)은 653 팀원의 ai_service.py(18개 분야별 GPT 프롬프트)를 이관해
    실제로 동작한다(core/fields/marc_653.py). KPIPA/NLK 보강은 원본과 동일하게
    기본 비활성(opt-in)이다.
  - 007(형태자료 부호)/008(부호화정보)은 2025년 코드(1215_main.py)의 규칙 기반
    로직을 이관해 실제로 동작한다(core/fields/marc_007_008.py). GPT를 쓰지 않고,
    041의 언어코드·260의 발행국코드를 그대로 재사용한다.
  - 020(ISBN)/950(가격)도 같은 2025년 코드에서 이관해 실제로 동작한다
    (core/fields/marc_020_950.py). NLK Seoji로 부가기호·세트ISBN·가격을
    보강하고, 알라딘 정가가 없을 때만 상품페이지 크롤링으로 폴백한다.
  - 490(총서사항)/830(총서 부출표목)도 같은 2025년 코드에서 이관해 실제로
    동작한다(core/fields/marc_490_830.py). 알라딘 seriesInfo.seriesName
    말미의 숫자를 권차($v)로 분리해 기재한다.

엔드포인트:
  POST /api/convert        — 단일 ISBN → MARC 변환
  POST /api/convert/batch  — 다중 ISBN 일괄 변환
  GET  /api/kpipa/{isbn}   — KPIPA 공식 API 직접 조회
  POST /api/feedback       — 사서 수정값 DB 저장
  GET  /health             — 헬스체크
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import openai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 내부 모듈 — 새 골격 경로
from core.config import Settings, get_settings, load_streamlit_secrets_into_env
from core.debug_log import clear_debug_lines, dbg_err, get_debug_lines
from core import llm_health, token_tracker
from core.marc_builder import MarcBuilder, kormarc_tag_to_mrk, mrk_str_to_field
from core.fields.marc_007_008 import build_007_field, build_008_field
from core.fields.marc_020_950 import build_020_fields, build_950_field
from core.fields.marc_490_830 import build_490_830
from core.fields.marc_260 import build_260_field
from core.fields.marc_300 import build_300_field
from core.fields.marc_245 import build_245_family
from core.fields.marc_500_700_710 import build_500_700_710_900
from api.aladin_client import get_aladin_item_by_isbn
from api.kpipa_client import (
    extract_kpipa_author_intro,
    extract_kpipa_toc_only,
    get_kpipa_book_detail,
)
from api.publisher_db import build_pub_location_bundle
from database.feedback_logger import init_db, save_feedback_record

from core.fields.marc_041 import build_041_546, LangFieldBuilder
from core.fields.marc_653 import build_653_field
from core.fields.marc_056 import build_056_field

logger = logging.getLogger("i2m_kormarc")

# ── 배포(갱신) 시각/커밋 — 모듈 로드 시 한 번만 계산 ──────────────────
#
# 처음엔 "프로세스 시작 시각"(datetime.now())을 썼는데, Render 무료 플랜은
# 15분 무요청 시 슬립했다가 다음 요청에서 다시 깨어날 때도 프로세스가 재시작된다
# — 실제 코드 배포가 아닌 단순 콜드 스타트 재기동인데도 "방금 배포됨"처럼
# 보이는 문제가 있었다. 그래서 프로세스 재시작마다 바뀌지 않고, 실제 빌드
# 시점에만 바뀌는 "이 파일(app.py)의 최종 수정시각(mtime)"으로 바꿨다 — Render가
# 배포마다 저장소를 새로 체크아웃해서 이미지를 빌드하므로, 이 mtime은 곧 그
# 체크아웃(=배포) 시각이고 이후 콜드 스타트로 프로세스만 재시작돼도 파일을 다시
# 쓰지 않는 한 그대로 유지된다. 로컬 개발 환경에서도 "app.py를 마지막으로 저장한
# 시각"이라는 나름 의미 있는 값이 된다.
_KST = timezone(timedelta(hours=9))
_DEPLOY_TIME = datetime.fromtimestamp(
    os.path.getmtime(__file__), tz=_KST
).strftime("%Y-%m-%d %H:%M:%S")

# 배포된 커밋 정보. 플랫폼마다 알아내는 방법이 다르다.
#
#   Render   : RENDER_GIT_COMMIT을 빌드마다 자동 주입한다.
#   HF Space : 그런 변수가 없다. Space 저장소의 .git은 배포 워크플로가 만든
#              단일 커밋이라 GitHub의 실제 해시를 담고 있지 않다 — 그래서
#              화면에 "local-dev"로 떠서 배포본인데도 로컬처럼 보였다.
#              워크플로가 DEPLOY_COMMIT 파일에 GitHub 해시와 커밋 제목을 적어둔다.
#   로컬     : 둘 다 없으므로 .git에 직접 물어본다.
_DEPLOY_COMMIT_FILE = Path(__file__).resolve().parent / "DEPLOY_COMMIT"


def _read_deploy_commit_file() -> tuple[str, str]:
    """DEPLOY_COMMIT 파일에서 (해시, 커밋 제목)을 읽는다. 없으면 ("", "")."""
    try:
        lines = _DEPLOY_COMMIT_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    sha = lines[0].strip() if lines else ""
    msg = lines[1].strip() if len(lines) > 1 else ""
    return sha, msg


def _git_head(fmt: str) -> str:
    """
    로컬 개발 환경에서 .git에 직접 물어본다. 실패하면 빈 문자열.

    encoding을 명시하는 이유: text=True만 쓰면 파이썬이 로케일 인코딩으로 읽는데,
    한국어 Windows는 cp949라 한글 커밋 메시지에서 UnicodeDecodeError가 난다.
    git 출력은 UTF-8이므로 그렇게 읽고, 혹시 깨진 바이트가 있어도 죽지 않게 replace한다.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", f"--format={fmt}"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
            cwd=Path(__file__).resolve().parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


_FILE_SHA, _FILE_MSG = _read_deploy_commit_file()

_DEPLOY_COMMIT = (
    os.environ.get("RENDER_GIT_COMMIT", "")
    or _FILE_SHA
    or _git_head("%H")
)[:7] or "local-dev"

_DEPLOY_COMMIT_MSG = _FILE_MSG or _git_head("%s")


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
    description="알라딘·KPIPA·행안부·OpenAI를 활용한 KORMARC 자동 생성 백엔드 (전 필드 실동작)",
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

    # core/kdc_model.py와 core/fields/marc_056.py도 같은 방식으로 os.environ에서 읽는다
    # (필드 모듈이 core.config를 import하지 않게 두기 위함 — 원칙 #9 "행 자체 완결").
    # 토큰 예산·MAX_LEN은 학습 전처리와 일치해야 하는 값이라 모델 라운드마다 다르다.
    if settings.kdc_model_dir:
        os.environ.setdefault("KDC_MODEL_DIR", settings.kdc_model_dir)
    # KDC_MODEL_VERSION은 표시용일 뿐 아니라 입력 스키마 판정의 근거다
    # (marc_056.input_schema가 "model21" 포함 여부를 본다). 예전에는 이 값을 환경에
    # 넣지 않아, .env로만 설정하면 스키마가 항상 v8로 잡히는 문제가 있었다.
    os.environ.setdefault("KDC_MODEL_VERSION", settings.kdc_model_version)
    if settings.kdc_input_schema:
        os.environ.setdefault("KDC_INPUT_SCHEMA", settings.kdc_input_schema)
    os.environ.setdefault("KDC_EDITION", settings.kdc_edition)
    os.environ.setdefault("KDC_MAX_LEN", str(settings.kdc_max_len))
    os.environ.setdefault("KDC_KEYWORD_TOKEN_BUDGET", str(settings.kdc_keyword_token_budget))
    os.environ.setdefault("KDC_TOC_TOKEN_BUDGET", str(settings.kdc_toc_token_budget))
    os.environ.setdefault("KDC_DESC_TOKEN_BUDGET", str(settings.kdc_desc_token_budget))
    os.environ.setdefault("KDC_SUBTITLE_TOKEN_BUDGET", str(settings.kdc_subtitle_token_budget))
    os.environ.setdefault("KDC_PUBLISHER_TOKEN_BUDGET", str(settings.kdc_publisher_token_budget))
    os.environ.setdefault("KDC_ADDCODE_TOKEN_BUDGET", str(settings.kdc_addcode_token_budget))
    os.environ.setdefault("KDC_KPIPA_TOC_TOKEN_BUDGET", str(settings.kdc_kpipa_toc_token_budget))
    os.environ.setdefault("KDC_KPIPA_AUTHOR_TOKEN_BUDGET", str(settings.kdc_kpipa_author_token_budget))

    return {
        "ALADIN_TTB_KEY":  settings.aladin_ttb_key,
        "ALADIN_TTB_KEY2": settings.aladin_ttb_key2,
        "ALADIN_TTB_KEY3": settings.aladin_ttb_key3,
        "OPENAI_API_KEY":  settings.openai_api_key,
        "KPIPA_API_KEY":   settings.kpipa_api_key,
        "DATA_GO_KR":      settings.data_go_kr,
        "NLK_CERT_KEY":    settings.nlk_cert_key,
    }


def _build_openai_client(settings: Settings) -> openai.OpenAI | None:
    """
    245(원제/원저자 웹 검색)가 요구하는 넉넉한 timeout(60초, 원본 245/app.py 기준)으로
    클라이언트를 만든다. API 키가 없으면 None — 각 빌더가 None을 받으면 GPT 단계를
    건너뛰고 규칙 기반 폴백만 쓰도록 이미 설계되어 있다(041 방식 주입, 원칙 #3).
    """
    if not settings.openai_api_key:
        return None
    return openai.OpenAI(api_key=settings.openai_api_key, timeout=60.0)


_SUBFIELD_RE_CACHE: dict[str, re.Pattern] = {}


def _subfield_value(mrk_tag: str, code: str) -> str:
    """
    MRK 문자열("245 00 $a본표제 :$b부제")에서 서브필드 하나의 값을 꺼낸다.

    056 model21은 부제·발행자·부가기호를 입력으로 쓰는데, 학습데이터에서는 정독
    MARC의 별도 열이었다. 우리는 그 카탈로그가 없으므로 방금 생성한 태그에서 되꺼낸다.
    끝에 붙는 MARC 구두점(" :", " /", ",", ";")은 학습데이터의 해당 열에는 없으므로 떼어낸다.
    """
    if not mrk_tag or not code:
        return ""
    pattern = _SUBFIELD_RE_CACHE.get(code)
    if pattern is None:
        pattern = re.compile(rf"\${code}([^$]*)")
        _SUBFIELD_RE_CACHE[code] = pattern
    m = pattern.search(mrk_tag)
    if not m:
        return ""
    return m.group(1).strip().rstrip(":/,;=").strip()


def _kpipa_payload_for_056(isbn: str, secrets: dict, settings: Settings) -> dict:
    """
    056 모델 입력에 쓸 KPIPA 목차·저자소개. 한 번의 조회로 둘 다 뽑는다.

    v8 스키마(model8~12)에서는 알라딘 목차가 비었을 때의 대체용으로만 썼지만,
    v21(model21)은 KPIPA 목차를 별도 슬롯으로도 넣으므로 매 건 필요하다.

    KPIPA 호출은 653과 마찬가지로 opt-in(kpipa_enable_653)이다. 키가 없거나 조회에
    실패하면 빈 값을 돌려주고 056은 해당 필드 없이 진행한다 — 학습 때도 결측 행이
    많았고(목차 12.1%, 저자소개 0.1%) field-dropout으로 내성이 학습되어 있다.
    """
    empty = {"toc": "", "author": ""}
    if not (settings.kpipa_enable_653 and secrets.get("KPIPA_API_KEY")):
        return empty
    try:
        raw, err = get_kpipa_book_detail(isbn, secrets["KPIPA_API_KEY"])
        if err or not raw:
            return empty
        return {
            "toc": extract_kpipa_toc_only(raw) or "",
            "author": extract_kpipa_author_intro(raw) or "",
        }
    except Exception as e:
        dbg_err("[056] KPIPA 조회 실패:", e)
        return empty


def _run_conversion(req: ConvertRequest, secrets: dict) -> ConvertResult:
    """
    단일 ISBN 변환 핵심 로직. 020/041/546/245/246/500/700/710/900/007/008/490/830/260/300/653/950을 생성한다.
    """
    start_time = time.perf_counter()
    token_tracker.clear()
    # 필드 단위 소요시간·토큰 — 평가시스템(pages/3_평가시스템.py)이 ISBN 전체 합계 말고
    # 041/245/260/300/653처럼 필드별로도 보고 싶어해서 추가했다. _run_conversion()이
    # 필드를 순서대로 한 번씩만 호출하는 구조라 각 호출을 _step()으로 감싸 시간을
    # 재고, token_tracker 누적값의 호출 전후 차이만 구하면 된다 — 041/300/653/700
    # 등 GPT를 쓰는 필드 모듈 자체는 하나도 손대지 않는다.
    field_elapsed_ms: dict[str, int] = {}
    field_tokens: dict[str, int] = {}

    def _step(name: str, fn, *args, **kwargs):
        """호출 1건의 시간·토큰을 재서 name 키에 더한다(덮어쓰지 않음) — 056처럼
        한 필드가 내부적으로 여러 호출(KPIPA 조회 + 모델 추론)로 나뉠 때도
        _step을 두 번 불러 같은 이름에 누적하면 된다."""
        _t0 = time.perf_counter()
        _tok0 = token_tracker.get_total()["total_tokens"]
        result = fn(*args, **kwargs)
        field_elapsed_ms[name] = field_elapsed_ms.get(name, 0) + round((time.perf_counter() - _t0) * 1000)
        field_tokens[name] = field_tokens.get(name, 0) + (token_tracker.get_total()["total_tokens"] - _tok0)
        return result

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

        settings = get_settings()
        openai_client = _build_openai_client(settings)
        builder = MarcBuilder()
        all_tags: list[str] = []

        def _add(tag_line: str | None) -> None:
            """
            245 계열("700 1_ $a ...")과 260/300 계열("=260  ...")이 서로 다른 태그
            표기 관용을 쓰므로, mrk_text에는 항상 표준 "=TAG  INDIND..." 형식으로
            정규화해서 담는다(kormarc_tag_to_mrk가 이미 "=" 형식인 태그는 그대로 통과).
            """
            if not tag_line:
                return
            mrk_line = tag_line if tag_line.startswith("=") else (kormarc_tag_to_mrk(tag_line) or tag_line)
            all_tags.append(mrk_line)
            field = mrk_str_to_field(mrk_line)
            if field:
                builder.rec.add_field(field)

        # ── 020 ──────────────────────────────────────────────
        tags_020 = _step("020", build_020_fields, item, isbn, nlk_cert_key=secrets.get("NLK_CERT_KEY", ""))
        for t in tags_020:
            _add(t)

        # ── 490/830 (총서) ─────────────────────────────────────
        tag_490, tag_830 = _step("490_830", build_490_830, item)
        _add(tag_490)
        _add(tag_830)

        # ── 041/546 ──────────────────────────────────────────
        tag_041, tag_546, orig_title_041 = _step(
            "041_546", build_041_546,
            item, detail={},
            openai_client=openai_client,
            model=settings.openai_model_041,
        )
        _add(LangFieldBuilder.as_mrk_041(tag_041))
        _add(LangFieldBuilder.as_mrk_546(tag_546))

        # ── 245/246/900 계열 ────────────────────────────────
        f245_ctx = _step(
            "245", build_245_family,
            item, isbn,
            aladin_ttb_key=secrets.get("ALADIN_TTB_KEY", ""),
            nlk_api_key=secrets.get("NLK_CERT_KEY", ""),
            openai_client=openai_client,
            lang_h=LangFieldBuilder.extract_lang_h(tag_041),
        )
        _add(f245_ctx["field_245"])

        f5_result = _step("246_500_700_710_900", build_500_700_710_900, f245_ctx, openai_client=openai_client)
        if f5_result["field_246"]:
            _add(f5_result["field_246"])
        for t in f5_result["fields_500"]:
            _add(t)
        for t in f5_result["fields_700"]:
            _add(t)
        for t in f5_result["fields_710"]:
            _add(t)
        for t in f5_result["fields_900"]:
            _add(t)
        if f245_ctx["field_940"]:
            _add(f245_ctx["field_940"])

        # ── 260 ──────────────────────────────────────────────
        bundle = _step("260", build_pub_location_bundle, isbn, publisher_raw, secrets)
        secondary_pub = bundle.get("secondary_publisher", "")
        tag_260, f_260 = build_260_field(
            place_display=bundle["place_display"],
            publisher_name=publisher_raw,
            pubyear=pubyear,
            publisher_name2=secondary_pub,
        )
        all_tags.append(tag_260)
        if f_260:
            builder.rec.add_field(f_260)

        # ── 007/008 ──────────────────────────────────────────
        # 041의 언어코드($a)와 260의 발행국코드(bundle)가 모두 필요해 이 시점에 생성한다.
        tag_007 = build_007_field()
        _add(tag_007)
        tag_008 = build_008_field(
            item,
            country_code=bundle.get("country_code", "   "),
            lang3=LangFieldBuilder.lang3_from_tag041(tag_041),
        )
        _add(tag_008)

        # ── 300 ──────────────────────────────────────────────
        tag_300, f_300, illus_diag = _step("300", build_300_field, item, secrets=secrets)
        all_tags.append(tag_300)
        if f_300:
            builder.rec.add_field(f_300)

        # ── 950 ──────────────────────────────────────────────
        tag_950 = build_950_field(item, isbn)
        _add(tag_950)

        # ── 653 ──────────────────────────────────────────────
        tag_653, err_653 = _step(
            "653", build_653_field,
            item, isbn,
            openai_client=openai_client,
            model=settings.openai_model_653,
            max_keywords=settings.max_keywords_653,
            min_keywords=settings.min_keywords_653,
            kpipa_api_key=secrets.get("KPIPA_API_KEY", ""),
            kpipa_enable=settings.kpipa_enable_653,
            nlk_cert_key=secrets.get("NLK_CERT_KEY", ""),
            nlk_enable=settings.nlk_enable_653,
        )
        _add(tag_653)  # 실패 사유는 build_653_field 내부에서 이미 [653] 디버그 로그로 남긴다

        # ── 056 (KDC 분류기호, 딥러닝 모델) ──────────────────
        # 653 키워드는 v8 스키마(model8~12)에서만 모델 입력에 들어간다. 그 경우
        # 반드시 653 이후에 실행해야 하므로 위치는 그대로 둔다 — model21(v21)로
        # 바꾸면 653을 쓰지 않지만, 순서를 지켜도 손해가 없다.
        # 목차는 300 처리에서 이미 확보한 값을 재사용해 알라딘 재크롤링을 피한다.
        _kpipa_raw = _step("056", _kpipa_payload_for_056, isbn, secrets, settings)
        tag_056, diag_056 = _step(
            "056", build_056_field,
            item,
            tag_653=tag_653,
            toc_text=illus_diag.get("toc_text", ""),
            kpipa_toc=_kpipa_raw["toc"],
            kpipa_author=_kpipa_raw["author"],
            # v21 신설 필드 — 학습데이터에서는 정독 MARC의 부제/발행자/부가기호였다.
            # 우리는 그 카탈로그가 없으므로 방금 생성한 245 $b / 260 $b / 020 $g를 쓴다.
            subtitle=_subfield_value(f245_ctx.get("field_245", ""), "b"),
            publisher=_subfield_value(tag_260, "b"),
            addcode=_subfield_value(tags_020[0] if tags_020 else "", "g"),
        )
        if tag_056:
            # MARC 태그 순서를 지키기 위해 append가 아니라 056보다 큰 첫 태그 앞에 끼운다.
            pos = next(
                (i for i, t in enumerate(all_tags) if t[1:4].isdigit() and t[1:4] > "056"),
                len(all_tags),
            )
            all_tags.insert(pos, tag_056)
            field_056 = mrk_str_to_field(tag_056)
            if field_056:
                builder.rec.add_field(field_056)

        mrk_text = "\n".join(filter(None, all_tags))
        marc_bytes = builder.rec.as_marc()

        meta = {
            "isbn": isbn,
            "aladin_title": (item or {}).get("title", ""),
            "publisher_raw": publisher_raw,
            "place_display": bundle.get("place_display", ""),
            "pubyear": pubyear,
            "tag_041": tag_041 or "",
            "tag_546": tag_546 or "",
            "tag_007": tag_007 or "",
            "tag_008": tag_008 or "",
            "tag_020": tags_020[0] if tags_020 else "",
            "tag_490": tag_490 or "",
            "tag_830": tag_830 or "",
            "tag_950": tag_950 or "",
            "tag_260": tag_260 or "",
            "tag_300": tag_300 or "",
            "tag_653": tag_653 or "",
            "tag_056": tag_056 or "",
            "kdc_candidates": diag_056.get("candidates", []),
            "kdc_low_confidence": diag_056.get("low_confidence", False),
            "kdc_margin_ratio": diag_056.get("margin_ratio"),
            "kdc_edition": diag_056.get("edition", ""),
            "kdc_reason": diag_056.get("reason", ""),
            # 평가 시트의 "입력 결손"(653/목차/책소개 유무) 열이 쓰는 값.
            "kdc_input_presence": diag_056.get("input_presence", {}),
            "kdc_model_version": settings.kdc_model_version,
            # 입력 스키마와 실제 사용된 필드. 모델 버전 문자열은 우리가 붙인 표시용이라
            # 실제로 무엇이 돌았는지를 보증하지 못한다. 653을 입력에 넣었는지 여부는
            # 스키마가 결정하므로, 이 값이 model21 전환의 실질적 확인 근거가 된다.
            "kdc_input_schema": diag_056.get("input_schema", ""),
            "kdc_input_fields": [
                k for k, v in (diag_056.get("input_presence") or {}).items() if v
            ],
            "category_id":   (item or {}).get("categoryId", ""),
            "category_name": (item or {}).get("categoryName", ""),
            "toc_text": illus_diag.get("toc_text", ""),
            "illus_diagnosis": illus_diag.get("illus_diagnosis", {}),
            "bundle_source": bundle.get("source"),
            "secondary_publisher": secondary_pub,
            "orig_title": f245_ctx.get("orig_title", ""),
            "orig_author_en": f245_ctx.get("orig_author_en", ""),
            "translation_book": f245_ctx.get("translation_book", False),
            "debug_lines": bundle.get("debug", []) + get_debug_lines(),
            "elapsed_ms": round((time.perf_counter() - start_time) * 1000),
            "token_usage": token_tracker.get_total(),
            # 필드별 소요시간(ms)·토큰 — 키는 _step() 호출부에 준 이름 그대로:
            # 020 / 490_830 / 041_546 / 245 / 246_500_700_710_900 / 260 / 300 / 653 / 056.
            # GPT를 안 쓰는 필드(020/490_830/260/056)는 field_tokens 값이 항상 0이다.
            "field_elapsed_ms": field_elapsed_ms,
            "field_tokens": field_tokens,
        }
        # 이 변환에서 GPT 호출이 한 번이라도 성공했는지. 041/245/300/653은 모두
        # 호출 직후 token_tracker.add()를 하므로, 합계가 0이면 전부 실패했다는 뜻이다.
        # 크레딧 소진처럼 실행 도중에 시작되는 장애를 건별로 잡아내기 위한 것 —
        # 200건을 돌리는 중간에 크레딧이 떨어지면 그 이후 결과가 조용히 오염된다.
        meta["gpt_called"] = meta["token_usage"]["total_tokens"] > 0
        clear_debug_lines()
        token_tracker.clear()

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
    """
    헬스체크 + 시스템 상태. Streamlit Home 페이지가 이 응답 하나로 백엔드 연결
    여부·마지막 배포(갱신) 시각·커밋·외부 API 키 설정 여부를 표시한다(키 값 자체는
    절대 노출하지 않고 설정 유무만 boolean으로 반환).

    openai_live는 키 설정 여부가 아니라 **실제로 호출이 되는지**다. 크레딧이 0원인
    키는 인증을 통과해 secrets_configured에 True로 잡히지만 모든 GPT 호출이 실패한다
    (실제 발생 사례 — core/llm_health.py 참고). 실호출 1회를 10분 캐시로 확인한다.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "version": {
            "deployed_at": _DEPLOY_TIME,
            "commit": _DEPLOY_COMMIT,
            "commit_message": _DEPLOY_COMMIT_MSG,
        },
        "secrets_configured": {
            "aladin_ttb_key":      bool(settings.aladin_ttb_key),
            "openai_api_key":      bool(settings.openai_api_key),
            "kpipa_api_key":       bool(settings.kpipa_api_key),
            "data_go_kr":          bool(settings.data_go_kr),
            "nlk_cert_key":        bool(settings.nlk_cert_key),
            "gspread_credentials": bool(settings.gspread_credentials),
        },
        "openai_live": llm_health.check_openai(settings.openai_api_key or ""),
    }


@app.post("/api/openai/recheck", tags=["운영"])
async def openai_recheck():
    """OpenAI 실호출 점검을 캐시 무시하고 다시 수행한다.

    크레딧을 충전하거나 키를 교체한 직후, 10분 캐시가 만료되기를 기다리지 않고
    바로 확인하기 위한 엔드포인트다.
    """
    settings = get_settings()
    return llm_health.check_openai(settings.openai_api_key or "", force=True)


@app.post("/api/convert", response_model=ConvertResult, tags=["MARC 변환"])
async def convert_single(req: ConvertRequest):
    """단일 ISBN을 MARC 레코드로 변환한다. (020/041/546/245/246/500/700/710/900/940/007/008/490/830/260/300/653/950 생성)"""
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
