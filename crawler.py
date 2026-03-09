import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import json, os, re, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_T = datetime.now(timezone(timedelta(hours=9)))  # KST 기준

TODAY_PATTERNS = list({
    _T.strftime("%Y-%m-%d"), _T.strftime("%Y.%m.%d"), _T.strftime("%Y/%m/%d"),
    f"{_T.year}년 {_T.month}월 {_T.day}일", f"{_T.year}년 {_T.month:02d}월 {_T.day:02d}일",
    f"{_T.month:02d}-{_T.day:02d}", f"{_T.month:02d}.{_T.day:02d}",
    f"{_T.month}.{_T.day}", f"{_T.month}/{_T.day}", f"{_T.month:02d}/{_T.day:02d}",
    f"{_T.month}월 {_T.day}일", f"{_T.month:02d}월 {_T.day:02d}일",
})

# ──────────────────────────────────────────────────────────────
# 소스 목록
# ──────────────────────────────────────────────────────────────
GOV_SOURCES = [
    ("대통령실",           "",  "정부부처"),
    ("교육부",             "https://www.moe.go.kr/boardCnts/listRenew.do?boardID=294&m=0204&s=moe", "정부부처"),
    ("과학기술정보통신부",  "https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307", "정부부처"),
    ("국방부",             "https://www.mnd.go.kr/cop/kookbang/kookbangIlboList.do?handle=dema0003&siteId=mnd&id=mnd_020101000000", "정부부처"),
    ("보건복지부",         "https://www.mohw.go.kr/board.es?mid=a10503010100&bid=0027", "정부부처"),
    ("환경부",             "https://www.me.go.kr/home/web/board/list.do?boardMasterId=1", "정부부처"),
    ("성평등가족부",       "https://www.mogef.go.kr/nw/enw/nw_enw_s001.do", "정부부처"),
    ("국토교통부",         "https://www.molit.go.kr/USR/NEWS/m_71/lst.jsp", "정부부처"),
    ("해양수산부",         "https://www.mof.go.kr/doc/ko/selectDocList.do?menuSeq=971&bbsSeq=10", "정부부처"),
    ("한국전력공사",       "https://www.kepco.co.kr/home/media/newsroom/pr/boardList.do", "공기업"),
    ("한국수력원자력",     "https://www.khnp.co.kr/main/selectBbsNttList.do?bbsNo=71&key=2289", "공기업"),
    ("한국남부발전",       "https://www.kospo.co.kr/kospo/216/subview.do", "공기업"),
    ("한국서부발전",       "https://www.iwest.co.kr/iwest/1262/subview.do", "공기업"),
    ("한국석유공사",       "https://www.knoc.co.kr/sub11/sub11_1.jsp", "공기업"),
    ("한국지역난방공사",   "https://www.kdhc.co.kr/kdhc/bbs/B0000038/list.do?menuNo=200125", "공기업"),
    ("인천국제공항공사",   "https://www.airport.kr/co/ko/pr/press/pressList.do", "공기업"),
    ("한국도로공사",       "https://www.ex.co.kr/site/com/pageProcess.do", "공기업"),
    ("한국조폐공사",       "https://www.komsco.com/kor/article/bodo", "공기업"),
    ("한국마사회",         "https://www.kra.co.kr/board/pr/skr0221.do", "공기업"),
    ("한전KDN",            "https://www.kdn.com/board.kdn?mid=a10111010000&bid=0018", "공기업"),
    ("국민체육진흥공단",   "https://www.kspo.or.kr/kspo/frt/bbs/type01/commonSelectBoardList.do?bbsId=BBSMSTR_000000000021", "공기업"),
    ("영화진흥위원회",     "https://www.kofic.or.kr/kofic/business/noti/findNewsList.do", "공기업"),
    ("한국문화예술위원회", "https://www.arko.or.kr/board/list/4002", "공기업"),
    ("기술보증기금",       "https://www.kibo.or.kr/main/board/boardType05.do", "공기업"),
    ("근로복지공단",       "https://www.comwel.or.kr/comwel/noti/pres.jsp", "공기업"),
    ("국민건강보험공단",   "https://www.nhis.or.kr/nhis/together/wbhaea01600m01.do", "공기업"),
    ("한국가스안전공사",   "https://www.kgs.or.kr/kgs/agc/board.do", "공기업"),
    ("한국전기안전공사",   "https://www.kesco.or.kr/bbs/selectPageListBbs.do?bbs_code=MKB00002", "공기업"),
    ("한국관광공사",       "https://knto.or.kr/pressRelease", "공기업"),
    ("한국환경공단",       "https://www.keco.or.kr/web/lay1/bbs/S1T109C110/A/19/list.do", "공기업"),
    ("국립공원공단",       "https://www.knps.or.kr/front/portal/open/pnewsList.do?pnewsGrpCd=PNE02&menuNo=8000319", "공기업"),
    ("한국국토정보공사",   "https://www.lx.or.kr/kor/bbs/BBSMSTR_000000000005/lst.do", "공기업"),
    ("한국재해예방안전보건공단", "https://kosha.or.kr/notification/release/press-release", "공기업"),
    ("한국산업인력공단",   "https://www.hrdkorea.or.kr/3/1/1", "공기업"),
    ("한국소비자원",       "https://www.kca.go.kr/home/sub.do?menukey=4002", "공기업"),
    ("한국원자력안전기술원", "https://www.kins.re.kr/kinsNews", "공기업"),
]

COMPANY_SOURCES = [
    ("삼성전자",    "https://news.samsung.com/kr/category/%ED%94%84%EB%A0%88%EC%8A%A4%EC%84%BC%ED%84%B0/%EB%B3%B4%EB%8F%84%EC%9E%90%EB%A3%8C"),
    ("LG전자",      "https://live.lge.co.kr/news/press-release/"),
    ("LG",          "https://www.lg.co.kr/media/release"),
    ("LG생활건강",  "https://www.lghnh.com/news/press/list.jsp"),
    ("LG유플러스",  "https://news.lguplus.com/category/%ed%94%84%eb%a0%88%ec%8a%a4%ec%84%bc%ed%84%b0/%eb%b3%b4%eb%8f%84%ec%9e%90%eb%a3%8c"),
    ("LG화학",      "https://www.lgchem.com/company/information-center/press-release"),
    ("LG CNS",      "https://www.lgcns.com/kr/newsroom/press.page_1"),
    ("LG이노텍",    "https://www.lginnotek.com/news/press.do"),
    ("LG디스플레이","https://www.lgdisplay.com/kor/company/media-center/latest-news"),
    ("SK텔레콤",    "https://news.sktelecom.com/category/%ed%94%84%eb%a0%88%ec%8a%a4%ec%84%bc%ed%84%b0/%eb%b3%b4%eb%8f%84%ec%9e%90%eb%a3%8c"),
    ("SK하이닉스",  "https://news.skhynix.co.kr/category/press/"),
    ("SK",          "https://sk.com/ko/media/news.jsp"),
    ("SK에코플랜트","https://news.skecoplant.com/category/sk-ecoplant"),
    ("SK바이오사이언스", "https://www.skbioscience.com/kr/news/news_01"),
    ("현대자동차",  "https://www.hyundaimotorgroup.com/ko/news/newsMain"),
    ("현대모비스",  "https://www.mobis.com/kr/aboutus/press.do"),
    ("현대건설",    "https://www.hdec.kr/kr/company/press_list.aspx"),
    ("HD현대",      "https://www.hd.com/kr/newsroom/media-hub/press/list"),
    ("HD현대중공업","https://www.hhi.co.kr/kr/media-hub/press-release"),
    ("현대제철",    "https://moment.hyundai-steel.com/moment-list?searchValue=50006"),
    ("롯데그룹",    "https://www.lotte.co.kr/pr/newsList.do"),
    ("롯데건설",    "https://www.lottecon.co.kr/medias/notice_list"),
    ("롯데칠성음료","https://company.lottechilsung.co.kr/kor/company/news/list.do"),
    ("롯데글로벌로지스", "https://www.lotteglogis.com/mobile/company/pr/list?type=PR"),
    ("CJ",          "https://cjnews.cj.net/category/press-center/"),
    ("CJ제일제당",  "https://www.cj.co.kr/kr/newsroom/pressreleases"),
    ("CJ올리브영",  "https://corp.oliveyoung.com/ko/news"),
    ("GS리테일",    "http://www.gsretail.com/gsretail/ko/media/news-report"),
    ("GS건설",      "https://www.gs.co.kr/ko/news"),
    ("한화",        "https://www.hanwha.co.kr/newsroom/index.do"),
    ("신세계그룹",  "https://www.shinsegaegroupnewsroom.com/category/press-release/"),
    ("포스코",      "http://newsroom.posco.com/"),
    ("두산에너빌리티","https://www.doosanenerbility.com/kr/about/news_board_list"),
    ("두산그룹",    "https://www.doosannewsroom.com/"),
    ("KB금융그룹",  "https://www.kbfg.com/kor/pr/press/list.htm"),
    ("신한금융지주","https://www.shinhanfs.com"),
    ("하나은행",    "https://www.hanabank.com"),
    ("우리은행",    "https://spot.wooribank.com/pot/Dream?withyou=BPPBC0036"),
    ("NH농협금융",  "https://www.nhfngroup.com/user/indexSub.do?codyMenuSeq=884083449&siteId=nhfngroup"),
    ("KT",          "https://corp.kt.com/html/promote/news/report_list.html"),
    ("KCC",         "https://www.kccworld.co.kr/media/news/list.do"),
    ("LS그룹",      "https://www.lsholdings.com/ko/media/news"),
    ("LX하우시스",  "https://www.lxhausys.co.kr/company/pr/news"),
    ("DL이앤씨",    "https://www.dlenc.co.kr/pr/InfoList.do"),
    ("DB손해보험",  "https://www.idbins.com/pc/bizxpress/contentTemplet/cmy/pr/news/list.jsp"),
    ("DB하이텍",    "https://dbhitek.com/kr/media/news/list"),
    ("BGF리테일",   "https://www.bgfretail.com/press/"),
    ("SPC삼립",     "https://spcsamlip.co.kr/press-release/"),
    ("농심",        "https://www.nongshim.com/promotion/notice/press"),
    ("오리온",      "https://www.orionworld.com/board/list/87"),
    ("하림",        "https://www.harim.com/main/?menu=52"),
    ("빙그레",      "https://www.binggrae.co.kr"),
    ("하이트진로",  "https://www.hitejinro.com"),
    ("코웨이",      "https://company.coway.com/newsroom/press"),
    ("아모레퍼시픽","https://www.apgroup.com/int/ko/news/news.html"),
    ("셀트리온",    "https://www.celltrion.com/ko-kr/company/media-center/press-release"),
    ("GC녹십자",    "https://www.gccorp.com/kor/pr/news"),
    ("대웅제약",    "https://www.daewoong.co.kr"),
    ("보령제약",    "https://www.boryung.com"),
    ("한미약품",    "https://www.hanmipharm.com"),
    ("종근당",      "https://www.ckdpharm.com/promotion/newsList.do"),
    ("KGC한국인삼공사","https://www.kgc.co.kr/media-center/kgc-notice/list.do"),
    ("쿠팡",        "https://news.coupang.com/archives/category/press/release/"),
    ("무신사",      "https://newsroom.musinsa.com/news/press"),
    ("우아한형제들","https://www.woowahan.com/newsroom/media?page=1"),
    ("넥슨",        "https://kr-newsroom.nexon.com/"),
    ("스타벅스코리아","https://www.starbucks.co.kr/footer/company/news_list.do"),
    ("GM코리아",    "https://news.gm-korea.co.kr/ko/home/newsroom.html"),
    ("미래에셋증권","https://www.miraeasset.com"),
    ("JB금융그룹",  "https://www.jbfg.com/ko/prcenter/press.do"),
    ("한국콜마",    "https://www.kolmar.co.kr/pr/news.php"),
    ("코오롱인더스트리","https://www.kolonindustries.com/kr/promote/news"),
    ("경동나비엔",  "https://www.navi-en.com"),
    ("넥센타이어",  "https://www.nexentire.com"),
    ("풀무원",      "https://www.pulmuone.com"),
    ("대상",        "https://www.daesang.com"),
    ("이마트",      "https://www.emart.com"),
    ("HDC현대산업개발","https://www.hdc-dvp.com/mobile/newsroom/list.do"),
    ("씨젠",        "https://www.seegene.com"),
    ("광동제약",    "https://www.kdpharm.com"),
    ("초록우산어린이재단","https://www.greenumbrella.or.kr"),
    ("바디프랜드",  "https://bodyfriend.co.kr"),
]

RSS_SOURCES = [
    ("뉴스와이어", "https://api.newswire.co.kr/rss/all", "rss", "RSS"),
]

# ──────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────
def make_id(title, source):
    return hashlib.sha256(f"{title}{source}".encode()).hexdigest()[:12]

def has_today(text):
    return any(p in text for p in TODAY_PATTERNS)

def is_korean(text):
    k = len(re.findall(r'[가-힣]', text))
    return len(text) > 0 and (k / len(text)) >= 0.1

def resolve_url(href, base):
    if not href or href.startswith("javascript") or href.strip() == "#":
        return None
    return urljoin(base, href)

def tokenize(text):
    text = re.sub(r'[^\가-힣a-zA-Z0-9]', ' ', text)
    return set(w for w in text.split() if len(w) > 1)

# ──────────────────────────────────────────────────────────────
# 크롤링
# ──────────────────────────────────────────────────────────────
def classify_error(err):
    e = err.lower()
    if "timed out" in e or "timeout" in e:      return "timeout"
    if "max retries" in e or "connection aborted" in e or "oserror" in e: return "blocked"
    return "parse"

def scrape_site(name, url, source_type, source_cat):
    status = {"name": name, "url": url, "type": source_type, "cat": source_cat,
              "count": 0, "detected": 0, "success": False, "error": None, "error_type": None}
    if not url:
        status["error"] = "URL 없음"; status["error_type"] = "no_url"
        return [], status
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()

        results, seen = [], set()

        def add(title, href):
            resolved = resolve_url(href, url)
            kr = len(re.findall(r'[가-힣]', title))
            if resolved and 15 < len(title) < 150 and kr >= 3 and title not in seen:
                seen.add(title)
                results.append({
                    "id": make_id(title, name), "title": title, "link": resolved,
                    "source": name, "source_type": source_type, "source_cat": source_cat,
                    "collected_at": _T.isoformat(timespec='minutes'),
                })

        for date_node in soup.find_all(string=lambda t: t and has_today(str(t))):
            node = date_node.parent
            for _ in range(7):
                if node is None: break
                for a in node.find_all("a", href=True):
                    add(a.get_text(strip=True), a["href"])
                if results: break
                node = node.parent
            if len(results) >= 5: break

        if not results:
            for row in soup.find_all(["li", "tr", "article", "div"], limit=100):
                if not has_today(row.get_text()): continue
                for a in row.find_all("a", href=True):
                    add(a.get_text(strip=True), a["href"])
                if len(results) >= 5: break

        status["success"] = True
        status["detected"] = len(results)
        status["count"] = min(len(results), 5)
        status["error_type"] = "no_articles" if not results else None
        return results[:5], status
    except Exception as e:
        err = str(e)
        status["error"] = err[:60]; status["error_type"] = classify_error(err)
        return [], status

def fetch_rss(name, url, source_type="rss", source_cat="RSS"):
    status = {"name": name, "url": url, "type": source_type, "cat": source_cat,
              "count": 0, "detected": 0, "success": False, "error": None, "error_type": None}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "xml")
        results = []
        for item in soup.find_all("item"):
            title = item.find("title")
            link = item.find("link")
            desc = item.find("description")
            if not title or not link: continue
            t = title.get_text(strip=True)
            l = link.get_text(strip=True)
            if not is_korean(t): continue
            summary = ""
            if desc:
                dh = BeautifulSoup(desc.get_text(strip=True), "html.parser")
                summary = re.sub(r'^.*?\)\s*--\s*', '', dh.get_text(strip=True)).strip()[:120]
            pub = item.find("pubDate")
            pub_date = None
            if pub:
                try:
                    pub_date = parsedate_to_datetime(pub.get_text(strip=True)).isoformat()
                except Exception:
                    pass
            results.append({
                "id": make_id(t, name), "title": t, "link": l,
                "source": name, "source_type": source_type, "source_cat": source_cat,
                "collected_at": _T.isoformat(timespec='minutes'),
                "published_at": pub_date,
                "_rss_summary": summary,
            })
        status["success"] = True
        status["detected"] = len(results)
        status["count"] = min(len(results), 30)
        status["error_type"] = "no_articles" if not results else None
        return results[:30], status
    except Exception as e:
        err = str(e)
        status["error"] = err[:60]; status["error_type"] = classify_error(err)
        return [], status

def crawl_all():
    all_tasks = []
    for name, url, cat in GOV_SOURCES:
        all_tasks.append(("site", name, url, "gov", cat))
    for name, url in COMPANY_SOURCES:
        all_tasks.append(("site", name, url, "company", "기업"))
    for name, url, stype, cat in RSS_SOURCES:
        all_tasks.append(("rss", name, url, stype, cat))

    items, sources = [], []
    total = len(all_tasks)

    def run(task):
        kind, name, url, stype, cat = task
        if kind == "rss":
            return fetch_rss(name, url, stype, cat)
        return scrape_site(name, url, stype, cat)

    with ThreadPoolExecutor(max_workers=20) as ex:
        fmap = {ex.submit(run, t): t for t in all_tasks}
        done = 0
        for f in as_completed(fmap):
            done += 1
            try:
                res, st = f.result()
                items.extend(res)
                sources.append(st)
                if res:
                    print(f"  [{done}/{total}] {st['name']}: {st['count']}건")
            except Exception as e:
                _, name, *_ = fmap[f]
                print(f"  [{done}/{total}] {name}: 오류")

    # 제목 중복 제거
    seen, unique = set(), []
    for item in items:
        if item["title"] not in seen:
            seen.add(item["title"])
            unique.append(item)
    return unique, sources

# ──────────────────────────────────────────────────────────────
# 중복 감지
# ──────────────────────────────────────────────────────────────
def detect_duplicates(items, threshold=0.40):
    n = len(items)
    assigned = {}
    clusters = []

    for i in range(n):
        if i in assigned: continue
        group = [i]
        for j in range(i + 1, n):
            if j in assigned: continue
            t1, t2 = tokenize(items[i]["title"]), tokenize(items[j]["title"])
            if not t1 or not t2: continue
            sim = len(t1 & t2) / len(t1 | t2)
            if sim >= threshold:
                group.append(j)
        if len(group) > 1:
            cid = f"c{len(clusters)+1}"
            common = tokenize(items[group[0]]["title"])
            for k in group[1:]:
                common &= tokenize(items[k]["title"])
            topic = " ".join(list(common)[:4]) or items[group[0]]["title"][:20]
            for k in group:
                assigned[k] = cid
            clusters.append({"id": cid, "topic": topic,
                             "item_ids": [items[k]["id"] for k in group],
                             "count": len(group)})

    for i, item in enumerate(items):
        item["duplicate_cluster"] = assigned.get(i)
        item["duplicate_suspected"] = i in assigned

    return items, clusters

# ──────────────────────────────────────────────────────────────
# Gemini 분류
# ──────────────────────────────────────────────────────────────
def parse_gemini_json(text):
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    return json.loads(m.group() if m else text)

def grade_and_categorize(items):
    if not GEMINI_API_KEY or not items:
        for item in items:
            item.setdefault("grade", "B"); item.setdefault("category", "기타")
            item.setdefault("reason", ""); item.setdefault("summary", "")
            item.setdefault("enetnews", True); item.setdefault("senior", False)
            item.setdefault("article_type", "report")
            item.setdefault("recommended_for", "enetnews")
        return items

    VALID_CATS = {"정부·공공","경제·금융","산업·기업","IT·과학","의료·건강","생활·소비","국제","기타"}
    BATCH = 20

    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        raw = ""
        try:
            lines = "\n".join(
                f"{i+1}. [{batch[i]['source']}/{batch[i]['source_cat']}] {batch[i]['title']}"
                for i in range(len(batch))
            )
            prompt = f"""다음 보도자료 목록을 분류하라. 반드시 JSON 배열만 출력하라.

[등급] 전체 60~70%를 A등급으로.
A: 주요 발표·출시·투자·계약·실적·정책·업계동향
B: 수상·인증·사회공헌·캠페인
C: 단순홍보·할인·경품

[카테고리] 정부·공공/경제·금융/산업·기업/IT·과학/의료·건강/생활·소비/국제/기타

[매체] enetnews=이넷뉴스(경제IT산업), senior=한국시니어신문(건강복지은퇴금융)
[유형] report=보도자료형 / analysis=분석확장형 / brief=단신형

[reason] 추상적 문구 금지. "AI 반도체 시장 선점 발표, 수출 파급력 높음" 처럼 편집 판단에 직접 도움이 되는 구체적 한 줄.

[응답 형식] 순수 JSON만, summary는 70~120자 한국어 요약문, reason은 편집 판단에 도움이 되는 구체적 한 줄:
[{{"no":1,"grade":"A","cat":"IT·과학","reason":"AI 반도체 시장 선점 전략 발표, 글로벌 수출 파급력 높음","summary":"삼성전자가 차세대 AI 반도체를 공개하며 HBM4 적용 로드맵을 발표했다. 올 하반기 양산 예정으로 글로벌 데이터센터 수요 대응이 기대된다.","enetnews":true,"senior":false,"type":"report"}}]

[목록]
{lines}"""
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=90)
            rj = resp.json()
            if "error" in rj:
                print(f"  Gemini 오류 {rj['error'].get('code')}: {rj['error'].get('message','')[:60]}")
                for item in batch: _default_fields(item)
                continue
            raw = rj["candidates"][0]["content"]["parts"][0]["text"].strip()
            grades = parse_gemini_json(raw)
            gmap = {g["no"]: g for g in grades}
            for i, item in enumerate(batch):
                g = gmap.get(i + 1, {})
                item["grade"] = g.get("grade", "B")
                item["category"] = g.get("cat", "기타") if g.get("cat") in VALID_CATS else "기타"
                item["reason"] = g.get("reason", "")
                item["summary"] = item.get("_rss_summary") or g.get("summary", "")
                item["enetnews"] = bool(g.get("enetnews", True))
                item["senior"] = bool(g.get("senior", False))
                item["article_type"] = g.get("type", "report")
                item["recommended_for"] = (
                    "both" if item["enetnews"] and item["senior"] else
                    "enetnews" if item["enetnews"] else
                    "senior" if item["senior"] else "none"
                )
                item.pop("_rss_summary", None)
            print(f"  Gemini 완료: {start+1}~{start+len(batch)}번")
        except Exception as e:
            print(f"  Gemini 오류: {e}")
            if raw: print(f"  응답: {raw[:80]}")
            for item in batch: _default_fields(item)
    return items

def _default_fields(item):
    item.setdefault("grade", "B"); item.setdefault("category", "기타")
    item.setdefault("reason", ""); item.setdefault("summary", item.pop("_rss_summary", ""))
    item.setdefault("enetnews", True); item.setdefault("senior", False)
    item.setdefault("article_type", "report"); item.setdefault("recommended_for", "enetnews")

# ──────────────────────────────────────────────────────────────
# 데이터 저장
# ──────────────────────────────────────────────────────────────
def save_data(items, clusters, sources):
    a = [i for i in items if i["grade"] == "A"]
    b = [i for i in items if i["grade"] == "B"]
    c = [i for i in items if i["grade"] == "C"]
    data = {
        "meta": {
            "updated_at": _T.isoformat(),
            "today": _T.strftime("%Y년 %m월 %d일"),
            "total": len(items),
            "a_count": len(a), "b_count": len(b), "c_count": len(c),
            "enetnews_count": sum(1 for i in items if i.get("enetnews")),
            "senior_count": sum(1 for i in items if i.get("senior")),
            "cluster_count": len(clusters),
            "source_success": sum(1 for s in sources if s["success"]),
            "source_fail": sum(1 for s in sources if not s["success"]),
            "total_detected": sum(s.get("detected", s["count"]) for s in sources),
            "total_reflected": sum(s["count"] for s in sources),
            "error_types": {
                "timeout":     sum(1 for s in sources if s.get("error_type") == "timeout"),
                "blocked":     sum(1 for s in sources if s.get("error_type") == "blocked"),
                "no_articles": sum(1 for s in sources if s.get("error_type") == "no_articles"),
                "parse":       sum(1 for s in sources if s.get("error_type") == "parse"),
                "no_url":      sum(1 for s in sources if s.get("error_type") == "no_url"),
            },
        },
        "items": items,
        "clusters": clusters,
        "sources": sources,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  data.json 저장 완료 ({len(items)}건)")

# ──────────────────────────────────────────────────────────────
# HTML 셸 생성
# ──────────────────────────────────────────────────────────────
def build_html():
    today = _T.strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>이넷뉴스 AI 보도자료 v2 — {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;900&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0a0a0a;--s:#111;--s2:#1a1a1a;--s3:#242424;--bd:#222;--bd2:#2e2e2e;--tx:#e8e8e8;--mu:#666;--di:#999;--ac:#ff3b30;--bl:#0a84ff;--gr:#30d158;--ye:#ffd60a;--or:#ff9f0a;--sidebar:220px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Noto Sans KR',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh}}
/* Header */
header{{position:fixed;top:0;left:0;right:0;z-index:200;background:rgba(10,10,10,.97);backdrop-filter:blur(12px);border-bottom:1px solid var(--bd);height:52px;display:flex;align-items:center;padding:0 20px;gap:16px}}
.logo{{font-size:17px;font-weight:900;white-space:nowrap}}.logo span{{color:var(--ac)}}
.hstats{{display:flex;gap:12px;flex:1;margin-left:20px}}
.hstat{{font-size:11px;color:var(--mu);white-space:nowrap}}
.hstat b{{color:var(--tx);font-weight:700}}
.hstat.hl-a b{{color:var(--ac)}}
.hstat.hl-e b{{color:var(--bl)}}
.hstat.hl-s b{{color:var(--gr)}}
.view-tabs{{display:flex;gap:4px;margin-left:auto}}
.vtab{{padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;background:var(--s2);color:var(--di);border:1px solid var(--bd);transition:all .15s}}
.vtab.active{{background:var(--ac);color:#fff;border-color:var(--ac)}}
.htime{{font-size:10px;color:var(--mu);white-space:nowrap}}
/* Layout */
.layout{{display:flex;margin-top:52px;min-height:calc(100vh - 52px)}}
/* Sidebar */
.sidebar{{width:var(--sidebar);min-width:var(--sidebar);background:var(--s);border-right:1px solid var(--bd);position:sticky;top:52px;height:calc(100vh - 52px);overflow-y:auto;padding:16px 0}}
.sb-section{{padding:0 0 12px;margin-bottom:4px;border-bottom:1px solid var(--bd)}}
.sb-title{{font-size:9px;font-weight:700;color:var(--mu);letter-spacing:1.5px;text-transform:uppercase;padding:8px 16px 6px}}
.sb-item{{display:flex;align-items:center;justify-content:space-between;padding:7px 16px;cursor:pointer;font-size:12px;color:var(--di);border-left:3px solid transparent;transition:all .1s}}
.sb-item:hover{{background:var(--s2);color:var(--tx)}}
.sb-item.active{{background:var(--s2);border-left-color:var(--ac);color:var(--tx);font-weight:600}}
.sb-badge{{font-size:9px;font-weight:700;background:var(--s3);color:var(--ac);padding:1px 5px;border-radius:8px;border:1px solid var(--bd2)}}
.sb-toggle{{display:flex;align-items:center;gap:8px;padding:7px 16px;cursor:pointer;font-size:12px;color:var(--di)}}
.sb-toggle input{{accent-color:var(--ac)}}
/* Main */
.main{{flex:1;padding:20px;min-width:0}}
.main-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}}
.main-title{{font-size:14px;font-weight:700}}
.main-count{{font-size:12px;color:var(--mu)}}
/* Grid */
.cards-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
/* Card */
.card{{background:var(--s);border:1px solid var(--bd);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:8px;transition:all .2s;position:relative}}
.card:hover{{border-color:var(--bd2);background:var(--s2);transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,0,0,.4)}}
.card.excluded{{opacity:.35}}
.card.is-candidate{{border-color:rgba(48,209,88,.35);background:rgba(48,209,88,.04)}}
.card-top{{display:flex;align-items:center;gap:5px;flex-wrap:wrap}}
.badge{{font-size:9px;font-weight:800;padding:2px 6px;border-radius:4px;white-space:nowrap}}
.badge-a{{background:rgba(255,59,48,.15);color:var(--ac);border:1px solid rgba(255,59,48,.3)}}
.badge-b{{background:rgba(10,132,255,.15);color:var(--bl);border:1px solid rgba(10,132,255,.3)}}
.badge-c{{background:rgba(100,100,100,.2);color:var(--mu);border:1px solid var(--bd)}}
.badge-cat{{background:var(--s3);color:var(--di);border:1px solid var(--bd2)}}
.badge-type{{background:rgba(255,159,10,.1);color:var(--or);border:1px solid rgba(255,159,10,.2)}}
.badge-dup{{background:rgba(255,214,10,.1);color:var(--ye);border:1px solid rgba(255,214,10,.2)}}
.badge-gov{{background:rgba(10,132,255,.1);color:var(--bl);border:1px solid rgba(10,132,255,.2)}}
.badge-pub{{background:rgba(48,209,88,.1);color:var(--gr);border:1px solid rgba(48,209,88,.2)}}
.badge-rss{{background:rgba(255,159,10,.1);color:var(--or);border:1px solid rgba(255,159,10,.2)}}
.card-title{{font-size:13px;font-weight:600;color:var(--tx);text-decoration:none;line-height:1.5;display:block}}
.card-title:hover{{color:var(--ac)}}
.card-source{{font-size:11px;color:var(--mu)}}
.card-summary{{font-size:11px;color:var(--di);line-height:1.6}}
.card-reason{{font-size:11px;color:var(--or);display:flex;align-items:center;gap:4px}}
.card-media{{display:flex;gap:5px}}
.media-tag{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;border:1px solid;cursor:pointer;transition:all .15s}}
.media-tag.enet{{color:var(--bl);border-color:rgba(10,132,255,.3);background:rgba(10,132,255,.08)}}
.media-tag.senior{{color:var(--gr);border-color:rgba(48,209,88,.3);background:rgba(48,209,88,.08)}}
.media-tag.enet.on{{background:var(--bl);color:#fff;border-color:var(--bl)}}
.media-tag.senior.on{{background:var(--gr);color:#fff;border-color:var(--gr)}}
.card-actions{{display:flex;gap:6px;margin-top:2px;flex-wrap:wrap}}
.btn{{font-size:10px;font-weight:700;padding:4px 8px;border-radius:5px;border:1px solid;cursor:pointer;transition:all .15s;background:transparent}}
.btn-link{{color:var(--di);border-color:var(--bd2)}}
.btn-link:hover{{color:var(--tx);border-color:var(--di)}}
.btn-cand{{color:var(--gr);border-color:rgba(48,209,88,.3)}}
.btn-cand:hover,.btn-cand.on{{background:var(--gr);color:#fff;border-color:var(--gr)}}
.btn-excl{{color:var(--mu);border-color:var(--bd)}}
.btn-excl:hover{{color:var(--ac);border-color:var(--ac)}}
.cluster-info{{font-size:10px;color:var(--ye);padding:4px 8px;background:rgba(255,214,10,.06);border-radius:5px;border:1px solid rgba(255,214,10,.15)}}
/* Status */
.stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.stat-box{{background:var(--s);border:1px solid var(--bd);border-radius:10px;padding:14px}}
.stat-label{{font-size:10px;color:var(--mu);margin-bottom:6px}}
.stat-val{{font-size:24px;font-weight:900}}
.stat-val.a{{color:var(--ac)}}
.stat-val.e{{color:var(--bl)}}
.stat-val.s{{color:var(--gr)}}
.source-table{{width:100%;border-collapse:collapse;font-size:12px}}
.source-table th{{padding:8px 10px;border-bottom:2px solid var(--bd);text-align:left;color:var(--mu);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px}}
.source-table td{{padding:7px 10px;border-bottom:1px solid var(--bd)}}
.source-table tr:hover td{{background:var(--s2)}}
.dot-ok{{color:var(--gr)}} .dot-fail{{color:var(--ac)}}
/* Empty */
.empty{{grid-column:1/-1;text-align:center;padding:60px;color:var(--mu);font-size:14px}}
.card-meta{{display:flex;align-items:center;justify-content:space-between;margin-top:2px}}
.card-time{{font-size:10px;color:var(--mu)}}
/* Scrollbar */
::-webkit-scrollbar{{width:4px}}::-webkit-scrollbar-thumb{{background:#333;border-radius:2px}}
/* Mobile */
@media(max-width:900px){{
  .sidebar{{display:none}}
  .cards-grid{{grid-template-columns:1fr}}
  .stat-grid{{grid-template-columns:repeat(2,1fr)}}
  .hstats{{display:none}}
}}
</style>
</head>
<body>
<header>
  <div class="logo">이넷<span>뉴스</span> AI <span style="font-size:11px;font-weight:400;color:var(--mu)">v2</span> <span style="font-size:9px;font-weight:600;color:var(--or);background:rgba(255,159,10,.12);border:1px solid rgba(255,159,10,.3);padding:1px 6px;border-radius:4px;margin-left:4px">내부 테스트</span></div>
  <div class="hstats" id="hstats"></div>
  <div class="view-tabs">
    <div class="vtab active" onclick="setView('list')">전체목록</div>
    <div class="vtab" onclick="setView('candidates')">기사화 후보</div>
    <div class="vtab" onclick="setView('status')">운영현황</div>
  </div>
  <div class="htime" id="htime"></div>
</header>
<div class="layout">
  <aside class="sidebar" id="sidebar"></aside>
  <main class="main" id="main"><div class="empty">데이터 로딩 중...</div></main>
</div>
<script src="app.js"></script>
</body>
</html>"""

# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────
def main():
    print(f"=== 이넷뉴스 AI 보도자료 v2 ===")
    print(f"크롤링 시작: {_T.strftime('%Y년 %m월 %d일 %H:%M')}")
    print(f"소스: 정부·공기업 {len(GOV_SOURCES)}개 + 기업 {len(COMPANY_SOURCES)}개 + RSS {len(RSS_SOURCES)}개")

    items, sources = crawl_all()
    print(f"\n수집: {len(items)}건")

    if items:
        items, clusters = detect_duplicates(items)
        print(f"중복 클러스터: {len(clusters)}개")
        print("Gemini 분류 중...")
        items = grade_and_categorize(items)
        a = sum(1 for i in items if i["grade"] == "A")
        print(f"A등급: {a}건 / 전체: {len(items)}건")
    else:
        clusters = []
        print("오늘 수집된 기사가 없습니다.")

    save_data(items, clusters, sources)

    print("완료! data.json 생성")

if __name__ == "__main__":
    main()
