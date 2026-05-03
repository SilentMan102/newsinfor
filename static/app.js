// ═══════════════════════════════════════════════════════════════════
// app.js — Vietnamese Government News Aggregator
// ═══════════════════════════════════════════════════════════════════

// ── State ──────────────────────────────────────────────────────────
let allItems = [], filtered = [], currentCat = 'all', currentLang = 'all';
let query = '', pageSize = 40, page = 1;
let lastExtractResult = null, serverOnline = false;

// ── Boot ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  if (location.protocol === 'file:') { showBanner(); showOfflineState(); return; }
  renderSkeletons(10);
  serverOnline = await checkServer();
  if (!serverOnline) { showBanner(); showOfflineState(); return; }
  fetchNews();
  loadCustomSources();
});

// ── Server Health Check ────────────────────────────────────────────
async function checkServer() {
  try {
    const d = await apiGet('/api/status');
    updateAIPill(d.ai_status);
    if (d.cache) {
      document.getElementById('stat-total').textContent = d.cache.total_items || 0;
      document.getElementById('stat-vi').textContent    = d.cache.vi_items    || 0;
      document.getElementById('stat-en').textContent    = d.cache.en_items    || 0;
    }
    return true;
  } catch {
    updateAIPill('offline');
    return false;
  }
}

function updateAIPill(status) {
  const pill = document.getElementById('ai-pill');
  const map = {
    enabled:      ['🤖 AI bật',          'pill-on'],
    disabled:     ['⚠️ Không có key',    'pill-off'],
    invalid_key:  ['❌ API key sai',      'pill-err'],
    rate_limited: ['⏳ Rate limited',     'pill-off'],
    error:        ['❌ Lỗi AI',           'pill-err'],
    offline:      ['❌ Server offline',  'pill-err'],
  };
  const [text, cls] = map[status] || ['⬤ …', 'pill-off'];
  pill.textContent = text;
  pill.className   = cls;
}

function showBanner() {
  document.getElementById('server-banner').style.display = 'flex';
}

function showOfflineState() {
  document.getElementById('news-list').innerHTML = `
    <div class="empty-state">
      <div class="big">🖥️</div>
      <p>Server chưa chạy hoặc bạn đang mở file HTML trực tiếp.<br/><br/>
      Mở <strong>Command Prompt</strong>:<br/><br/>
      <code>cd G:\\TARGER2026\\NewsPaper</code><br/>
      <code>python app.py</code><br/><br/>
      Sau đó mở trình duyệt tại:<br/>
      <code>http://localhost:5000</code></p>
    </div>`;
  document.getElementById('btn-extract').disabled = true;
}

// ── Language Toggle ────────────────────────────────────────────────
function setLang(lang, btn) {
  currentLang = lang;
  page = 1;
  ['all', 'vi', 'en'].forEach(l => {
    document.getElementById('lang-' + l).className =
      'lang-btn' + (l === lang ? ` active-${l}` : '');
  });
  const titles = { all: 'Tất cả tin tức', vi: 'Tin tức Tiếng Việt 🇻🇳', en: 'English News 🇬🇧' };
  document.getElementById('page-title').textContent = titles[lang];
  buildCategoryButtons();
  applyFilters();
}

// ── Fetch News ─────────────────────────────────────────────────────
async function fetchNews() {
  try {
    const d  = await apiGet('/api/news');
    allItems = d.items || [];
    document.getElementById('updated-at').textContent = 'Cập nhật: ' + formatDate(d.updated_at);
    const vi = allItems.filter(i => i.lang === 'vi' || !i.lang).length;
    const en = allItems.filter(i => i.lang === 'en').length;
    document.getElementById('stat-total').textContent = allItems.length;
    document.getElementById('stat-vi').textContent    = vi;
    document.getElementById('stat-en').textContent    = en;
    buildCategoryButtons();
    applyFilters();
  } catch(e) {
    document.getElementById('news-list').innerHTML =
      `<div class="empty-state"><div class="big">⚠️</div>
       <p>Lỗi tải dữ liệu:<br/><code>${esc(e.message)}</code></p></div>`;
  }
}

async function forceRefresh() {
  if (!serverOnline) return;
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true; btn.textContent = '…';
  renderSkeletons(10);
  try {
    await apiPost('/api/refresh');
    await fetchNews();
    await checkServer();
  } catch(e) {
    alert('Lỗi cập nhật: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '↻ Cập nhật';
  }
}

// ── Custom Sources ─────────────────────────────────────────────────
async function loadCustomSources() {
  try {
    const sources = await apiGet('/api/custom-sources');
    const el = document.getElementById('custom-src-list');
    if (!sources.length) {
      el.innerHTML = '<span style="font-size:.72rem;color:var(--muted);padding:.2rem .75rem;display:block">Chưa có nguồn</span>';
      return;
    }
    el.innerHTML = sources.map(s => `
      <div class="custom-src">
        <span>🌐</span>
        <span class="src-name" title="${esc(s.url)}">${esc(s.name || s.url)}</span>
        <span class="lang-tag ${s.lang === 'en' ? 'lang-en' : 'lang-vi'}">${(s.lang || 'vi').toUpperCase()}</span>
        <button onclick="deleteCustomSource('${esc(s.url)}')" title="Xóa">✕</button>
      </div>`).join('');
  } catch {}
}

async function deleteCustomSource(url) {
  await apiPost('/api/custom-sources/delete', { url });
  loadCustomSources();
  forceRefresh();
}

// ── Universal Extractor ────────────────────────────────────────────
async function doExtract() {
  if (!serverOnline) { setExtractStatus('⛔ Server chưa kết nối', '#f08080'); return; }

  let url = document.getElementById('extract-url').value
              .trim().replace(/[\u200B-\u200D\uFEFF\u00A0]/g, '');

  if (!url)                       { setExtractStatus('⚠️ Vui lòng nhập URL', '#e8a838'); return; }
  if (!url.startsWith('http'))    { url = 'https://' + url; document.getElementById('extract-url').value = url; }
  try { new URL(url); } catch    { setExtractStatus('⚠️ URL không hợp lệ. Ví dụ: https://moh.gov.vn', '#f08080'); return; }

  const btn = document.getElementById('btn-extract');
  btn.disabled = true; btn.textContent = 'Đang trích xuất…';
  document.getElementById('btn-save').style.display = 'none';
  setExtractStatus('🔄 Đang tải trang và phân tích…', 'var(--muted)');
  lastExtractResult = null;

  try {
    const cat  = document.getElementById('extract-cat').value;
    const lang = document.getElementById('extract-lang').value;
    const data = await apiPost('/api/extract', { url, category: cat, lang: lang || undefined });

    if (data.error) { setExtractStatus('❌ ' + data.error, '#f08080'); return; }
    if (!data.items || !data.items.length) {
      setExtractStatus('⚠️ Không tìm thấy bài viết. Thử URL trang danh mục tin tức.', '#e8a838');
      return;
    }

    lastExtractResult = data;
    const langLabel = data.lang === 'en' ? '🇬🇧 English' : '🇻🇳 Tiếng Việt';
    setExtractStatus(
      `✅ Tìm thấy <strong>${data.extracted}</strong> bài từ <em>${esc(data.site_name)}</em>
       <span class="lang-tag ${data.lang==='en'?'lang-en':'lang-vi'}" style="margin-left:4px">${langLabel}</span>
       <span style="color:var(--muted)"> — ${data.candidates_found} liên kết</span>`,
      'var(--green)'
    );
    showExtractPreview(data, cat);
    document.getElementById('btn-save').style.display = 'inline-block';

  } catch(e) {
    let msg = e.message || 'Lỗi không xác định';
    if (/pattern|Failed to fetch|NetworkError|fetch/i.test(msg))
      msg = 'Không thể kết nối server. Đảm bảo <code>python app.py</code> đang chạy.';
    else if (/JSON|SyntaxError/i.test(msg))
      msg = 'Server trả về phản hồi không hợp lệ. Kiểm tra terminal Flask.';
    setExtractStatus('❌ ' + msg, '#f08080');
  } finally {
    btn.disabled = false; btn.textContent = 'Trích xuất';
  }
}

async function doSave() {
  if (!lastExtractResult) return;
  const url  = document.getElementById('extract-url').value.trim();
  const cat  = document.getElementById('extract-cat').value;
  const lang = document.getElementById('extract-lang').value || lastExtractResult.lang || 'vi';
  const btn  = document.getElementById('btn-save');
  btn.disabled = true; btn.textContent = 'Đang lưu…';
  try {
    const data = await apiPost('/api/extract', { url, category: cat, lang, save: true });
    if (data.saved) {
      setExtractStatus('💾 Đã lưu nguồn! Tự động cập nhật mỗi 6 giờ.', 'var(--green)');
      btn.style.display = 'none';
      loadCustomSources();
      const newItems = data.items.map(h => ({
        title: h.title, link: h.link,
        source: data.site_name, category: cat, lang, icon: '🌐'
      }));
      allItems = [...newItems, ...allItems];
      buildCategoryButtons();
      applyFilters();
      const vi = allItems.filter(i => i.lang === 'vi' || !i.lang).length;
      const en = allItems.filter(i => i.lang === 'en').length;
      document.getElementById('stat-total').textContent = allItems.length;
      document.getElementById('stat-vi').textContent    = vi;
      document.getElementById('stat-en').textContent    = en;
    }
  } catch(e) {
    setExtractStatus('❌ Lỗi lưu: ' + e.message, '#f08080');
  } finally {
    btn.disabled = false; btn.textContent = '＋ Lưu nguồn';
  }
}

function showExtractPreview(data, cat) {
  const lang    = data.lang || 'vi';
  const preview = data.items.map(h => ({
    title: h.title, link: h.link,
    source: data.site_name, category: cat, lang, icon: '🌐', _new: true
  }));
  document.getElementById('news-list').innerHTML =
    `<div class="section-label">── Kết quả từ ${esc(data.site_name)}
     (${preview.length} bài · ${lang === 'en' ? '🇬🇧 English' : '🇻🇳 Tiếng Việt'}) ──</div>` +
    preview.map(cardHTML).join('');
  document.getElementById('item-count').textContent = preview.length + ' bài trích xuất';
}

function setExtractStatus(msg, color) {
  const el = document.getElementById('extract-status');
  el.innerHTML = msg; el.style.color = color;
}

// ── Filters & Search ───────────────────────────────────────────────
function selectCategory(cat, btn) {
  currentCat = cat; page = 1;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function onSearch() {
  query = document.getElementById('search').value.toLowerCase();
  page  = 1;
  applyFilters();
}

function applyFilters() {
  filtered = allItems.filter(item => {
    const langOk = currentLang === 'all' || (item.lang || 'vi') === currentLang;
    const catOk  = currentCat  === 'all' || item.category === currentCat;
    const qOk    = !query ||
                   item.title.toLowerCase().includes(query) ||
                   item.source.toLowerCase().includes(query);
    return langOk && catOk && qOk;
  });
  document.getElementById('item-count').textContent = filtered.length + ' bài viết';
  renderCards(filtered.slice(0, page * pageSize));
  document.getElementById('load-more-wrap').style.display =
    filtered.length > page * pageSize ? 'block' : 'none';
}

function loadMore() {
  page++;
  renderCards(filtered.slice(0, page * pageSize));
  document.getElementById('load-more-wrap').style.display =
    filtered.length > page * pageSize ? 'block' : 'none';
}

// ── Rendering ──────────────────────────────────────────────────────
function cardHTML(item, i = 0) {
  const isEn = (item.lang || 'vi') === 'en';
  return `
    <div class="news-card${isEn ? ' card-en' : ''}" style="animation-delay:${Math.min(i,20)*18}ms">
      <span class="card-icon">${item.icon || '📰'}</span>
      <div class="card-body">
        <a class="card-title" href="${esc(item.link)}" target="_blank" rel="noopener">
          ${esc(item.title)}
        </a>
        <div class="card-meta">
          <span class="badge ${isEn ? 'badge-cat-en' : 'badge-cat'}">${esc(item.category)}</span>
          ${item._new ? '<span class="badge badge-new">Mới</span>' : ''}
          <span class="lang-tag ${isEn ? 'lang-en' : 'lang-vi'}">${isEn ? 'EN' : 'VI'}</span>
          <span class="meta-source">${esc(item.source)}</span>
        </div>
      </div>
    </div>`;
}

function renderCards(items) {
  const list = document.getElementById('news-list');
  if (!items.length) {
    list.innerHTML = '<div class="empty-state"><div class="big">🔍</div><p>Không tìm thấy kết quả.</p></div>';
    return;
  }
  list.innerHTML = items.map(cardHTML).join('');
}

function buildCategoryButtons() {
  const visible = currentLang === 'all'
    ? allItems
    : allItems.filter(i => (i.lang || 'vi') === currentLang);

  const counts = {};
  visible.forEach(i => { counts[i.category] = (counts[i.category] || 0) + 1; });

  document.getElementById('count-all').textContent = visible.length;

  const catList = document.getElementById('cat-list');
  catList.querySelectorAll('[data-cat]:not([data-cat="all"])').forEach(b => b.remove());

  Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([cat, count]) => {
    const btn = document.createElement('button');
    btn.className   = 'cat-btn';
    btn.dataset.cat = cat;
    btn.innerHTML   = `${catIcon(cat)} ${cat} <span class="count">${count}</span>`;
    btn.onclick     = () => selectCategory(cat, btn);
    catList.appendChild(btn);
  });
}

function renderSkeletons(n) {
  document.getElementById('news-list').innerHTML = Array(n).fill(0).map(() => `
    <div class="skeleton-card">
      <div class="sk sk-icon"></div>
      <div class="sk-body">
        <div class="sk sk-line" style="width:${60 + Math.random() * 35}%"></div>
        <div class="sk sk-line short"></div>
      </div>
    </div>`).join('');
}

// ── API Helpers ────────────────────────────────────────────────────
async function apiGet(path) {
  const res = await fetch(path, { signal: AbortSignal.timeout(30000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(path, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
    signal:  AbortSignal.timeout(60000),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const d = await res.json(); msg = d.error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// ── Utilities ──────────────────────────────────────────────────────
function esc(s) {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString('vi-VN', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso.slice(0, 16).replace('T', ' '); }
}

function catIcon(cat) {
  const map = {
    'Chính phủ': '🏛️', 'Chính trị': '🇻🇳', 'Kinh tế': '📈',
    'Xã hội':    '👥', 'Pháp luật': '⚖️',  'Quốc tế': '🌏',
    'Y tế':      '🏥', 'Giáo dục':  '📚',  'Quốc phòng': '🎖️',
    'Tin tức':   '📰', 'Business':  '💼',  'Politics': '🏛️',
    'World':     '🌍', 'General':   '📰',
  };
  return map[cat] || '📰';
}

// ── Mobile bottom nav ──────────────────────────────────────────────
function mobileNav(tab, btn) {
  document.querySelectorAll('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  if (tab === 'home') {
    setLang('all', document.getElementById('lang-all'));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } else if (tab === 'vi') {
    setLang('vi', document.getElementById('lang-vi'));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } else if (tab === 'en') {
    setLang('en', document.getElementById('lang-en'));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } else if (tab === 'search') {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setTimeout(() => document.getElementById('search').focus(), 300);
  }
}