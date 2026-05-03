# ─── app.py ───────────────────────────────────────────────────────────────────
from flask import Flask, jsonify, send_from_directory, request
import feedparser, json, os, re
import requests as req
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
import anthropic, logging

from config import ANTHROPIC_API_KEY, CACHE_DURATION_HOURS, PORT, DEBUG

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# ─── Preset RSS sources ───────────────────────────────────────────────────────
SOURCES = [
    # Vietnamese sources
    {"id":"bcp_tintuc",   "name":"Báo Chính phủ – Tin tức",   "category":"Chính phủ", "lang":"vi", "url":"https://baochinhphu.vn/rss/tin-tuc.rss",   "icon":"🏛️"},
    {"id":"bcp_kinhte",   "name":"Báo Chính phủ – Kinh tế",   "category":"Kinh tế",   "lang":"vi", "url":"https://baochinhphu.vn/rss/kinh-te.rss",   "icon":"📈"},
    {"id":"bcp_xahoi",    "name":"Báo Chính phủ – Xã hội",    "category":"Xã hội",    "lang":"vi", "url":"https://baochinhphu.vn/rss/xa-hoi.rss",    "icon":"🤝"},
    {"id":"bcp_phapluat", "name":"Báo Chính phủ – Pháp luật", "category":"Pháp luật", "lang":"vi", "url":"https://baochinhphu.vn/rss/phap-luat.rss", "icon":"⚖️"},
    {"id":"bcp_quocte",   "name":"Báo Chính phủ – Quốc tế",   "category":"Quốc tế",   "lang":"vi", "url":"https://baochinhphu.vn/rss/quoc-te.rss",   "icon":"🌏"},
    {"id":"nd_chinhtri",  "name":"Nhân Dân – Chính trị",       "category":"Chính trị", "lang":"vi", "url":"https://nhandan.vn/rss/chinhtri.rss",      "icon":"🇻🇳"},
    {"id":"nd_kinhte",    "name":"Nhân Dân – Kinh tế",         "category":"Kinh tế",   "lang":"vi", "url":"https://nhandan.vn/rss/kinhte.rss",        "icon":"📊"},
    {"id":"nd_xahoi",     "name":"Nhân Dân – Xã hội",          "category":"Xã hội",    "lang":"vi", "url":"https://nhandan.vn/rss/xahoi.rss",         "icon":"👥"},
    {"id":"nd_thegioi",   "name":"Nhân Dân – Thế giới",        "category":"Quốc tế",   "lang":"vi", "url":"https://nhandan.vn/rss/thegioi.rss",       "icon":"🌐"},
    {"id":"qd_tintuc",    "name":"Quân Đội Nhân Dân",          "category":"Chính trị", "lang":"vi", "url":"https://www.qdnd.vn/rss/tin-tuc.rss",      "icon":"🎖️"},
    # English sources
    {"id":"vne_news",     "name":"VnExpress – News",           "category":"General",   "lang":"en", "url":"https://e.vnexpress.net/rss/news.rss",     "icon":"📰"},
    {"id":"vne_business", "name":"VnExpress – Business",       "category":"Business",  "lang":"en", "url":"https://e.vnexpress.net/rss/business.rss", "icon":"💼"},
    {"id":"vne_world",    "name":"VnExpress – World",          "category":"World",     "lang":"en", "url":"https://e.vnexpress.net/rss/world.rss",    "icon":"🌍"},
    {"id":"vne_politics", "name":"VnExpress – Politics",       "category":"Politics",  "lang":"en", "url":"https://e.vnexpress.net/rss/politics.rss", "icon":"🏛️"},
    {"id":"vntimes_en",   "name":"Vietnam Times",              "category":"General",   "lang":"en", "url":"https://vietnamtimes.org.vn/feed",         "icon":"🗞️"},
    {"id":"hanoitimes",   "name":"Hanoi Times",                "category":"General",   "lang":"en", "url":"https://hanoitimes.vn/feed",               "icon":"🏙️"},
]

CACHE_FILE          = "cache.json"
CUSTOM_SOURCES_FILE = "custom_sources.json"
HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Custom sources ───────────────────────────────────────────────────────────
def load_custom_sources():
    if os.path.exists(CUSTOM_SOURCES_FILE):
        with open(CUSTOM_SOURCES_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_custom_sources(sources):
    with open(CUSTOM_SOURCES_FILE,"w",encoding="utf-8") as f: json.dump(sources,f,ensure_ascii=False,indent=2)

# ─── Scraping helpers ─────────────────────────────────────────────────────────
def fetch_html(url):
    resp = req.get(url, headers=HEADERS, timeout=15)
    resp.encoding = resp.apparent_encoding
    return resp.text

def detect_site_name(html, url):
    soup = BeautifulSoup(html,"html.parser")
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"): return og["content"].strip()
    t = soup.find("title")
    if t: return t.get_text(strip=True).split("|")[0].split("-")[0].strip()
    return urlparse(url).netloc

def detect_lang(html, url):
    """Detect language from HTML meta tags or domain."""
    soup = BeautifulSoup(html,"html.parser")
    # Check <html lang="...">
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        lang = html_tag["lang"].lower()
        if lang.startswith("vi"): return "vi"
        if lang.startswith("en"): return "en"
    # Check og:locale
    og = soup.find("meta", property="og:locale")
    if og and og.get("content"):
        loc = og["content"].lower()
        if "vi" in loc: return "vi"
        if "en" in loc: return "en"
    # Fallback: check domain
    domain = urlparse(url).netloc.lower()
    en_hints = ["e.vnexpress", "vietnamtimes", "hanoitimes", "vietnamnews", "tuoitrenews", "theinvestor"]
    if any(h in domain for h in en_hints): return "en"
    return "vi"  # default to Vietnamese

def extract_candidate_links(html, base_url):
    soup = BeautifulSoup(html,"html.parser")
    for tag in soup(["script","style","nav","footer","header","aside","form","button","noscript","iframe"]):
        tag.decompose()
    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    candidates, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = re.sub(r"\s+"," ",a.get_text(strip=True))
        href  = a["href"].strip()
        if len(title)<12 or len(title)>350: continue
        if title in seen: continue
        if href.startswith(("mailto:","tel:","javascript:","#")): continue
        if href.startswith("/"): href = base_domain + href
        if not href.startswith("http"): href = urljoin(base_url, href)
        seen.add(title)
        candidates.append({"title":title,"link":href})
    return candidates[:300]

# ─── AI filter ────────────────────────────────────────────────────────────────
def heuristic_filter(candidates, source_url):
    parsed = urlparse(source_url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    skip   = re.compile(r"(đăng nhập|đăng ký|liên hệ|giới thiệu|trang chủ|xem thêm|tất cả|chuyên mục|login|register|contact|about|home|more|tag|facebook|youtube|zalo|twitter|instagram|sitemap|rss|print|share|quảng cáo)",re.I)
    return [c for c in candidates if not skip.search(c["title"]) and len(c["title"])>=25 and c["link"].startswith(base)][:50]

def ai_filter_headlines(candidates, source_url, site_name):
    if not candidates: return []
    if not ANTHROPIC_API_KEY:
        logger.info("No API key → heuristic filter")
        return heuristic_filter(candidates, source_url)
    lines  = "\n".join(f"{i+1}. {c['title']} || {c['link']}" for i,c in enumerate(candidates))
    prompt = f"""Analyze links from: {source_url} (site: {site_name})
Identify ONLY actual news article headlines. EXCLUDE navigation, categories, ads, buttons, social links, footer.
Return ONLY raw JSON array: [{{"title":"...","link":"..."}}]. No markdown, no explanation.
Links:
{lines}"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp   = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=4096, messages=[{"role":"user","content":prompt}])
        raw    = re.sub(r"^```[a-z]*\n?","",resp.content[0].text.strip())
        raw    = re.sub(r"\n?```$","",raw)
        result = json.loads(raw)
        logger.info(f"AI: {len(candidates)} → {len(result)} headlines")
        return result
    except anthropic.AuthenticationError:
        logger.warning("⚠️  Invalid API key → heuristic"); return heuristic_filter(candidates,source_url)
    except anthropic.RateLimitError:
        logger.warning("⚠️  Rate limit → heuristic");      return heuristic_filter(candidates,source_url)
    except anthropic.APIConnectionError:
        logger.warning("⚠️  API unreachable → heuristic"); return heuristic_filter(candidates,source_url)
    except Exception as e:
        logger.warning(f"⚠️  AI error ({e}) → heuristic"); return heuristic_filter(candidates,source_url)

# ─── Cache ────────────────────────────────────────────────────────────────────
def scrape_source(cs):
    html       = fetch_html(cs["url"])
    lang       = cs.get("lang") or detect_lang(html, cs["url"])
    site_name  = cs.get("name") or detect_site_name(html, cs["url"])
    candidates = extract_candidate_links(html, cs["url"])
    headlines  = ai_filter_headlines(candidates, cs["url"], site_name)
    return [{"title":h["title"],"link":h["link"],"source":site_name,"category":cs.get("category","Tin tức"),"lang":lang,"icon":cs.get("icon","🌐"),"published":None} for h in headlines]

def build_cache():
    logger.info("═══ Building cache ═══")
    all_items = []
    for src in SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            count = 0
            for entry in feed.entries[:15]:
                t = entry.get("title","").strip()
                l = entry.get("link","").strip()
                if t and l:
                    all_items.append({"title":t,"link":l,"source":src["name"],"category":src["category"],"lang":src.get("lang","vi"),"icon":src["icon"],"published":None})
                    count += 1
            logger.info(f"RSS ✓ [{src.get('lang','vi').upper()}] {src['name']} — {count} items")
        except Exception as e:
            logger.warning(f"RSS ✗ {src['name']}: {e}")
    for cs in load_custom_sources():
        try:
            items = scrape_source(cs)
            all_items.extend(items)
            logger.info(f"WEB ✓ [{cs.get('lang','?').upper()}] {cs.get('name',cs['url'])} — {len(items)} items")
        except Exception as e:
            logger.warning(f"WEB ✗ {cs.get('url')}: {e}")
    cache = {"updated_at":datetime.now().isoformat(),"total":len(all_items),"items":all_items}
    with open(CACHE_FILE,"w",encoding="utf-8") as f: json.dump(cache,f,ensure_ascii=False,indent=2)
    logger.info(f"═══ Cache built: {len(all_items)} total ═══")
    return cache

def load_or_refresh_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE,"r",encoding="utf-8") as f: cache=json.load(f)
        if datetime.now()-datetime.fromisoformat(cache["updated_at"])<timedelta(hours=CACHE_DURATION_HOURS): return cache
    return build_cache()

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/api/news")
def get_news():
    cache    = load_or_refresh_cache()
    category = request.args.get("category","").strip()
    lang     = request.args.get("lang","").strip()      # "vi" | "en" | "" (all)
    items    = cache["items"]
    if category and category != "all":
        items = [i for i in items if i["category"]==category]
    if lang and lang != "all":
        items = [i for i in items if i.get("lang","vi")==lang]
    return jsonify({"updated_at":cache["updated_at"],"total":len(items),"items":items})

@app.route("/api/extract", methods=["POST"])
def extract_from_url():
    body = request.get_json() or {}
    url  = (body.get("url") or "").strip()
    if not url: return jsonify({"error":"URL is required"}),400
    if not url.startswith("http"): url = "https://" + url
    try: urlparse(url).netloc
    except: return jsonify({"error":"Invalid URL format"}),400
    try:
        html       = fetch_html(url)
        site_name  = body.get("name") or detect_site_name(html,url)
        lang       = body.get("lang") or detect_lang(html,url)
        candidates = extract_candidate_links(html,url)
        headlines  = ai_filter_headlines(candidates,url,site_name)
        result     = {"url":url,"site_name":site_name,"lang":lang,"extracted":len(headlines),"candidates_found":len(candidates),"items":headlines}
        if body.get("save"):
            custom = load_custom_sources()
            if not any(c["url"]==url for c in custom):
                custom.append({"url":url,"name":site_name,"category":body.get("category","Tin tức"),"lang":lang,"icon":"🌐"})
                save_custom_sources(custom)
            result["saved"] = True
        return jsonify(result)
    except req.exceptions.ConnectionError:
        return jsonify({"error":f"Cannot connect to {url}"}),502
    except req.exceptions.Timeout:
        return jsonify({"error":"Request timed out (15s)"}),504
    except Exception as e:
        logger.exception("Extract error")
        return jsonify({"error":str(e)}),500

@app.route("/api/custom-sources", methods=["GET"])
def get_custom_sources(): return jsonify(load_custom_sources())

@app.route("/api/custom-sources/delete", methods=["POST"])
def delete_custom_source():
    url    = (request.get_json() or {}).get("url","")
    custom = [c for c in load_custom_sources() if c["url"]!=url]
    save_custom_sources(custom)
    return jsonify({"status":"ok","remaining":len(custom)})

@app.route("/api/refresh", methods=["POST"])
def manual_refresh():
    cache = build_cache()
    return jsonify({"status":"ok","updated_at":cache["updated_at"],"total":cache["total"]})

@app.route("/api/status")
def status():
    cache_info = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE,"r",encoding="utf-8") as f: c=json.load(f)
        age = datetime.now()-datetime.fromisoformat(c["updated_at"])
        vi_count = sum(1 for i in c["items"] if i.get("lang","vi")=="vi")
        en_count = sum(1 for i in c["items"] if i.get("lang")=="en")
        cache_info = {"updated_at":c["updated_at"],"total_items":c["total"],"vi_items":vi_count,"en_items":en_count,"age_seconds":int(age.total_seconds())}
    ai_status = "disabled"
    if ANTHROPIC_API_KEY:
        try:
            anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(model="claude-haiku-4-5-20251001",max_tokens=5,messages=[{"role":"user","content":"hi"}])
            ai_status = "enabled"
        except anthropic.AuthenticationError: ai_status = "invalid_key"
        except anthropic.RateLimitError:      ai_status = "rate_limited"
        except Exception:                     ai_status = "error"
    return jsonify({"status":"running","ai_status":ai_status,"ai_enabled":ai_status=="enabled","rss_sources":len(SOURCES),"vi_sources":sum(1 for s in SOURCES if s.get("lang")=="vi"),"en_sources":sum(1 for s in SOURCES if s.get("lang")=="en"),"custom_sources":len(load_custom_sources()),"cache":cache_info,"cache_duration_hours":CACHE_DURATION_HOURS})

@app.route("/api/categories")
def get_categories():
    cache = load_or_refresh_cache()
    lang  = request.args.get("lang","").strip()
    items = cache["items"]
    if lang and lang != "all":
        items = [i for i in items if i.get("lang","vi")==lang]
    return jsonify(sorted(set(i["category"] for i in items)))

@app.route("/")
def index(): return send_from_directory("static","index.html")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Source Manager API (full CRUD)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/sources/all", methods=["GET"])
def get_all_sources():
    custom = load_custom_sources()
    preset = [{"id":s["id"],"name":s["name"],"url":s["url"],"category":s["category"],"lang":s.get("lang","vi"),"icon":s.get("icon","📰"),"type":"preset","enabled":s.get("enabled",True)} for s in SOURCES]
    user   = [{"id":f"custom_{i}","name":c.get("name",c["url"]),"url":c["url"],"category":c.get("category","Tin tức"),"lang":c.get("lang","vi"),"icon":c.get("icon","🌐"),"type":"custom","enabled":c.get("enabled",True)} for i,c in enumerate(custom)]
    return jsonify({"preset":preset,"custom":user,"total":len(preset)+len(user)})

@app.route("/api/sources/preset/toggle", methods=["POST"])
def toggle_preset_source():
    body = request.get_json() or {}
    sid  = body.get("id","")
    for s in SOURCES:
        if s["id"] == sid:
            s["enabled"] = not s.get("enabled", True)
            return jsonify({"id":sid,"enabled":s["enabled"]})
    return jsonify({"error":"Source not found"}), 404

@app.route("/api/sources/preset/update", methods=["POST"])
def update_preset_source():
    body = request.get_json() or {}
    sid  = body.get("id","")
    for s in SOURCES:
        if s["id"] == sid:
            for f in ["lang","category","name"]:
                if f in body: s[f] = body[f]
            return jsonify({"status":"ok","source":s})
    return jsonify({"error":"Source not found"}), 404

@app.route("/api/sources/custom/add", methods=["POST"])
def add_custom_source():
    body = request.get_json() or {}
    url  = (body.get("url") or "").strip()
    if not url: return jsonify({"error":"URL required"}), 400
    if not url.startswith("http"): url = "https://" + url
    custom = load_custom_sources()
    if any(c["url"]==url for c in custom):
        return jsonify({"error":"Source already exists"}), 409
    new_src = {"url":url,"name":body.get("name",urlparse(url).netloc),"category":body.get("category","Tin tức"),"lang":body.get("lang","vi"),"icon":"🌐","enabled":True}
    custom.append(new_src)
    save_custom_sources(custom)
    return jsonify({"status":"ok","source":new_src})

@app.route("/api/sources/custom/update", methods=["POST"])
def update_custom_source():
    body   = request.get_json() or {}
    url    = (body.get("url") or "").strip()
    custom = load_custom_sources()
    for s in custom:
        if s["url"] == url:
            for f in ["name","category","lang","icon","enabled"]:
                if f in body: s[f] = body[f]
            save_custom_sources(custom)
            return jsonify({"status":"ok","source":s})
    return jsonify({"error":"Source not found"}), 404

@app.route("/api/sources/custom/delete", methods=["POST"])
def delete_custom_source_v2():
    url    = (request.get_json() or {}).get("url","")
    custom = [c for c in load_custom_sources() if c["url"] != url]
    save_custom_sources(custom)
    return jsonify({"status":"ok"})

@app.route("/sources")
def sources_page():
    return send_from_directory("static", "sources.html")


if __name__ == "__main__":
    logger.info(f"Starting on http://localhost:{PORT}")
    logger.info(f"AI: {'enabled' if ANTHROPIC_API_KEY else 'disabled (heuristic mode)'}")
    load_or_refresh_cache()
    app.run(debug=DEBUG, port=PORT)