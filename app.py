from flask import Flask, request, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import uuid
import io
import re
import threading
import tempfile
from datetime import datetime, date, timedelta
from PIL import Image
from pdf2image import convert_from_path

app = Flask(__name__)

# ─────────────────────────────────────────────
# ENV VARIABLES
# ─────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY")
BUCKET_NAME    = "katalog-images"

GEMINI_VISION_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
GEMINI_CHAT_URL   = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"

print("=" * 60)
print("katalog.ai starting up...")
print(f"  GEMINI_API_KEY : {'SET' if GEMINI_API_KEY else 'MISSING'}")
print(f"  SUPABASE_URL   : {SUPABASE_URL if SUPABASE_URL else 'MISSING'}")
print(f"  SUPABASE_KEY   : {'SET' if SUPABASE_KEY else 'MISSING'}")
print("=" * 60)


# ─────────────────────────────────────────────
# UPLOAD TOOL HTML
# ─────────────────────────────────────────────
UPLOAD_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>katalog.ai Upload</title>
<style>
body{font-family:monospace;background:#111;color:#eee;padding:40px;max-width:700px;margin:0 auto}
h1{color:#00ff88}
input,.file-input-wrapper{background:#222;border:1px solid #444;color:#eee;padding:8px;width:100%;margin:5px 0 15px 0;font-family:monospace;display:block;box-sizing:border-box}
.file-input-wrapper{padding:0;overflow:hidden}
.file-input-wrapper input[type=file]{border:none;margin:0;padding:10px;background:#1a1a1a;width:100%}
label{color:#aaa;font-size:13px}
button{background:#00ff88;color:#000;border:none;padding:15px;font-weight:bold;font-size:16px;cursor:pointer;width:100%;margin-top:10px;border-radius:4px}
button:disabled{background:#444;color:#888;cursor:not-allowed}
button.secondary{background:#0088ff;color:#fff;margin-top:6px}
#log{background:#000;padding:20px;margin-top:20px;min-height:100px;font-size:12px;line-height:1.8;white-space:pre-wrap;overflow:auto;max-height:500px;border-radius:4px}
#bar-wrap{background:#222;height:24px;margin-top:10px;display:none;border-radius:4px;overflow:hidden}
#fill{background:#00ff88;height:24px;width:0%;transition:width 0.3s;display:flex;align-items:center;justify-content:center;font-size:11px;color:#000;font-weight:bold}
.info{background:#222;padding:15px;margin:20px 0;border-left:3px solid #00ff88;font-size:13px}
</style>
</head>
<body>
<h1>katalog.ai</h1>
<div class="info">Pass 1: PDF to products. Pass 2: crop product images.</div>

<label>PDF File:</label>
<div class="file-input-wrapper"><input type="file" id="f" accept=".pdf"></div>
<label>Store:</label>
<input type="text" id="s" placeholder="Lidl">
<label>Valid From (YYYY-MM-DD):</label>
<input type="text" id="vf" placeholder="2026-03-02">
<label>Valid Until (YYYY-MM-DD, empty = +14 days):</label>
<input type="text" id="vu" placeholder="2026-03-15">

<button id="btn" onclick="startUpload()">Process PDF</button>
<button class="secondary" onclick="cropOnly()">Crop Existing (Pass 2 only)</button>

<div id="bar-wrap"><div id="fill">0%</div></div>
<div id="log">Ready.</div>

<script>
var pollTimer = null;

function log(msg) {
  var el = document.getElementById("log");
  el.textContent += msg + "\\n";
  el.scrollTop = el.scrollHeight;
}

function setProgress(pct, label) {
  document.getElementById("bar-wrap").style.display = "block";
  var fill = document.getElementById("fill");
  fill.style.width = pct + "%";
  fill.textContent = label || pct + "%";
}

function startUpload() {
  var f  = document.getElementById("f").files[0];
  var s  = document.getElementById("s").value.trim();
  var vf = document.getElementById("vf").value.trim();
  var vu = document.getElementById("vu").value.trim();

  if (!f)  { alert("Select a PDF"); return; }
  if (!s)  { alert("Enter store name"); return; }
  if (!vf) { alert("Enter valid from date"); return; }

  if (!vu) {
    var d = new Date(vf + "T12:00:00");
    d.setDate(d.getDate() + 14);
    vu = d.toISOString().split("T")[0];
    document.getElementById("vu").value = vu;
  }

  document.getElementById("btn").disabled = true;
  document.getElementById("btn").textContent = "Uploading...";
  document.getElementById("log").textContent = "";

  log("Uploading: " + f.name);
  log("Store: " + s + " | " + vf + " to " + vu);

  var fd = new FormData();
  fd.append("file", f);
  fd.append("store", s);
  fd.append("valid_from", vf);
  fd.append("valid_until", vu);

  fetch("/upload", { method: "POST", body: fd })
    .then(function(r) {
      if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
      return r.json();
    })
    .then(function(data) {
      if (data.error) { log("ERROR: " + data.error); resetBtn(); return; }
      log("Job: " + data.job_id + " | Pages: " + data.total_pages);
      document.getElementById("btn").textContent = "Processing...";
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(function() { poll(data.job_id); }, 3000);
    })
    .catch(function(e) { log("ERROR: " + e.message); resetBtn(); });
}

function poll(jobId) {
  fetch("/status/" + jobId)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var pct = d.total_pages > 0 ? Math.round((d.current_page / d.total_pages) * 100) : 0;
      setProgress(pct);
      document.getElementById("btn").textContent = "Page " + d.current_page + "/" + d.total_pages + " (" + (d.total_products||0) + " products)";

      if (d.status === "cropping") {
        document.getElementById("btn").textContent = "Cropping... " + (d.cropped_products || 0) + " done";
        setProgress(100, "Cropping...");
      }
      if (d.status === "done") {
        clearInterval(pollTimer);
        log("PASS 1 DONE: " + d.total_products + " products from " + d.total_pages + " pages");
        log("Starting Pass 2...");
        startCrop(d.catalogue_name, jobId);
      }
      if (d.status === "crop_done") {
        clearInterval(pollTimer);
        log("PASS 2 DONE: " + d.cropped_products + " product images cropped");
        log("ALL DONE!");
        setProgress(100, "ALL DONE!");
        resetBtn("Process Another");
      }
      if (d.status === "error") {
        clearInterval(pollTimer);
        log("Error. Job ID: " + jobId);
        resetBtn();
      }
    })
    .catch(function(e) { console.log("Poll error:", e); });
}

function startCrop(catalogueName, jobId) {
  fetch("/crop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalogue_name: catalogueName, job_id: jobId })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { log("Crop error: " + d.error); resetBtn(); return; }
    log("Cropping: " + catalogueName);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function() { poll(jobId); }, 3000);
  })
  .catch(function(e) { log("Crop error: " + e.message); resetBtn(); });
}

function cropOnly() {
  var cn = prompt("Enter catalogue_name:");
  if (!cn) return;
  document.getElementById("log").textContent = "";
  log("Pass 2 for: " + cn);
  fetch("/crop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalogue_name: cn })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { log("ERROR: " + d.error); return; }
    log("Job: " + d.job_id);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function() { poll(d.job_id); }, 3000);
  })
  .catch(function(e) { log("ERROR: " + e.message); });
}

function resetBtn(label) {
  var btn = document.getElementById("btn");
  btn.disabled = false;
  btn.textContent = label || "Process PDF";
}

document.getElementById("f") && document.getElementById("f").addEventListener("change", function() {
  if (this.files[0]) document.getElementById("log").textContent = "Selected: " + this.files[0].name;
});
</script>
</body>
</html>'''


# ─────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────
def supa_headers(extra=None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    if extra:
        h.update(extra)
    return h


# ─────────────────────────────────────────────
# JOB TRACKING
# ─────────────────────────────────────────────
def create_job(store, catalogue_name, total_pages, valid_from, valid_until):
    job_id = str(uuid.uuid4())[:8]
    record = {
        "job_id": job_id, "store": store, "catalogue_name": catalogue_name,
        "status": "processing", "total_pages": total_pages, "current_page": 0,
        "total_products": 0, "cropped_products": 0,
        "valid_from": valid_from, "valid_until": valid_until,
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/jobs",
                          headers=supa_headers({"Prefer": "return=minimal"}),
                          json=record, timeout=10)
        if r.status_code in [200, 201]:
            return job_id
        print(f"create_job failed: {r.status_code} {r.text}")
        return None
    except Exception as e:
        print(f"create_job exception: {e}")
        return None


def update_job(job_id, **kwargs):
    try:
        requests.patch(f"{SUPABASE_URL}/rest/v1/jobs?job_id=eq.{job_id}",
                       headers=supa_headers({"Prefer": "return=minimal"}),
                       json=kwargs, timeout=10)
    except:
        pass


def get_job(job_id):
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/jobs?job_id=eq.{job_id}&select=*",
                         headers=supa_headers(), timeout=10)
        data = r.json()
        return data[0] if data else None
    except:
        return None


# ─────────────────────────────────────────────
# STORAGE IMAGE UPLOAD
# ─────────────────────────────────────────────
def upload_image(image_bytes, storage_path):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{storage_path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true"
    }
    try:
        r = requests.put(url, headers=headers, data=image_bytes, timeout=30)
        if r.status_code in [200, 201]:
            return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{storage_path}"
        print(f"Upload failed [{r.status_code}]: {storage_path}")
        return None
    except Exception as e:
        print(f"Upload exception: {e}")
        return None


def build_storage_path(store, catalogue_name, page_num, product_index=None):
    store_clean = re.sub(r'[^a-z0-9_]', '_', store.lower())
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', catalogue_name)
    date_folder = date_match.group(1) if date_match else datetime.utcnow().strftime("%Y-%m-%d")
    if product_index is None:
        return f"{store_clean}/{date_folder}/page_{str(page_num).zfill(3)}.jpg"
    return f"{store_clean}/{date_folder}/products/page_{str(page_num).zfill(3)}_product_{str(product_index).zfill(3)}.jpg"


# ─────────────────────────────────────────────
# GEMINI VISION (PDF processing)
# ─────────────────────────────────────────────
def call_gemini_vision(image_base64, prompt, timeout=60):
    payload = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}},
            {"text": prompt}
        ]}],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        r = requests.post(f"{GEMINI_VISION_URL}?key={GEMINI_API_KEY}",
                          json=payload, timeout=timeout)
        if r.status_code != 200:
            print(f"Gemini vision HTTP {r.status_code}")
            return None
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates or candidates[0].get("finishReason") == "SAFETY":
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "") if parts else None
    except Exception as e:
        print(f"Gemini vision exception: {e}")
        return None


def parse_json_response(text):
    if not text:
        return []
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            obj = json.loads(match.group())
            for v in obj.values():
                if isinstance(v, list):
                    return v
        return []
    except:
        return []


# ─────────────────────────────────────────────
# PASS 1: EXTRACT PRODUCTS FROM PAGE
# ─────────────────────────────────────────────
EXTRACT_PROMPT = """Stranica {page} kataloga od trgovine {store}.
Izvuci SVE proizvode s cijenama s ove stranice.
Vrati SAMO JSON array:
[{{"product":"naziv","brand":"brend ili null","quantity":"250g ili null","original_price":"2.99 ili null","sale_price":"1.99","discount_percent":"33% ili null","valid_until":"08.03.2026. ili null","category":"kategorija","subcategory":"potkategorija ili null","fine_print":"sitni tisak ili null"}}]
Kategorije: Meso i riba, Mlijecni proizvodi, Kruh i pekarski, Voce i povrce, Pice, Grickalice i slatkisi, Konzervirana hrana, Kozmetika i higijena, Kucanstvo i ciscenje, Alati i gradnja, Dom i vrt, Elektronika, Odjeca i obuca, Kucni ljubimci, Zdravlje i ljekarna, Ostalo.
Ako nema proizvoda vrati: []"""


def extract_products(image_base64, store, page_num):
    prompt = EXTRACT_PROMPT.format(page=page_num, store=store)
    result1 = parse_json_response(call_gemini_vision(image_base64, prompt))
    result2 = parse_json_response(call_gemini_vision(image_base64, prompt))
    seen = set()
    merged = []
    for p in (result1 + result2):
        if not isinstance(p, dict):
            continue
        name = p.get("product", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(p)
    print(f"  Page {page_num}: {len(merged)} products")
    return merged


# ─────────────────────────────────────────────
# PASS 1: SAVE TO SUPABASE
# ─────────────────────────────────────────────
def parse_date(date_str):
    if not date_str or date_str in ['null', 'None', '']:
        return None
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y", "%d. %m. %Y.", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            continue
    return None


def clean_val(v):
    return v if v not in [None, "null", "None", ""] else None


def save_products(products, store, page_num, page_image_url, catalogue_name, valid_from, valid_until):
    if not products:
        return 0
    records = []
    for p in products:
        if not isinstance(p, dict) or not p.get("product"):
            continue
        final_valid_until = parse_date(p.get("valid_until")) or valid_until
        if not final_valid_until:
            continue
        records.append({
            "store": store,
            "product": p.get("product", "").strip(),
            "brand": clean_val(p.get("brand")),
            "quantity": clean_val(p.get("quantity")),
            "original_price": clean_val(p.get("original_price")),
            "sale_price": clean_val(p.get("sale_price")),
            "discount_percent": clean_val(p.get("discount_percent")),
            "category": p.get("category") or "Ostalo",
            "subcategory": clean_val(p.get("subcategory")),
            "valid_from": valid_from,
            "valid_until": final_valid_until,
            "is_expired": False,
            "page_number": page_num,
            "page_image_url": page_image_url,
            "product_image_url": None,
            "catalogue_name": catalogue_name,
            "catalogue_week": datetime.utcnow().strftime("%Y-W%V"),
            "fine_print": clean_val(p.get("fine_print"))
        })
    if not records:
        return 0
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/products",
                          headers=supa_headers({"Prefer": "return=minimal"}),
                          json=records, timeout=20)
        if r.status_code in [200, 201]:
            return len(records)
        print(f"Save products failed [{r.status_code}]: {r.text[:200]}")
        return 0
    except Exception as e:
        print(f"save_products exception: {e}")
        return 0


def save_catalogue(store, catalogue_name, valid_from, valid_until, pages, products_count, fine_print=None):
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/catalogues",
                      headers=supa_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                      json={"store": store, "catalogue_name": catalogue_name,
                            "valid_from": valid_from, "valid_until": valid_until,
                            "fine_print": fine_print, "pages": pages,
                            "products_count": products_count},
                      timeout=10)
    except:
        pass


# ─────────────────────────────────────────────
# PASS 2: BOUNDING BOXES + CROP
# ─────────────────────────────────────────────
BBOX_PROMPT = """Page {page} of {store} catalog.
Products on this page:
{product_list}

Return bounding boxes as percentage of image (0-100).
Return ONLY JSON array:
[{{"product":"exact name","x1":10,"y1":5,"x2":45,"y2":35}}]
x1,y1=top-left, x2,y2=bottom-right, all percentages. Skip invisible products."""


def get_bounding_boxes(image_base64, store, page_num, products):
    if not products:
        return []
    product_list = "\n".join([f"- {p['product']}" for p in products])
    prompt = BBOX_PROMPT.format(page=page_num, store=store, product_list=product_list)
    result = parse_json_response(call_gemini_vision(image_base64, prompt, timeout=90))
    valid = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            x1, y1, x2, y2 = float(item["x1"]), float(item["y1"]), float(item["x2"]), float(item["y2"])
            if x2 > x1 and y2 > y1 and 0 <= x1 <= 100 and 0 <= y2 <= 100:
                item.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
                valid.append(item)
        except:
            continue
    print(f"  {len(valid)} valid boxes for page {page_num}")
    return valid


def crop_and_upload(pil_image, bbox, storage_path):
    try:
        w, h = pil_image.size
        x1 = max(0, int(bbox["x1"] / 100 * w))
        y1 = max(0, int(bbox["y1"] / 100 * h))
        x2 = min(w, int(bbox["x2"] / 100 * w))
        y2 = min(h, int(bbox["y2"] / 100 * h))
        if x2 - x1 < 10 or y2 - y1 < 10:
            return None
        buf = io.BytesIO()
        pil_image.crop((x1, y1, x2, y2)).save(buf, format="JPEG", quality=90)
        return upload_image(buf.getvalue(), storage_path)
    except Exception as e:
        print(f"crop_and_upload exception: {e}")
        return None


def run_crop_pass(catalogue_name, job_id):
    print(f"\nPASS 2 starting: {catalogue_name}")
    if job_id:
        update_job(job_id, status="cropping", cropped_products=0)
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/products"
            f"?catalogue_name=eq.{requests.utils.quote(catalogue_name)}"
            f"&product_image_url=is.null"
            f"&select=id,product,page_number,page_image_url,store"
            f"&order=page_number.asc&limit=2000",
            headers=supa_headers(), timeout=30
        )
        all_products = r.json() if r.status_code == 200 else []
        if not all_products:
            print(f"No products to crop for: {catalogue_name}")
            if job_id:
                update_job(job_id, status="crop_done", cropped_products=0)
            return

        pages = {}
        for p in all_products:
            pages.setdefault(p.get("page_number"), []).append(p)

        total_cropped = 0
        for page_num, page_products in sorted(pages.items()):
            page_image_url = page_products[0].get("page_image_url")
            store = page_products[0].get("store", "")
            if not page_image_url:
                continue
            try:
                img_r = requests.get(page_image_url, timeout=30)
                if img_r.status_code != 200:
                    continue
                img_bytes = img_r.content
                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            except Exception as e:
                print(f"Image load failed page {page_num}: {e}")
                continue

            bboxes = get_bounding_boxes(img_base64, store, page_num, page_products)
            for bbox_item in bboxes:
                bbox_name = bbox_item.get("product", "").lower().strip()
                matched = next((pp for pp in page_products
                                if pp.get("product", "").lower().strip() == bbox_name), None)
                if not matched:
                    matched = next((pp for pp in page_products
                                    if bbox_name in pp.get("product", "").lower()
                                    or pp.get("product", "").lower() in bbox_name), None)
                if not matched:
                    continue
                storage_path = build_storage_path(store, catalogue_name, page_num, matched["id"])
                img_url = crop_and_upload(pil_img, bbox_item, storage_path)
                if img_url:
                    try:
                        requests.patch(
                            f"{SUPABASE_URL}/rest/v1/products?id=eq.{matched['id']}",
                            headers=supa_headers({"Prefer": "return=minimal"}),
                            json={"product_image_url": img_url}, timeout=10
                        )
                        total_cropped += 1
                    except:
                        pass
            if job_id:
                update_job(job_id, cropped_products=total_cropped)

        print(f"PASS 2 COMPLETE: {total_cropped} images")
        if job_id:
            update_job(job_id, status="crop_done", cropped_products=total_cropped)
    except Exception as e:
        print(f"run_crop_pass exception: {e}")
        if job_id:
            update_job(job_id, status="error")


# ─────────────────────────────────────────────
# WHATSAPP BOT — USER MANAGEMENT
# ─────────────────────────────────────────────
def get_or_create_user(phone):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/users?phone=eq.{requests.utils.quote(phone)}&limit=1",
            headers=supa_headers(), timeout=10
        )
        data = r.json()
        if data and isinstance(data, list):
            return data[0]
    except:
        pass
    country_code = phone.replace("whatsapp:+", "")[:3]
    new_user = {
        "phone": phone,
        "country_code": country_code,
        "language": "hr" if country_code == "385" else "en",
        "total_searches": 0,
        "last_active": datetime.utcnow().isoformat()
    }
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=supa_headers({"Prefer": "return=representation"}),
            json=new_user, timeout=10
        )
        data = r.json()
        print(f"New user: {phone}")
        return data[0] if isinstance(data, list) and data else new_user
    except:
        return new_user


def update_user(phone, updates):
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/users?phone=eq.{requests.utils.quote(phone)}",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json=updates, timeout=10
        )
    except:
        pass


# ─────────────────────────────────────────────
# WHATSAPP BOT — SMART PRODUCT SEARCH
# ─────────────────────────────────────────────
STORES = {
    "plodine": "Plodine", "lidl": "Lidl", "kaufland": "Kaufland",
    "konzum": "Konzum", "spar": "Spar", "studenac": "Studenac"
}

STOP_WORDS = {
    "the","a","an","in","at","for","me","show","find","get","what","is","are",
    "have","has","do","can","you","please","give","want","need","look","search",
    "check","any","deals","sale","price","how","much","does","cost","about",
    "tell","list","all","from","store","shop","catalog","catalogue","katalog",
    "akcija","cijena","gdje","ima","daj","molim","trazi","mi","da","li","po",
    "na","je","su","se","za","od","do","sto","sta","koji","koja","koje","imaju"
}


def smart_search(message):
    msg_lower = message.lower()
    detected_store = next((STORES[s] for s in STORES if s in msg_lower), None)
    words = [w for w in re.findall(r'[a-zA-ZčćđšžČĆĐŠŽ]+', msg_lower)
             if len(w) > 2 and w not in STOP_WORDS and w not in STORES]

    today = date.today().strftime("%Y-%m-%d")
    filters = [
        "is_expired=eq.false",
        f"valid_until=gte.{today}",
        "select=product,brand,quantity,store,sale_price,original_price,discount_percent,valid_until,page_number,category,page_image_url",
        "limit=25",
        "order=discount_percent.desc"
    ]
    if detected_store:
        filters.append(f"store=eq.{detected_store}")
    if words:
        filters.append(f"product=ilike.*{words[0]}*")

    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/products?" + "&".join(filters),
                         headers=supa_headers(), timeout=10)
        products = r.json()
        if not isinstance(products, list):
            return [], detected_store
        print(f"  Search: store={detected_store}, keyword={words[0] if words else '-'}, results={len(products)}")
        return products, detected_store
    except Exception as e:
        print(f"smart_search exception: {e}")
        return [], detected_store


def get_catalogues(store=None):
    today = date.today().strftime("%Y-%m-%d")
    params = [
        "select=store,catalogue_name,valid_from,valid_until,pages,products_count",
        f"valid_until=gte.{today}",
        "order=valid_from.desc",
        "limit=10"
    ]
    if store:
        params.append(f"store=eq.{store}")
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/catalogues?" + "&".join(params),
                         headers=supa_headers(), timeout=10)
        return r.json() if isinstance(r.json(), list) else []
    except:
        return []


def get_page_image_url(store, page_number):
    store_cap = STORES.get(store.lower(), store)
    today = date.today().strftime("%Y-%m-%d")
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/products"
            f"?select=page_image_url"
            f"&store=eq.{store_cap}"
            f"&page_number=eq.{page_number}"
            f"&is_expired=eq.false"
            f"&valid_until=gte.{today}"
            f"&limit=1",
            headers=supa_headers(), timeout=10
        )
        data = r.json()
        if data and isinstance(data, list):
            return data[0].get("page_image_url")
        return None
    except:
        return None


# ─────────────────────────────────────────────
# WHATSAPP BOT — CONVERSATION HISTORY
# ─────────────────────────────────────────────
def get_history(phone, limit=6):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/chat_history"
            f"?session_id=eq.{requests.utils.quote(phone)}"
            f"&select=role,message,created_at"
            f"&order=created_at.desc&limit={limit}",
            headers=supa_headers(), timeout=10
        )
        data = r.json()
        if not isinstance(data, list):
            return []
        return [{"role": h["role"], "content": h["message"]} for h in reversed(data)]
    except:
        return []


def save_to_history(phone, role, message):
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/chat_history",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json={"session_id": phone, "role": role,
                  "message": message[:2000],
                  "created_at": datetime.utcnow().isoformat()},
            timeout=10
        )
    except:
        pass


# ─────────────────────────────────────────────
# WHATSAPP BOT — ASK GEMINI
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """Ti si katalog.ai - osobni shopping asistent.
Pomažeš korisnicima pronaći akcije u supermarketima u Hrvatskoj.
Uvijek odgovaraj na ISTOM jeziku na kojem korisnik piše.
NIKAD ne koristis markdown, zvjezdice, bold ili bullet points - samo obican tekst.
Maksimalno 6 proizvoda po odgovoru.
Budi kratak, prijateljski i koristan.
Dostupne trgovine: Lidl, Kaufland, Konzum, Spar, Plodine, Studenac
Format za proizvode: Naziv - Cijena EUR (Trgovina, vrijedi do DATUM)"""


def ask_gemini_chat(user_message, products, catalogues, history):
    context_lines = []
    if products:
        context_lines.append(f"PRONAĐENO {len(products)} PROIZVODA:")
        for p in products[:20]:
            line = f"- {p.get('product','')} {p.get('brand','')} {p.get('quantity','')} | {p.get('sale_price','?')} EUR"
            if p.get('original_price'):
                line += f" (bilo {p.get('original_price')} EUR)"
            if p.get('discount_percent'):
                line += f" -{p.get('discount_percent')}"
            line += f" | {p.get('store','')} | do: {p.get('valid_until','')} | str.{p.get('page_number','')}"
            context_lines.append(line)
    if catalogues:
        context_lines.append(f"\nDOSTUPNI KATALOZI:")
        for c in catalogues:
            context_lines.append(f"- {c.get('store')} | {c.get('valid_from')} do {c.get('valid_until')} | {c.get('pages')} str. | {c.get('products_count')} proizvoda")
    if not context_lines:
        context_lines.append("Nisu pronađeni odgovarajući proizvodi.")

    messages = []
    for h in history[-6:]:
        role = "user" if h["role"] == "user" else "model"
        messages.append({"role": role, "parts": [{"text": h["content"]}]})
    messages.append({"role": "user", "parts": [{"text": f"Kontekst:\n{chr(10).join(context_lines)}\n\nPoruka: {user_message}"}]})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": messages,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400}
    }
    try:
        r = requests.post(f"{GEMINI_CHAT_URL}?key={GEMINI_API_KEY}",
                          json=payload, timeout=30)
        if r.status_code != 200:
            print(f"Gemini chat error {r.status_code}: {r.text[:200]}")
            return "Servis trenutno nije dostupan. Pokušajte ponovno."
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "Nema odgovora. Pokušajte ponovno."
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "").strip() if parts else "Nema odgovora."
    except Exception as e:
        print(f"ask_gemini_chat exception: {e}")
        return "Greška u servisu."


# ─────────────────────────────────────────────
# DETECT PAGE IMAGE REQUEST
# ─────────────────────────────────────────────
def detect_page_request(message):
    msg = message.lower()
    page_match = re.search(r'\b(\d{1,3})\b', msg)
    if not page_match:
        return None, None
    page_num = int(page_match.group(1))
    store = next((STORES[s] for s in STORES if s in msg), None)
    page_keywords = ["page", "stranica", "strana", "str", "sliku", "slika", "prikaži", "show"]
    if any(kw in msg for kw in page_keywords) and store:
        return store, page_num
    return None, None


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def home():
    return "katalog.ai running -> /upload-tool"


@app.route("/upload-tool")
def upload_tool():
    return UPLOAD_HTML


@app.route("/upload", methods=["POST"])
def upload():
    file        = request.files.get("file")
    store       = request.form.get("store", "").strip()
    valid_from  = request.form.get("valid_from", "").strip()
    valid_until = request.form.get("valid_until", "").strip()

    errors = []
    if not file:        errors.append("No PDF")
    if not store:       errors.append("No store")
    if not valid_from:  errors.append("No valid_from")
    if not valid_until: errors.append("No valid_until")
    if errors:
        return jsonify({"error": " | ".join(errors)}), 400

    catalogue_name = os.path.splitext(file.filename)[0]

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file.save(tmp.name)
            temp_path = tmp.name
    except Exception as e:
        return jsonify({"error": f"Could not save PDF: {e}"}), 500

    try:
        images = convert_from_path(temp_path, dpi=150)
        total_pages = len(images)
    except Exception as e:
        os.unlink(temp_path)
        return jsonify({"error": f"PDF conversion failed: {e}"}), 500

    job_id = create_job(store, catalogue_name, total_pages, valid_from, valid_until)
    if not job_id:
        os.unlink(temp_path)
        return jsonify({"error": "Could not create job"}), 500

    print(f"PASS 1: {catalogue_name} | {store} | {total_pages} pages")

    def process():
        total_products = 0
        catalogue_fine_print = None
        try:
            for page_num in range(total_pages):
                i = page_num + 1
                try:
                    img = images[page_num]
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                    storage_path = build_storage_path(store, catalogue_name, i)
                    page_image_url = upload_image(img_bytes, storage_path)

                    products = extract_products(img_base64, store, i)

                    for p in products:
                        fp = p.get("fine_print")
                        if fp and fp not in ["null", None]:
                            catalogue_fine_print = (catalogue_fine_print + " " + fp) if catalogue_fine_print else fp

                    saved = save_products(products, store, i, page_image_url,
                                          catalogue_name, valid_from, valid_until)
                    total_products += saved
                    update_job(job_id, current_page=i, total_products=total_products, status="processing")
                except Exception as page_err:
                    print(f"Page {i} error: {page_err}")
                    update_job(job_id, current_page=i)
                    continue

            try:
                os.unlink(temp_path)
            except:
                pass

            save_catalogue(store, catalogue_name, valid_from, valid_until,
                           total_pages, total_products, catalogue_fine_print)
            update_job(job_id, status="done", current_page=total_pages,
                       total_products=total_products, catalogue_name=catalogue_name)
            print(f"PASS 1 COMPLETE: {total_products} products")

        except Exception as e:
            print(f"process() exception: {e}")
            update_job(job_id, status="error")
            try:
                os.unlink(temp_path)
            except:
                pass

    threading.Thread(target=process, daemon=True).start()
    return jsonify({"job_id": job_id, "total_pages": total_pages,
                    "catalogue_name": catalogue_name, "message": "Pass 1 started"})


@app.route("/status/<job_id>")
def status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    return jsonify(job)


@app.route("/crop", methods=["POST"])
def crop():
    data = request.get_json(silent=True) or {}
    catalogue_name = data.get("catalogue_name", "").strip()
    job_id = data.get("job_id")
    if not catalogue_name:
        return jsonify({"error": "catalogue_name required"}), 400
    if not job_id:
        job_id = create_job("crop", catalogue_name, 0, None, None)
    threading.Thread(target=run_crop_pass, args=(catalogue_name, job_id), daemon=True).start()
    return jsonify({"job_id": job_id, "catalogue_name": catalogue_name, "message": "Pass 2 started"})


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming = request.form.get("Body", "").strip()
    sender   = request.form.get("From", "")

    print(f"\n{sender}: {incoming[:100]}")

    if not incoming or not sender:
        return str(MessagingResponse())

    user = get_or_create_user(sender)
    save_to_history(sender, "user", incoming)
    history = get_history(sender)

    resp = MessagingResponse()

    # Check for page image request first
    store, page_num = detect_page_request(incoming)
    if store and page_num:
        image_url = get_page_image_url(store, page_num)
        if image_url:
            msg = resp.message(f"{store} - stranica {page_num}:")
            msg.media(image_url)
            save_to_history(sender, "assistant", f"[Sent: {store} page {page_num}]")
        else:
            reply = f"Nemam sliku za stranicu {page_num} kataloga {store}."
            resp.message(reply)
            save_to_history(sender, "assistant", reply)
        update_user(sender, {"last_active": datetime.utcnow().isoformat(),
                              "total_searches": (user.get("total_searches") or 0) + 1})
        return str(resp)

    # Smart product search
    products, detected_store = smart_search(incoming)

    # Get catalogues if relevant
    catalogues = []
    if any(kw in incoming.lower() for kw in ["katalog", "catalog", "catalogue", "ponuda", "stranica"]):
        catalogues = get_catalogues(detected_store)

    # Ask Gemini
    reply = ask_gemini_chat(incoming, products, catalogues, history)

    resp.message(reply)
    save_to_history(sender, "assistant", reply)
    update_user(sender, {"last_active": datetime.utcnow().isoformat(),
                          "total_searches": (user.get("total_searches") or 0) + 1})

    print(f"Reply: {reply[:80]}")
    return str(resp)


@app.route("/health")
def health():
    checks = {
        "gemini_key": bool(GEMINI_API_KEY),
        "supabase_url": bool(SUPABASE_URL),
        "supabase_key": bool(SUPABASE_KEY),
    }
    ok = all(checks.values())
    return jsonify({"status": "ok" if ok else "degraded", "checks": checks}), 200 if ok else 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
