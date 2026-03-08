'use strict';

// ── 전역 상태 ──────────────────────────────────────────────
let DATA = null;
let VIEW = 'list'; // 'list' | 'candidates' | 'status'

const F = {
  grade: 'all',       // 'all' | 'A' | 'B' | 'C'
  cat: 'all',
  source_type: 'all', // 'all' | 'gov' | 'company' | 'rss'
  media: 'all',       // 'all' | 'enetnews' | 'senior' | 'both' | 'none'
  dup_only: false,
  time: 'all',        // 'all' | '24h' | '48h' | '7d'
};

// ── localStorage ─────────────────────────────────────────────
const LS = {
  get: k => { try { return JSON.parse(localStorage.getItem(k) || '{}'); } catch { return {}; } },
  set: (k, v) => localStorage.setItem(k, JSON.stringify(v)),
  candidates: () => LS.get('candidates'),
  excluded:   () => LS.get('excluded'),
  overrides:  () => LS.get('overrides'),
};

function toggleCandidate(id) {
  const c = LS.candidates();
  c[id] ? delete c[id] : (c[id] = true);
  LS.set('candidates', c);
  renderHeaderStats();
  refreshCard(id);
}

function toggleExclude(id) {
  const e = LS.excluded();
  e[id] ? delete e[id] : (e[id] = true);
  LS.set('excluded', e);
  refreshCard(id);
}

function toggleMedia(id, key) {
  const o = LS.overrides();
  if (!o[id]) o[id] = {};
  o[id][key] = !getMediaState(id, key);
  LS.set('overrides', o);
  refreshCard(id);
}

function getMediaState(id, key) {
  const o = LS.overrides();
  if (o[id] && key in o[id]) return o[id][key];
  const item = DATA && DATA.items.find(i => i.id === id);
  return item ? !!item[key] : false;
}

function getRecommendedFor(item) {
  // recommended_for 필드 우선, 없으면 override·bool에서 계산
  const o = LS.overrides();
  const ov = o[item.id];
  if (ov && ('enetnews' in ov || 'senior' in ov)) {
    const e = 'enetnews' in ov ? ov.enetnews : !!item.enetnews;
    const s = 'senior'   in ov ? ov.senior   : !!item.senior;
    if (e && s) return 'both';
    if (e) return 'enetnews';
    if (s) return 'senior';
    return 'none';
  }
  // override 없으면 crawler 필드 사용
  return item.recommended_for || (item.enetnews && item.senior ? 'both' :
    item.enetnews ? 'enetnews' : item.senior ? 'senior' : 'none');
}

// ── 시간 처리 ─────────────────────────────────────────────────
function parseItemTime(item) {
  // published_at(RSS pubDate) 우선, 없으면 collected_at
  const raw = item.published_at || item.collected_at;
  if (!raw) return null;
  // HH:MM 포맷(구버전 호환)
  if (/^\d{2}:\d{2}$/.test(raw)) {
    const d = new Date();
    const [h, m] = raw.split(':').map(Number);
    d.setHours(h, m, 0, 0);
    return d;
  }
  return new Date(raw);
}

function timeAgo(item) {
  const d = parseItemTime(item);
  if (!d || isNaN(d)) return '';
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1)  return '방금';
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}시간 전`;
  return `${Math.floor(hrs / 24)}일 전`;
}

function withinHours(item, hours) {
  const d = parseItemTime(item);
  if (!d || isNaN(d)) return true; // 시간 불명이면 포함
  return (Date.now() - d.getTime()) < hours * 3_600_000;
}

// ── 필터 적용 ──────────────────────────────────────────────────
function applyFilters(items) {
  const excl = LS.excluded();
  return items.filter(item => {
    if (excl[item.id]) return false;
    if (F.grade !== 'all' && item.grade !== F.grade) return false;
    if (F.cat !== 'all' && item.category !== F.cat) return false;
    if (F.source_type !== 'all' && item.source_type !== F.source_type) return false;
    if (F.media !== 'all') {
      const rf = getRecommendedFor(item);
      if (F.media === 'enetnews' && rf !== 'enetnews' && rf !== 'both') return false;
      if (F.media === 'senior'   && rf !== 'senior'   && rf !== 'both') return false;
      if (F.media === 'both'     && rf !== 'both') return false;
      if (F.media === 'none'     && rf !== 'none') return false;
    }
    if (F.dup_only && !item.duplicate_suspected) return false;
    if (F.time !== 'all') {
      const hours = F.time === '24h' ? 24 : F.time === '48h' ? 48 : 168;
      if (!withinHours(item, hours)) return false;
    }
    return true;
  });
}

// ── 정렬 ──────────────────────────────────────────────────────
function sortItems(items) {
  const gOrder = { A: 0, B: 1, C: 2 };
  return [...items].sort((a, b) => {
    const gDiff = (gOrder[a.grade] ?? 1) - (gOrder[b.grade] ?? 1);
    if (gDiff !== 0) return gDiff;
    const ta = parseItemTime(a), tb = parseItemTime(b);
    if (ta && tb && !isNaN(ta) && !isNaN(tb)) return tb - ta;
    return 0;
  });
}

// ── 사이드바 렌더링 ────────────────────────────────────────────
const CATS = ['정부·공공','경제·금융','산업·기업','IT·과학','의료·건강','생활·소비','국제','기타'];

function renderSidebar(allItems) {
  const el = document.getElementById('sidebar');
  if (!el) return;

  const visible = applyFilters(allItems);

  // 집계
  const gradeN = { all: visible.length, A: 0, B: 0, C: 0 };
  const catN = {};
  const stN = { all: visible.length, gov: 0, company: 0, rss: 0 };
  const mediaN = { all: visible.length, enetnews: 0, senior: 0, both: 0, none: 0 };

  visible.forEach(i => {
    gradeN[i.grade] = (gradeN[i.grade] || 0) + 1;
    catN[i.category] = (catN[i.category] || 0) + 1;
    stN[i.source_type] = (stN[i.source_type] || 0) + 1;
    const rf = getRecommendedFor(i);
    mediaN[rf] = (mediaN[rf] || 0) + 1;
  });

  const sbItem = (key, fKey, label, count, active) =>
    `<div class="sb-item ${active ? 'active' : ''}" onclick="setFilter('${fKey}','${key}')">
      ${label} <span class="sb-badge">${count}</span>
    </div>`;

  el.innerHTML = `
    <div class="sb-section">
      <div class="sb-title">등급</div>
      ${[['all','전체',gradeN.all],['A','A등급',gradeN.A||0],['B','B등급',gradeN.B||0],['C','C등급',gradeN.C||0]]
        .map(([k,l,n]) => sbItem(k,'grade',l,n,F.grade===k)).join('')}
    </div>
    <div class="sb-section">
      <div class="sb-title">카테고리</div>
      ${sbItem('all','cat','전체',visible.length,F.cat==='all')}
      ${CATS.filter(c => catN[c]).map(c => sbItem(c,'cat',c,catN[c],F.cat===c)).join('')}
    </div>
    <div class="sb-section">
      <div class="sb-title">소스</div>
      ${[['all','전체',stN.all],['gov','정부·공기업',stN.gov||0],['company','기업',stN.company||0],['rss','RSS',stN.rss||0]]
        .map(([k,l,n]) => sbItem(k,'source_type',l,n,F.source_type===k)).join('')}
    </div>
    <div class="sb-section">
      <div class="sb-title">추천 매체</div>
      ${[['all','전체',mediaN.all],['enetnews','이넷뉴스',mediaN.enetnews||0],['senior','시니어신문',mediaN.senior||0],['both','공통',mediaN.both||0],['none','미지정',mediaN.none||0]]
        .map(([k,l,n]) => sbItem(k,'media',l,n,F.media===k)).join('')}
    </div>
    <div class="sb-section">
      <div class="sb-title">기간</div>
      ${[['all','전체'],['24h','24시간'],['48h','48시간'],['7d','7일']]
        .map(([k,l]) => `<div class="sb-item ${F.time===k?'active':''}" onclick="setFilter('time','${k}')">${l}</div>`).join('')}
    </div>
    <div class="sb-section">
      <label class="sb-toggle">
        <input type="checkbox" ${F.dup_only?'checked':''} onchange="setFilter('dup_only',this.checked)">
        중복 의심만
      </label>
    </div>
  `;
}

// ── 카드 렌더링 ────────────────────────────────────────────────
function gradeClass(g) { return g === 'A' ? 'badge-a' : g === 'B' ? 'badge-b' : 'badge-c'; }

function sourceBadge(item) {
  if (item.source_type === 'gov') {
    return item.source_cat === '정부부처'
      ? '<span class="badge badge-gov">정부</span>'
      : '<span class="badge badge-pub">공기업</span>';
  }
  if (item.source_type === 'rss') return '<span class="badge badge-rss">RSS</span>';
  return '';
}

function typeBadge(t) {
  const labels = { report: '보도자료', analysis: '분석형', brief: '단신' };
  return `<span class="badge badge-type">${labels[t] || t || ''}</span>`;
}

function renderCardHTML(item) {
  const cands = LS.candidates();
  const excl  = LS.excluded();
  const isCandidate = !!cands[item.id];
  const isExcluded  = !!excl[item.id];
  const _ov    = (LS.overrides()[item.id] || {});
  const enetOn = 'enetnews' in _ov ? !!_ov.enetnews : !!item.enetnews;
  const senOn  = 'senior'   in _ov ? !!_ov.senior   : !!item.senior;
  const ago    = timeAgo(item);

  let clusterHTML = '';
  if (item.duplicate_suspected && item.duplicate_cluster && DATA) {
    const cl = DATA.clusters.find(c => c.id === item.duplicate_cluster);
    if (cl) clusterHTML = `<div class="cluster-info">🔗 중복 의심 · ${cl.count}건 유사 — ${cl.topic}</div>`;
  }

  return `<div class="card${isCandidate?' is-candidate':''}${isExcluded?' excluded':''}" data-id="${item.id}">
  <div class="card-top">
    <span class="badge ${gradeClass(item.grade)}">${item.grade}</span>
    <span class="badge badge-cat">${item.category || '기타'}</span>
    ${sourceBadge(item)}
    ${typeBadge(item.article_type)}
    ${item.duplicate_suspected ? '<span class="badge badge-dup">중복</span>' : ''}
  </div>
  <a href="${item.link}" target="_blank" rel="noopener" class="card-title">${item.title}</a>
  ${item.summary ? `<div class="card-summary">${item.summary}</div>` : ''}
  ${item.reason  ? `<div class="card-reason">📌 ${item.reason}</div>` : ''}
  <div class="card-meta">
    <span class="card-source">${item.source}</span>
    ${ago ? `<span class="card-time">${ago}</span>` : ''}
  </div>
  <div class="card-media">
    <span class="media-tag enet${enetOn?' on':''}" onclick="toggleMedia('${item.id}','enetnews')">이넷뉴스</span>
    <span class="media-tag senior${senOn?' on':''}" onclick="toggleMedia('${item.id}','senior')">시니어신문</span>
  </div>
  ${clusterHTML}
  <div class="card-actions">
    <button class="btn btn-cand${isCandidate?' on':''}" onclick="toggleCandidate('${item.id}')">
      ${isCandidate ? '★ 후보 등록됨' : '☆ 기사화 후보'}
    </button>
    <button class="btn btn-excl" onclick="toggleExclude('${item.id}')">
      ${isExcluded ? '↩ 복원' : '제외'}
    </button>
  </div>
</div>`;
}

function renderCards(items) {
  const main = document.getElementById('main');
  if (!items || !items.length) {
    main.innerHTML = '<div class="empty">표시할 항목이 없습니다.</div>';
    return;
  }
  const title = VIEW === 'candidates' ? '기사화 후보' : '전체 목록';
  main.innerHTML = `
    <div class="main-header">
      <div class="main-title">${title}</div>
      <div class="main-count">${items.length}건</div>
    </div>
    <div class="cards-grid">${items.map(renderCardHTML).join('')}</div>`;
}

function refreshCard(id) {
  if (!DATA) return;
  const item = DATA.items.find(i => i.id === id);
  if (!item) return;
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (!el) return;
  el.outerHTML = renderCardHTML(item);
}

// ── 운영현황 뷰 ────────────────────────────────────────────────
function renderStatus() {
  const main = document.getElementById('main');
  const m = DATA.meta;
  const sources = DATA.sources || [];
  const ok   = sources.filter(s => s.success).sort((a,b) => b.count - a.count);
  const fail = sources.filter(s => !s.success);

  const et = m.error_types || {};
  main.innerHTML = `
    <div class="main-header">
      <div class="main-title">운영 현황</div>
      <div class="main-count">${m.today} <span style="font-size:10px;color:var(--mu);margin-left:8px">내부 운영 테스트 v1</span></div>
    </div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-label">총 감지 건수</div><div class="stat-val">${m.total_detected ?? '-'}</div></div>
      <div class="stat-box"><div class="stat-label">최종 반영 건수</div><div class="stat-val" style="color:var(--gr)">${m.total_reflected ?? m.total}</div></div>
      <div class="stat-box"><div class="stat-label">A등급</div><div class="stat-val a">${m.a_count}</div></div>
      <div class="stat-box"><div class="stat-label">B / C 등급</div><div class="stat-val" style="color:var(--bl)">${m.b_count} <span style="font-size:14px;color:var(--mu)">/ ${m.c_count}</span></div></div>
      <div class="stat-box"><div class="stat-label">이넷뉴스 추천</div><div class="stat-val e">${m.enetnews_count}</div></div>
      <div class="stat-box"><div class="stat-label">시니어 추천</div><div class="stat-val s">${m.senior_count}</div></div>
      <div class="stat-box"><div class="stat-label">중복 클러스터</div><div class="stat-val" style="color:var(--ye)">${m.cluster_count}</div></div>
      <div class="stat-box"><div class="stat-label">수집 성공 소스</div><div class="stat-val" style="color:var(--gr)">${m.source_success}</div></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:20px">
      ${[['타임아웃','timeout','--or'],['접근차단','blocked','--ac'],['기사없음','no_articles','--mu'],['파싱실패','parse','--ye'],['URL없음','no_url','--di']]
        .map(([l,k,c]) => `<div class="stat-box" style="padding:10px">
          <div class="stat-label">${l}</div>
          <div style="font-size:20px;font-weight:800;color:var(${c})">${et[k]??0}</div>
        </div>`).join('')}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <div style="font-size:11px;color:var(--gr);margin-bottom:8px;font-weight:700">✓ 수집 성공 (${ok.length})</div>
        <table class="source-table">
          <thead><tr><th>소스</th><th>유형</th><th>감지</th><th>반영</th></tr></thead>
          <tbody>${ok.map(s => {
            const det = s.detected ?? s.count;
            const diff = det > s.count ? `<span style="color:var(--mu);font-size:10px"> (${det})</span>` : '';
            return `<tr><td>${s.name}</td><td style="color:var(--mu)">${s.cat}</td><td style="color:var(--di)">${det}</td><td style="color:var(--gr)">${s.count}${diff}</td></tr>`;
          }).join('')}</tbody>
        </table>
      </div>
      <div>
        <div style="font-size:11px;color:var(--ac);margin-bottom:8px;font-weight:700">✗ 수집 실패 (${fail.length})</div>
        <table class="source-table">
          <thead><tr><th>소스</th><th>사유</th><th>상세</th></tr></thead>
          <tbody>${fail.map(s => {
            const typeLabel = {timeout:'타임아웃',blocked:'접근차단',parse:'파싱실패',no_url:'URL없음',no_articles:'기사없음'}[s.error_type] || s.error_type || '-';
            const typeColor = {timeout:'--or',blocked:'--ac',parse:'--ye',no_url:'--di',no_articles:'--mu'}[s.error_type] || '--mu';
            return `<tr><td>${s.name}</td><td><span style="color:var(${typeColor});font-size:10px;font-weight:700">${typeLabel}</span></td><td style="color:var(--mu);font-size:10px">${(s.error||'').substring(0,40)}</td></tr>`;
          }).join('')}</tbody>
        </table>
      </div>
    </div>`;
}

// ── 헤더 통계 ──────────────────────────────────────────────────
function renderHeaderStats() {
  if (!DATA) return;
  const m = DATA.meta;
  const candCount = Object.keys(LS.candidates()).length;
  document.getElementById('hstats').innerHTML = `
    <span class="hstat">전체 <b>${m.total}</b></span>
    <span class="hstat hl-a">A등급 <b>${m.a_count}</b></span>
    <span class="hstat hl-e">이넷뉴스 <b>${m.enetnews_count}</b></span>
    <span class="hstat hl-s">시니어 <b>${m.senior_count}</b></span>
    <span class="hstat">후보 <b>${candCount}</b></span>`;
  document.getElementById('htime').textContent = m.today;
}

// ── 뷰/필터 제어 ──────────────────────────────────────────────
function setView(v) {
  VIEW = v;
  document.querySelectorAll('.vtab').forEach((el, i) => {
    el.classList.toggle('active', ['list','candidates','status'][i] === v);
  });
  render();
}

function setFilter(key, val) {
  F[key] = val;
  render();
}

// ── 메인 렌더 ──────────────────────────────────────────────────
function render() {
  if (!DATA) return;
  renderHeaderStats();

  if (VIEW === 'status') {
    document.getElementById('sidebar').innerHTML = '';
    renderStatus();
    return;
  }

  let items = sortItems(applyFilters(DATA.items));

  if (VIEW === 'candidates') {
    const c = LS.candidates();
    items = items.filter(i => c[i.id]);
  }

  renderSidebar(DATA.items);
  renderCards(items);
}

// ── 초기 로드 ──────────────────────────────────────────────────
async function init() {
  try {
    const res = await fetch('data.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
    render();
  } catch (e) {
    document.getElementById('main').innerHTML =
      `<div class="empty">data.json 로드 실패: ${e.message}<br><small style="color:var(--mu)">crawler.py를 먼저 실행해 주세요.</small></div>`;
  }
}

init();
