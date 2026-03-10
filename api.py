"""
api.py — DailyK AI Newsroom 로컬 FastAPI 서버
실행: python3 -m uvicorn api:app --port 8000

파이프라인:
  STEP1  원문 수집   Python (requests)
  STEP2  구조 분석   Gemini
  STEP3  팩트 검증   Gemini
  STEP4  기사 작성   Claude
  STEP5  최종 검수   Claude

엔드포인트:
  GET  /health                   서버 상태
  GET  /article/{id}/{media}     기존 기사 조회
  POST /generate                 SSE 스트리밍 기사 생성
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import writer as W

# ── 앱 초기화 ─────────────────────────────────────────────────
app = FastAPI(title="DailyK Writer API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=2)


# ── 요청 모델 ─────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    id:    str
    media: str            # "enet" | "senior"
    url:   Optional[str] = None   # 직접 제공 시 data.json 조회 생략
    title: Optional[str] = None   # fallback 본문 생성용


# ── SSE 헬퍼 ─────────────────────────────────────────────────
def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── GET /health ───────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── GET /article/{id}/{media} ─────────────────────────────────
@app.get("/article/{article_id}/{media}")
def get_article(article_id: str, media: str):
    path = W.ARTICLES_DIR / f"{article_id}_{media}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="기사 없음")
    return {"content": path.read_text(encoding="utf-8")}


# ── POST /generate  (SSE 스트리밍) ────────────────────────────
@app.post("/generate")
async def generate(req: GenerateRequest):
    if req.media not in ("enet", "senior"):
        raise HTTPException(status_code=400, detail="media 는 enet 또는 senior")

    async def stream():
        loop = asyncio.get_event_loop()

        try:
            # 데이터 로드 (url 직접 제공 시 data.json 조회 생략 — Cloud Run 대응)
            if req.url:
                url        = req.url
                article_id = req.id
            else:
                data = W.load_data()
                item = W.find_item(data, req.id)
                url  = item.get("link", "")
                article_id = item["id"]
            if not url:
                yield sse({"type": "error", "message": "원문 URL이 없습니다."})
                return

            # ── STEP 1: 원문 수집 (실패 시 제목+URL fallback) ──
            yield sse({"step": 1, "status": "running"})
            title = req.title or ""
            body, is_fallback = await loop.run_in_executor(
                executor, W.fetch_full_text_or_fallback, url, title
            )
            await loop.run_in_executor(
                executor, lambda: W.save_source(article_id, body)
            )
            yield sse({"step": 1, "status": "done",
                       "chars": len(body.replace(" ", "")),
                       "fallback": is_fallback})

            # ── STEP 2: 구조 분석 (GPT) ──────────────────────
            yield sse({"step": 2, "status": "running"})
            meta = await loop.run_in_executor(
                executor, W.analyze_structure, body
            )
            yield sse({"step": 2, "status": "done",
                       "subject": meta.get("subject", "")})

            # ── STEP 3: 팩트 검증 (Gemini) ───────────────────
            yield sse({"step": 3, "status": "running"})
            fact = await loop.run_in_executor(
                executor, W.verify_facts, body, meta
            )
            yield sse({"step": 3, "status": "done",
                       "confidence": fact.get("confidence", 0)})

            # ── STEP 4: 기사 작성 (Claude) ───────────────────
            guideline_file = (
                W.ENET_GUIDELINE_FILE if req.media == "enet"
                else W.SENIOR_GUIDELINE_FILE
            )
            media_label = "이넷뉴스" if req.media == "enet" else "한국시니어신문"
            guideline   = W.load_guideline(guideline_file)

            yield sse({"step": 4, "status": "running"})
            draft = await loop.run_in_executor(
                executor,
                W.write_article, body, meta, fact, guideline, media_label
            )
            yield sse({"step": 4, "status": "done"})

            # ── STEP 5: 최종 검수 (GPT) ──────────────────────
            yield sse({"step": 5, "status": "running"})
            final = await loop.run_in_executor(
                executor, W.review_article, draft
            )
            yield sse({"step": 5, "status": "done"})

            # 저장
            await loop.run_in_executor(
                executor, lambda: W.save_md(article_id, req.media, final)
            )

            # 기사 전송
            yield sse({"type": "article", "content": final})
            yield sse({"type": "done"})

        except Exception as e:
            yield sse({"type": "error", "message": f"오류: {e}"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
