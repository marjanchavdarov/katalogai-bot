from flask import Flask, request, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import uuid
import io
import tempfile
import re
from datetime import datetime, timedelta
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

# ─────────────────────────────────────────────
# STARTUP CHECK — immediately visible in logs
# ─────────────────────────────────────────────
print("=" * 60)
print("katalog.ai starting up...")
print(f"  GEMINI_API_KEY : {'✅ SET' if GEMINI_API_KEY else '❌ MISSING'}")
print(f"  SUPABASE_URL   : {'✅ ' + SUPABASE_URL if SUPABASE_URL else '❌ MISSING'}")
print(f"  SUPABASE_KEY   : {'✅ SET' if SUPABASE_KEY else '❌ MISSING'}")
print("=" * 60)


# ─────────────────────────────────────────────
# UPLOAD UI HTML
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
<div class="info">Pass 1: Upload PDF → extract products.<br>Pass 2 starts automatically after Pass 1.</div>

<label>PDF File:</label>
<div class="file-input-wrapper"><input type="file" id="f" accept=".pdf"></div>
<label>Store:</label>
<input type="text" id="s" placeholder="Lidl">
<label>Valid From (YYYY-MM-DD):</label>
<input type="text" id="vf" placeholder="2026-03-02">
<label>Valid Until (YYYY-MM-DD, empty = +14 days):</label>
<input type="text" id="vu" placeholder="2026-03-15">

<button id="btn" onclick="startUpload()">▶ Process PDF</button>
<button class="secondary" onclick="cropOnly()">✂ Crop Existing (Pass 2 only)</button>

<div id="bar-wrap"><div id="fill">0%</div></div>
<div id="log">Ready. Select a PDF and click Process.</div>

<script>
var pollTimer = null;
var currentJobId = null;

function log(msg) {
  var el = document.getElementById("log");
  el.textContent += msg + "\\n";
  el.scrollTop = el.scrollHeight;
}

function setProgress(pct, label) {
  var bw = document.getElementById("bar-wrap");
  var fill = document.getElementById("fill");
  bw.style.display = "block";
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

  log("📤 Uploading: " + f.name);
  log("🏪 Store: " + s);
  log("📅 Valid: " + vf + " → " + vu);
  log("──────────────────────────────");

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
      if (data.error) { log("❌ " + data.error); resetBtn(); return; }
      currentJobId = data.job_id;
      log("✅ Job started: " + data.job_id);
      log("📄 Total pages: " + data.total_pages);
      log("──────────────────────────────");
      document.getElementById("btn").textContent = "Processing...";
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(function() { poll(data.job_id); }, 3000);
    })
    .catch(function(e) { log("❌ Upload error: " + e.message); resetBtn(); });
}

function poll(jobId) {
  fetch("/status/" + jobId)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var pct = d.total_pages > 0 ? Math.round((d.current_page / d.total_pages) * 100) : 0;
      setProgress(pct);
      document.getElementById("btn").textContent = "Pass 1: Page " + d.current_page + "/" + d.total_pages + " (" + d.total_products + " products)";

      if (d.status === "cropping") {
        document.getElementById("btn").textContent = "Pass 2: Cropping... " + (d.cropped_products || 0) + " done";
        setProgress(100, "Cropping...");
      }

      if (d.status === "done") {
        clearInterval(pollTimer);
        log("✅ PASS 1 DONE: " + d.total_products + " products from " + d.total_pages + " pages");
        log("✂ Starting Pass 2 (cropping)...");
        setProgress(100, "Done!");
        document.getElementById("btn").textContent = "Cropping products...";
        startCrop(d.catalogue_name, jobId);
      }

      if (d.status === "crop_done") {
        clearInterval(pollTimer);
        log("✅ PASS 2 DONE: " + d.cropped_products + " product images cropped");
        log("🎉 ALL DONE! Check Supabase.");
        setProgress(100, "ALL DONE!");
        resetBtn("Process Another");
      }

      if (d.status === "error") {
        clearInterval(pollTimer);
        log("❌ Job error - check server logs. Job ID: " + jobId);
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
    if (d.error) { log("⚠️ Crop error: " + d.error); resetBtn(); return; }
    log("✂ Cropping started for: " + catalogueName);
  })
  .catch(function(e) { log("⚠️ Could not start crop: " + e.message); resetBtn(); });
}

function cropOnly() {
  var cn = prompt("Enter catalogue_name to crop (from Supabase catalogues table):");
  if (!cn) return;
  document.getElementById("log").textContent = "";
  log("✂ Starting Pass 2 for: " + cn);
  fetch("/crop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalogue_name: cn })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { log("❌ " + d.error); return; }
    log("✅ Crop job started: " + d.job_id);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function() { poll(d.job_id); }, 3000);
  })
  .catch(function(e) { log("❌ " + e.message); });
}

function resetBtn(label) {
  var btn = document.getElementById("btn");
  btn.disabled = false;
  btn.textContent = label || "▶ Process PDF";
}

document.addEventListener("DOMContentLoaded", function() {
  document.getElementById("f").addEventListener("change", function() {
    if (this.files[0]) {
      document.getElementById("log").textContent = "📄 Selected: " + this.files[0].name + " (" + Math.round(this.files[0].size/1024) + " KB)\\nReady.";
    }
  });
});
</script>
</body>
</html>'''


# ─────────────────────────────────────────────
# HELPER: SUPABASE HEADERS
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
# JOB TRACKING (Supabase jobs table)
# ─────────────────────────────────────────────
def create_job(store, catalogue_name, total_pages, valid_from, valid_until):
    """Create a new job record in Supabase. Returns job_id string."""
    job_id = str(uuid.uuid4())[:8]
    record = {
        "job_id": job_id,
        "store": store,
        "catalogue_name": catalogue_name,
        "status": "processing",
        "total_pages": total_pages,
        "current_page": 0,
        "total_products": 0,
        "cropped_products": 0,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/jobs",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json=record,
            timeout=10
        )
        if r.status_code not in [200, 201]:
            print(f"❌ create_job failed: {r.status_code} {r.text}")
            return None
        print(f"✅ Job created: {job_id}")
        return job_id
    except Exception as e:
        print(f"❌ create_job exception: {e}")
        return None


def update_job(job_id, **kwargs):
    """Update any fields on a job record."""
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/jobs?job_id=eq.{job_id}",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json=kwargs,
            timeout=10
        )
        if r.status_code not in [200, 204]:
            print(f"⚠️ update_job({job_id}) failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"⚠️ update_job exception: {e}")


def get_job(job_id):
    """Fetch a single job record."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/jobs?job_id=eq.{job_id}&select=*",
            headers=supa_headers(),
            timeout=10
        )
        data = r.json()
        return data[0] if data else None
    except Exception as e:
        print(f"⚠️ get_job exception: {e}")
        return None


# ─────────────────────────────────────────────
# SUPABASE STORAGE IMAGE UPLOAD (FIXED)
# ─────────────────────────────────────────────
def upload_image(image_bytes, storage_path):
    """
    Upload image to Supabase Storage.
    Uses PUT with x-upsert so it works for new AND existing files.
    Returns public URL or None on failure.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ upload_image: Supabase credentials missing")
        return None

    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{storage_path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true"   # ← THE FIX: works for both new and existing files
    }

    try:
        r = requests.put(url, headers=headers, data=image_bytes, timeout=30)
        if r.status_code in [200, 201]:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{storage_path}"
            print(f"✅ Uploaded: {storage_path}")
            return public_url
        else:
            print(f"❌ Upload failed [{r.status_code}]: {storage_path} → {r.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ Upload exception: {storage_path} → {e}")
        return None


def build_storage_path(store, catalogue_name, page_num, product_index=None):
    """
    Build consistent storage paths.
    Page:    lidl/2026-03-02/page_001.jpg
    Product: lidl/2026-03-02/products/page_001_product_003.jpg
    """
    store_clean = re.sub(r'[^a-z0-9_]', '_', store.lower())
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', catalogue_name)
    date_folder = date_match.group(1) if date_match else datetime.utcnow().strftime("%Y-%m-%d")

    if product_index is None:
        return f"{store_clean}/{date_folder}/page_{str(page_num).zfill(3)}.jpg"
    else:
        return f"{store_clean}/{date_folder}/products/page_{str(page_num).zfill(3)}_product_{str(product_index).zfill(3)}.jpg"


# ─────────────────────────────────────────────
# GEMINI HELPERS
# ─────────────────────────────────────────────
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

def call_gemini(image_base64, prompt, timeout=60):
    """
    Call Gemini vision API. Returns raw text or None.
    Detailed error logging for every failure mode.
    """
    if not GEMINI_API_KEY:
        print("❌ call_gemini: GEMINI_API_KEY not set")
        return None

    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=timeout
        )

        if r.status_code != 200:
            print(f"❌ Gemini HTTP {r.status_code}: {r.text[:300]}")
            return None

        data = r.json()

        if "error" in data:
            print(f"❌ Gemini API error: {data['error']}")
            return None

        if "candidates" not in data or not data["candidates"]:
            print(f"❌ Gemini no candidates. Full response: {json.dumps(data)[:500]}")
            return None

        candidate = data["candidates"][0]

        if candidate.get("finishReason") == "SAFETY":
            print(f"⚠️ Gemini blocked page for safety reasons")
            return None

        parts = candidate.get("content", {}).get("parts", [])
        if not parts:
            print(f"❌ Gemini empty parts in response")
            return None

        return parts[0].get("text", "")

    except requests.exceptions.Timeout:
        print(f"❌ Gemini timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"❌ Gemini exception: {e}")
        return None


def parse_json_response(text):
    """Safely extract JSON array from Gemini text response."""
    if not text:
        return []
    try:
        # Strip markdown code fences
        text = text.replace("```json", "").replace("```", "").strip()
        # Find JSON array
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Maybe it's a JSON object with array inside
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            obj = json.loads(match.group())
            # Return first list value found
            for v in obj.values():
                if isinstance(v, list):
                    return v
        return []
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON parse error: {e} | Text: {text[:200]}")
        return []


# ─────────────────────────────────────────────
# PASS 1: EXTRACT PRODUCTS FROM PAGE
# ─────────────────────────────────────────────
EXTRACT_PROMPT = """Stranica {page} kataloga od trgovine {store}.
Izvuci SVE proizvode s cijenama s ove stranice.
Vrati SAMO JSON array bez ikakvog teksta izvan njega:
[
  {{
    "product": "naziv proizvoda",
    "brand": "brend ili null",
    "quantity": "250g ili null",
    "original_price": "2.99 ili null",
    "sale_price": "1.99",
    "discount_percent": "33% ili null",
    "valid_until": "08.03.2026. ili null",
    "category": "kategorija",
    "subcategory": "potkategorija ili null",
    "fine_print": "sitni tisak ili null"
  }}
]
Kategorije: Meso i riba, Mlijecni proizvodi, Kruh i pekarski, Voce i povrce, Pice,
Grickalice i slatkisi, Konzervirana hrana, Kozmetika i higijena, Kucanstvo i ciscenje,
Alati i gradnja, Dom i vrt, Elektronika, Odjeca i obuca, Kucni ljubimci, Zdravlje i ljekarna, Ostalo.
Ako nema proizvoda vrati: []"""


def extract_products(image_base64, store, page_num):
    """
    Single pass extraction. Returns list of product dicts.
    Two attempts with deduplication.
    """
    prompt = EXTRACT_PROMPT.format(page=page_num, store=store)

    print(f"  🔍 Pass 1 attempt 1 - page {page_num}")
    result1 = parse_json_response(call_gemini(image_base64, prompt))

    print(f"  🔍 Pass 1 attempt 2 - page {page_num}")
    result2 = parse_json_response(call_gemini(image_base64, prompt))

    # Merge and deduplicate by product name
    seen = set()
    merged = []
    for p in (result1 + result2):
        if not isinstance(p, dict):
            continue
        name = p.get("product", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(p)

    print(f"  📦 Page {page_num}: attempt1={len(result1)}, attempt2={len(result2)}, merged={len(merged)}")
    return merged


# ─────────────────────────────────────────────
# PASS 1: SAVE PRODUCTS TO SUPABASE
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
    """Insert products into Supabase. Returns count saved."""
    if not products:
        return 0

    records = []
    for p in products:
        if not isinstance(p, dict) or not p.get("product"):
            continue

        product_valid_until = parse_date(p.get("valid_until"))
        final_valid_until = product_valid_until or valid_until
        if not final_valid_until:
            print(f"  ⚠️ Skipping '{p.get('product')}' — no valid_until")
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
            "product_image_url": None,   # filled in by Pass 2
            "catalogue_name": catalogue_name,
            "catalogue_week": datetime.utcnow().strftime("%Y-W%V"),
            "fine_print": clean_val(p.get("fine_print"))
        })

    if not records:
        return 0

    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/products",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json=records,
            timeout=20
        )
        if r.status_code in [200, 201]:
            print(f"  ✅ Saved {len(records)} products for page {page_num}")
            return len(records)
        else:
            print(f"  ❌ Save products failed [{r.status_code}]: {r.text[:300]}")
            return 0
    except Exception as e:
        print(f"  ❌ save_products exception: {e}")
        return 0


def save_catalogue(store, catalogue_name, valid_from, valid_until, pages, products_count, fine_print=None):
    record = {
        "store": store,
        "catalogue_name": catalogue_name,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "fine_print": fine_print,
        "pages": pages,
        "products_count": products_count
    }
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/catalogues",
            headers=supa_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
            json=record,
            timeout=10
        )
        if r.status_code in [200, 201]:
            print(f"✅ Catalogue saved: {catalogue_name}")
        else:
            print(f"⚠️ Catalogue save failed [{r.status_code}]: {r.text[:200]}")
    except Exception as e:
        print(f"⚠️ save_catalogue exception: {e}")


# ─────────────────────────────────────────────
# PASS 2: GET BOUNDING BOXES FROM GEMINI
# ─────────────────────────────────────────────
BBOX_PROMPT = """Ovo je stranica {page} kataloga od trgovine {store}.
Na ovoj stranici su sljedeći proizvodi:
{product_list}

Za svaki od ovih proizvoda pronađi mu vizualnu poziciju na slici i vrati bounding box
kao postotak dimenzija slike (0-100).

Vrati SAMO JSON array:
[
  {{
    "product": "točan naziv proizvoda",
    "x1": 10,
    "y1": 5,
    "x2": 45,
    "y2": 35
  }}
]
gdje x1,y1 = gornji lijevi kut, x2,y2 = donji desni kut, sve u postocima (0-100).
Ako proizvod nije vidljiv preskoči ga.
Vrati SAMO JSON array bez teksta izvan njega."""


def get_bounding_boxes(image_base64, store, page_num, products):
    """
    Ask Gemini for bounding boxes of known products on a page.
    Returns list of dicts with product + bbox coords.
    """
    if not products:
        return []

    product_list = "\n".join([f"- {p['product']}" for p in products])
    prompt = BBOX_PROMPT.format(page=page_num, store=store, product_list=product_list)

    print(f"  📐 Getting bounding boxes for {len(products)} products on page {page_num}")
    text = call_gemini(image_base64, prompt, timeout=90)
    result = parse_json_response(text)

    # Validate boxes
    valid = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            x1, y1, x2, y2 = float(item["x1"]), float(item["y1"]), float(item["x2"]), float(item["y2"])
            if x2 > x1 and y2 > y1 and 0 <= x1 <= 100 and 0 <= y2 <= 100:
                item.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
                valid.append(item)
            else:
                print(f"  ⚠️ Invalid bbox for '{item.get('product')}': {x1},{y1},{x2},{y2}")
        except (KeyError, ValueError, TypeError) as e:
            print(f"  ⚠️ Bbox parse error for '{item.get('product')}': {e}")

    print(f"  📐 Got {len(valid)}/{len(result)} valid bounding boxes")
    return valid


# ─────────────────────────────────────────────
# PASS 2: CROP AND UPLOAD PRODUCT IMAGES
# ─────────────────────────────────────────────
def crop_and_upload(pil_image, bbox, storage_path):
    """
    Crop a region from PIL image using percentage bbox and upload to Supabase.
    Returns public URL or None.
    """
    try:
        w, h = pil_image.size
        x1 = int(bbox["x1"] / 100 * w)
        y1 = int(bbox["y1"] / 100 * h)
        x2 = int(bbox["x2"] / 100 * w)
        y2 = int(bbox["y2"] / 100 * h)

        # Safety clamp
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 - x1 < 10 or y2 - y1 < 10:
            print(f"  ⚠️ Crop too small: {x2-x1}x{y2-y1}px — skipping")
            return None

        cropped = pil_image.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        buf.seek(0)

        return upload_image(buf.read(), storage_path)

    except Exception as e:
        print(f"  ❌ crop_and_upload exception: {e}")
        return None


def update_product_image_url(product_id, image_url):
    """Update product_image_url for a single product."""
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/products?id=eq.{product_id}",
            headers=supa_headers({"Prefer": "return=minimal"}),
            json={"product_image_url": image_url},
            timeout=10
        )
        if r.status_code not in [200, 204]:
            print(f"  ⚠️ update_product_image_url failed [{r.status_code}]: {r.text[:200]}")
    except Exception as e:
        print(f"  ⚠️ update_product_image_url exception: {e}")


def get_page_image_bytes(page_image_url):
    """Download page image from Supabase storage for cropping."""
    try:
        r = requests.get(page_image_url, timeout=30)
        if r.status_code == 200:
            return r.content
        print(f"  ❌ Could not fetch page image [{r.status_code}]: {page_image_url}")
        return None
    except Exception as e:
        print(f"  ❌ get_page_image_bytes exception: {e}")
        return None


# ─────────────────────────────────────────────
# PASS 2: MAIN CROPPING WORKER
# ─────────────────────────────────────────────
def run_crop_pass(catalogue_name, job_id):
    """
    Background worker for Pass 2.
    1. Gets all products for this catalogue grouped by page
    2. Downloads page image
    3. Asks Gemini for bounding boxes
    4. Crops each product
    5. Uploads to Supabase storage
    6. Updates product record with image URL
    """
    import threading
    print(f"\n{'='*60}")
    print(f"✂ PASS 2 starting for: {catalogue_name}")
    print(f"{'='*60}")

    if job_id:
        update_job(job_id, status="cropping", cropped_products=0)

    try:
        # Get all products for this catalogue (only those without product_image_url)
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/products"
            f"?catalogue_name=eq.{requests.utils.quote(catalogue_name)}"
            f"&product_image_url=is.null"
            f"&select=id,product,page_number,page_image_url,store"
            f"&order=page_number.asc"
            f"&limit=2000",
            headers=supa_headers(),
            timeout=30
        )
        all_products = r.json() if r.status_code == 200 else []

        if not all_products:
            print(f"⚠️ No products without images found for: {catalogue_name}")
            if job_id:
                update_job(job_id, status="crop_done", cropped_products=0)
            return

        print(f"📦 Found {len(all_products)} products to crop")

        # Group by page
        pages = {}
        for p in all_products:
            pn = p.get("page_number")
            if pn not in pages:
                pages[pn] = []
            pages[pn].append(p)

        total_cropped = 0

        for page_num, page_products in sorted(pages.items()):
            print(f"\n  📄 Page {page_num}: {len(page_products)} products")

            # Get page image URL (same for all products on page)
            page_image_url = page_products[0].get("page_image_url")
            store = page_products[0].get("store", "")

            if not page_image_url:
                print(f"  ⚠️ No page_image_url for page {page_num} — skipping")
                continue

            # Download page image
            img_bytes = get_page_image_bytes(page_image_url)
            if not img_bytes:
                print(f"  ❌ Could not download page image — skipping page {page_num}")
                continue

            # Convert to PIL and base64
            try:
                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            except Exception as e:
                print(f"  ❌ PIL open failed: {e}")
                continue

            # Get bounding boxes from Gemini
            bboxes = get_bounding_boxes(img_base64, store, page_num, page_products)

            if not bboxes:
                print(f"  ⚠️ No bounding boxes returned for page {page_num}")
                continue

            # Match bboxes to products by name and crop
            for bbox_item in bboxes:
                bbox_name = bbox_item.get("product", "").lower().strip()

                # Find matching product
                matched = None
                for pp in page_products:
                    if pp.get("product", "").lower().strip() == bbox_name:
                        matched = pp
                        break

                # Fuzzy match if exact fails
                if not matched:
                    for pp in page_products:
                        pp_name = pp.get("product", "").lower().strip()
                        if bbox_name in pp_name or pp_name in bbox_name:
                            matched = pp
                            break

                if not matched:
                    print(f"  ⚠️ No product match for bbox: '{bbox_item.get('product')}'")
                    continue

                # Build storage path and crop
                storage_path = build_storage_path(store, catalogue_name, page_num, matched["id"])
                img_url = crop_and_upload(pil_img, bbox_item, storage_path)

                if img_url:
                    update_product_image_url(matched["id"], img_url)
                    total_cropped += 1
                    print(f"  ✂ Cropped: {matched['product']} → {storage_path}")

            # Update job progress after each page
            if job_id:
                update_job(job_id, cropped_products=total_cropped)

        print(f"\n✅ PASS 2 COMPLETE: {total_cropped} product images cropped")
        if job_id:
            update_job(job_id, status="crop_done", cropped_products=total_cropped)

    except Exception as e:
        print(f"❌ run_crop_pass exception: {e}")
        if job_id:
            update_job(job_id, status="error")


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return "katalog.ai running ✅ → go to /upload-tool"


@app.route("/upload-tool")
def upload_tool():
    return UPLOAD_HTML


@app.route("/upload", methods=["POST"])
def upload():
    """Pass 1: Receive PDF, extract products, store in Supabase."""
    file       = request.files.get("file")
    store      = request.form.get("store", "").strip()
    valid_from = request.form.get("valid_from", "").strip()
    valid_until = request.form.get("valid_until", "").strip()

    # Validate inputs
    errors = []
    if not file:        errors.append("No PDF file")
    if not store:       errors.append("No store name")
    if not valid_from:  errors.append("No valid_from date")
    if not valid_until: errors.append("No valid_until date")
    if errors:
        return jsonify({"error": " | ".join(errors)}), 400

    catalogue_name = os.path.splitext(file.filename)[0]

    # Save PDF to temp file
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file.save(tmp.name)
            temp_path = tmp.name
    except Exception as e:
        return jsonify({"error": f"Could not save PDF: {e}"}), 500

    # Convert PDF to images to get page count
    try:
        images = convert_from_path(temp_path, dpi=150)
        total_pages = len(images)
    except Exception as e:
        os.unlink(temp_path)
        return jsonify({"error": f"PDF conversion failed: {e}"}), 500

    # Create job record
    job_id = create_job(store, catalogue_name, total_pages, valid_from, valid_until)
    if not job_id:
        os.unlink(temp_path)
        return jsonify({"error": "Could not create job in Supabase — check jobs table exists"}), 500

    print(f"\n{'='*60}")
    print(f"📄 PASS 1: {catalogue_name}")
    print(f"   Store: {store} | Pages: {total_pages} | Job: {job_id}")
    print(f"{'='*60}")

    # Process pages in background thread
    import threading
    def process():
        total_products = 0
        catalogue_fine_print = None

        try:
            for page_num in range(total_pages):
                i = page_num + 1
                print(f"\n  📄 Processing page {i}/{total_pages}")

                try:
                    img = images[page_num]

                    # Convert to bytes and base64
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                    # Upload page image to Supabase storage
                    storage_path = build_storage_path(store, catalogue_name, i)
                    page_image_url = upload_image(img_bytes, storage_path)

                    if not page_image_url:
                        print(f"  ⚠️ Page {i} image upload failed — products will have no page_image_url")

                    # Extract products (two attempts, merged)
                    products = extract_products(img_base64, store, i)

                    # Collect fine print
                    for p in products:
                        fp = p.get("fine_print")
                        if fp and fp not in ["null", None]:
                            catalogue_fine_print = (catalogue_fine_print + " " + fp) if catalogue_fine_print else fp

                    # Save to Supabase
                    saved = save_products(
                        products, store, i, page_image_url,
                        catalogue_name, valid_from, valid_until
                    )
                    total_products += saved

                    # Update job progress
                    update_job(job_id,
                        current_page=i,
                        total_products=total_products,
                        status="processing"
                    )

                except Exception as page_err:
                    print(f"  ❌ Page {i} error: {page_err}")
                    update_job(job_id, current_page=i)
                    continue

            # Cleanup temp file
            try:
                os.unlink(temp_path)
            except:
                pass

            # Save catalogue summary
            save_catalogue(store, catalogue_name, valid_from, valid_until,
                           total_pages, total_products, catalogue_fine_print)

            # Mark Pass 1 done
            update_job(job_id,
                status="done",
                current_page=total_pages,
                total_products=total_products,
                catalogue_name=catalogue_name
            )
            print(f"\n✅ PASS 1 COMPLETE: {total_products} products from {total_pages} pages")

        except Exception as e:
            print(f"❌ process() exception: {e}")
            update_job(job_id, status="error")
            try:
                os.unlink(temp_path)
            except:
                pass

    thread = threading.Thread(target=process, daemon=True)
    thread.start()

    return jsonify({
        "job_id": job_id,
        "total_pages": total_pages,
        "catalogue_name": catalogue_name,
        "message": "Pass 1 started"
    })


@app.route("/status/<job_id>")
def status(job_id):
    """Return current job status from Supabase."""
    job = get_job(job_id)
    if not job:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    return jsonify(job)


@app.route("/crop", methods=["POST"])
def crop():
    """
    Pass 2: Crop product images for a catalogue.
    Body: { "catalogue_name": "...", "job_id": "..." (optional) }
    """
    data = request.get_json(silent=True) or {}
    catalogue_name = data.get("catalogue_name", "").strip()
    job_id = data.get("job_id")

    if not catalogue_name:
        return jsonify({"error": "catalogue_name required"}), 400

    # If no job_id provided, create a new crop job
    if not job_id:
        job_id = create_job("crop", catalogue_name, 0, None, None)

    print(f"✂ Pass 2 requested for: {catalogue_name} (job: {job_id})")

    import threading
    thread = threading.Thread(
        target=run_crop_pass,
        args=(catalogue_name, job_id),
        daemon=True
    )
    thread.start()

    return jsonify({
        "job_id": job_id,
        "catalogue_name": catalogue_name,
        "message": "Pass 2 (cropping) started"
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    """WhatsApp webhook placeholder — handled by n8n."""
    incoming = request.form.get("Body", "").strip()
    sender   = request.form.get("From", "")
    print(f"📱 WhatsApp from {sender}: {incoming}")
    resp = MessagingResponse()
    resp.message("katalog.ai: handled by n8n ✅")
    return str(resp)


@app.route("/health")
def health():
    """Health check endpoint for Render."""
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
