"""
writer.py — DailyK AI Newsroom 심층기사 생성기

파이프라인:
  STEP1  원문 수집   fetch_full_text()     requests + BeautifulSoup
  STEP2  구조 분석   analyze_structure()   Gemini 2.5 Flash
  STEP3  팩트 검증   verify_facts()        Gemini 2.5 Flash
  STEP4  기사 작성   write_article()       Claude
  STEP5  최종 검수   review_article()      Claude

사용법:
  python writer.py --id <article_id> --media <enet|senior|both>

출력:
  articles/<id>_source.txt      원문 전문
  articles/<id>_enet.md         이넷뉴스 심층기사
  articles/<id>_senior.md       시니어신문 심층기사
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

# ── API 클라이언트 ────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")

GEMINI_MODEL    = "gemini-2.5-flash"   # 변경 시 이 상수만 수정
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

HEADERS = _random_headers()  # 하위 호환용 (crawler.py 등에서 직접 참조 시)

# ── 경로 상수 ─────────────────────────────────────────────────
MIN_BODY_CHARS        = 500
GEMINI_TIMEOUT        = 120
CLAUDE_TIMEOUT        = 180
ARTICLES_DIR          = Path("articles")
DATA_JSON             = Path("data.json")
GUIDELINES_DIR        = Path("guidelines")
ENET_GUIDELINE_FILE   = GUIDELINES_DIR / "enetnews_v1_1.md"
SENIOR_GUIDELINE_FILE = GUIDELINES_DIR / "korea_senior_news_v2_0.md"


# ── 로그 ─────────────────────────────────────────────────────
def log(step: str, msg: str):
    print(f"[{step}] {msg}")


# ── API 호출 ─────────────────────────────────────────────────
def call_gemini(prompt: str, retries: int = 4) -> str:
    import time
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 없음")
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    print(f"[Gemini] model={GEMINI_MODEL} | prompt={len(prompt)}자")
    for attempt in range(retries):
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=GEMINI_TIMEOUT,
        )
        if resp.ok:
            time.sleep(2)
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            print(f"[Gemini] 쿼터 초과 → {wait}초 후 재시도 ({attempt+1}/{retries})")
            time.sleep(wait)
        else:
            print(f"[Gemini ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
    raise RuntimeError("Gemini 재시도 초과")



def call_claude(prompt: str, system: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 없음")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── 공통 유틸 ─────────────────────────────────────────────────
def load_guideline(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"집필 지침 없음: {path}")
    return path.read_text(encoding="utf-8")


def load_data() -> dict:
    if not DATA_JSON.exists():
        raise FileNotFoundError("data.json 없음. crawler.py를 먼저 실행하세요.")
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


def find_item(data: dict, article_id: str) -> dict:
    for item in data.get("items", []):
        if str(item["id"]) == str(article_id):
            return item
    raise ValueError(f"ID '{article_id}' 를 data.json에서 찾을 수 없습니다.")


def extract_json_block(text: str) -> dict:
    m = re.search(r"\{[\s\S]+\}", text)
    if not m:
        raise RuntimeError(f"JSON 블록 없음:\n{text[:300]}")
    return json.loads(m.group())


# ── STEP 1: 원문 수집 ─────────────────────────────────────────
FETCH_TIMEOUT = 40  # 20 → 40초

def fetch_full_text(url: str) -> str:
    """원문 수집. 타임아웃/차단 시 RuntimeError를 raise한다."""
    log("STEP1 원문수집", url)
    try:
        resp = requests.get(url, headers=_random_headers(), timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"원문 요청 실패: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer",
                      "aside", "form", "iframe", "noscript"]):
        tag.decompose()

    selectors = [
        "article", ".article-body", ".article_body", ".article-content",
        ".news-content", ".view-content", ".cont-body",
        "#article-view-content-div", ".news_body", ".article_txt",
        ".story-body", "main",
    ]
    body_text = ""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            body_text = el.get_text(separator="\n", strip=True)
            if len(body_text.replace(" ", "")) >= MIN_BODY_CHARS:
                break

    if len(body_text.replace(" ", "")) < MIN_BODY_CHARS:
        paras = [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 30
        ]
        body_text = "\n".join(paras)

    body_clean = body_text.strip()
    char_count = len(body_clean.replace(" ", ""))

    if char_count < MIN_BODY_CHARS:
        raise RuntimeError(
            f"원문 본문 {char_count}자 — {MIN_BODY_CHARS}자 미만.\n"
            "본문 수집 실패. 기사 생성을 중단합니다.\n"
            "원문 링크를 직접 확인하거나 접근이 차단된 사이트일 수 있습니다."
        )

    log("STEP1 원문수집", f"완료 ({char_count}자)")
    return body_clean


def fetch_full_text_or_fallback(url: str, title: str = "") -> tuple[str, bool]:
    """원문 수집 시도 후 실패 시 제목+URL로 fallback 본문 생성.
    반환: (body_text, is_fallback)
    """
    try:
        return fetch_full_text(url), False
    except RuntimeError as e:
        log("STEP1 원문수집", f"실패 → fallback 사용: {e}")
        fallback_body = (
            f"[원문 수집 실패 — URL 기반 기사 작성]\n\n"
            f"기사 제목: {title}\n"
            f"원문 URL: {url}\n\n"
            "원문을 직접 수집하지 못했습니다. "
            "제목과 URL 정보를 바탕으로 기사를 작성합니다."
        )
        return fallback_body, True


# ── STEP 2: 구조 분석 (GPT) ───────────────────────────────────
META_PROMPT = """아래 기사 원문에서 다음 6개 항목을 정확히 추출하라.
JSON 형식으로만 출력하라. 추가 설명 없이 JSON만 출력한다.

{{
  "subject":          "주체 (정부부처·기업·기관명 정확히)",
  "effective_date":   "시행 시점 (날짜·기간·즉시 등)",
  "key_figures":      ["핵심 수치 1", "핵심 수치 2"],
  "impact":           "정책/산업 영향 2~3문장",
  "senior_relevance": "시니어 관련성 (없으면 '해당없음')",
  "conditions":       ["예외 조건 또는 단서 (없으면 빈 배열)"]
}}

기사 원문:
{body}
"""

def analyze_structure(body: str) -> dict:
    log("STEP2 구조분석", "Gemini 메타 추출 중...")
    prompt = META_PROMPT.format(body=body[:4000])
    raw    = call_gemini(prompt)
    meta   = extract_json_block(raw)
    log("STEP2 구조분석", f"주체={meta.get('subject','?')} / 시행={meta.get('effective_date','?')}")
    return meta


# ── STEP 3: 팩트 검증 (Gemini) ───────────────────────────────
FACT_PROMPT = """아래 기사 본문과 추출 수치를 교차 검증하라.
수치 오류나 내부 불일치가 있으면 지적하고, 없으면 "이상 없음"을 출력하라.
JSON으로만 출력한다.

{{
  "confidence": 0~100,
  "issues": ["이슈1"],
  "verdict": "이상 없음" 또는 "검토 필요"
}}

기사 본문:
{body}

추출 수치:
{figures}
"""

def verify_facts(body: str, meta: dict) -> dict:
    log("STEP3 팩트검증", "Gemini 수치 교차 검증 중...")
    figures = "\n".join(meta.get("key_figures", [])) or "수치 없음"
    prompt  = FACT_PROMPT.format(body=body[:4000], figures=figures)
    raw     = call_gemini(prompt)
    try:
        result = extract_json_block(raw)
    except Exception:
        result = {"confidence": 50, "issues": [], "verdict": "검증 실패"}
    log("STEP3 팩트검증", f"신뢰도={result.get('confidence')}% / {result.get('verdict')}")
    return result


# ── STEP 4: 기사 작성 (Claude) ────────────────────────────────
WRITE_SYSTEM = """당신은 {media_label} 전속 심층기사 전문 기자다.
아래 집필 지침을 절대적 기준으로 삼아 기사를 작성한다.
지침의 모든 규칙을 빠짐없이 적용하며, 기사만 출력하고 부연 설명은 일절 쓰지 않는다.

[집필 지침]
{guideline}
"""

WRITE_PROMPT = """아래 원문과 추출 메타를 바탕으로 심층기사를 작성하라.

[원문 본문]
{body}

[추출 메타]
- 주체: {subject}
- 시행 시점: {effective_date}
- 핵심 수치: {key_figures}
- 정책/산업 영향: {impact}
- 시니어 관련성: {senior_relevance}
- 예외/단서: {conditions}

[팩트 검증]
신뢰도: {confidence}% / 이슈: {issues}

집필 지침에 명시된 구조(SEO 제목 3개, 부제, 리드, 중제 3개, 본문, 마무리, 해시태그)를
빠짐없이 출력하라.
"""

def write_article(body: str, meta: dict, fact: dict,
                  guideline: str, media_label: str) -> str:
    log("STEP4 기사작성", f"Claude — [{media_label}] 집필 중...")
    system = WRITE_SYSTEM.format(media_label=media_label, guideline=guideline)
    prompt = WRITE_PROMPT.format(
        body=body[:5000],
        subject=meta.get("subject", ""),
        effective_date=meta.get("effective_date", ""),
        key_figures=", ".join(meta.get("key_figures", [])),
        impact=meta.get("impact", ""),
        senior_relevance=meta.get("senior_relevance", ""),
        conditions=", ".join(meta.get("conditions", [])) or "없음",
        confidence=fact.get("confidence", "?"),
        issues=", ".join(fact.get("issues", [])) or "없음",
    )
    draft = call_claude(prompt, system)
    log("STEP4 기사작성", f"초안 완료 ({len(draft.replace(' ',''))}자)")
    return draft


# ── STEP 5: 최종 검수 (GPT) ───────────────────────────────────
REVIEW_PROMPT = """아래 기사를 집필 지침 체크리스트 기준으로 검수하라.
미충족 항목이 있으면 즉시 수정해 완성본 기사만 출력하라.
추가 설명 없이 기사만 출력한다.

체크리스트:
□ 중제 3개 (볼드 처리, 구분선 없음)
□ 부제·중제만 읽어도 기사 방향 파악 가능
□ 각 중제 4문단 이상
□ 리드 2문장 이내
□ 대비 문장 2회 이상
□ 전문용어 쉬운 말 병기
□ 글쓰기 금지 표현 제거 (~하는 것이다, ~라는 점이다 등)
□ AI 티·특수문자 제거
□ 마지막 문장 구체적 실행 기준 제시
□ 공백 제외 1,800자 이상

[기사 초안]
{draft}
"""

def review_article(draft: str) -> str:
    log("STEP5 최종검수", "Claude 체크리스트 검수 중...")
    system = "당신은 신문 편집장이다. 집필 지침 체크리스트를 검수해 미충족 항목을 수정한다. 기사만 출력한다."
    prompt = REVIEW_PROMPT.format(draft=draft)
    final  = call_claude(prompt, system)
    log("STEP5 최종검수", f"완성 ({len(final.replace(' ',''))}자)")
    return final


# ── 저장 ──────────────────────────────────────────────────────
def save_source(article_id: str, body: str):
    ARTICLES_DIR.mkdir(exist_ok=True)
    path = ARTICLES_DIR / f"{article_id}_source.txt"
    path.write_text(body, encoding="utf-8")
    log("저장", str(path))


def save_md(article_id: str, media: str, content: str):
    ARTICLES_DIR.mkdir(exist_ok=True)
    path = ARTICLES_DIR / f"{article_id}_{media}.md"
    path.write_text(content, encoding="utf-8")
    log("저장", str(path))


# ── 미디어별 실행 ──────────────────────────────────────────────
def generate_for_media(item: dict, body: str, meta: dict,
                        fact: dict, media: str):
    if media == "enet":
        guideline   = load_guideline(ENET_GUIDELINE_FILE)
        media_label = "이넷뉴스"
    else:
        guideline   = load_guideline(SENIOR_GUIDELINE_FILE)
        media_label = "한국시니어신문"

    draft = write_article(body, meta, fact, guideline, media_label)
    final = review_article(draft)
    save_md(item["id"], media, final)


# ── 메인 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DailyK 심층기사 생성기")
    parser.add_argument("--id",    required=True,
                        help="data.json 기사 ID")
    parser.add_argument("--media", required=True,
                        choices=["enet", "senior", "both"],
                        help="생성 대상 매체")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  DailyK Writer  ID={args.id}  매체={args.media}")
    print(f"{'='*55}\n")

    data = load_data()
    item = find_item(data, args.id)
    log("시작", item.get("title", "")[:60])

    url = item.get("link", "")
    if not url:
        print("[오류] 원문 URL 없음. 중단.")
        sys.exit(1)

    # STEP 1
    try:
        body = fetch_full_text(url)
    except RuntimeError as e:
        print(f"\n[경고] {e}")
        sys.exit(1)

    # 원문 저장
    save_source(item["id"], body)

    # STEP 2
    meta = analyze_structure(body)

    # STEP 3
    fact = verify_facts(body, meta)
    if fact.get("confidence", 100) < 70:
        print(f"\n[주의] 팩트 신뢰도 {fact['confidence']}% — 검토 후 사용 권장.")
        for issue in fact.get("issues", []):
            print(f"  - {issue}")

    # STEP 4-5
    medias = ["enet", "senior"] if args.media == "both" else [args.media]
    for m in medias:
        generate_for_media(item, body, meta, fact, m)

    print(f"\n{'='*55}")
    print(f"  완료! articles/ 폴더를 확인하세요.")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
