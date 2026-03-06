from flask import Flask, request, jsonify, send_file
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import threading
from datetime import datetime, date, timedelta
import re
import io
import tempfile
from PIL import Image
import pdf2image
from pdf2image import convert_from_path

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===========================
# UPLOAD TOOL HTML (embedded)
# ===========================
UPLOAD_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>katalog.ai Upload</title>
<style>
body{font-family:monospace;background:#111;color:#eee;padding:40px;max-width:700px;margin:0 auto}
h1{color:#00ff88}
input, .file-input-wrapper{background:#222;border:1px solid #444;color:#eee;padding:8px;width:100%;margin:5px 0 15px 0;font-family:monospace;display:block;box-sizing:border-box}
.file-input-wrapper{padding:0;overflow:hidden}
.file-input-wrapper input[type=file]{border:none;margin:0;padding:10px;background:#1a1a1a;width:100%}
.file-input-wrapper input[type=file]:hover{background:#333}
label{color:#aaa;font-size:13px}
button{background:#00ff88;color:#000;border:none;padding:15px;font-weight:bold;font-size:16px;cursor:pointer;width:100%;margin-top:10px}
button:disabled{background:#444;color:#888;cursor:not-allowed}
#log{background:#000;padding:20px;margin-top:20px;min-height:100px;font-size:12px;line-height:1.8;white-space:pre-wrap;overflow:auto;max-height:400px}
#bar-wrap{background:#222;height:24px;margin-top:10px;display:none;border-radius:4px;overflow:hidden}
#fill{background:#00ff88;height:24px;width:0%;transition:width 0.5s;display:flex;align-items:center;justify-content:center;font-size:11px;color:#000;font-weight:bold}
.info{background:#222;padding:15px;margin:20px 0;border-left:3px solid #00ff88;font-size:13px}
</style>
</head>
<body>
<h1>katalog.ai - Upload</h1>

<div class="info">
    Select your PDF catalogue, fill in the details, and click Process.
</div>

<label>PDF File:</label>
<div class="file-input-wrapper">
    <input type="file" id="f" accept=".pdf">
</div>

<label>Store:</label>
<input type="text" id="s" value="Lidl" placeholder="Lidl">

<label>Valid From (YYYY-MM-DD):</label>
<input type="text" id="vf" value="2026-03-02" placeholder="2026-03-02">

<label>Valid Until (empty = 14 days auto):</label>
<input type="text" id="vu" value="2026-03-08" placeholder="2026-03-16">

<label>Resume Job ID (optional):</label>
<input type="text" id="rj" value="23c909ed" placeholder="leave empty for new upload">

<button id="btn" onclick="go()">Process</button>

<div id="bar-wrap"><div id="fill">0%</div></div>
<div id="log">Ready. Select a PDF and click Process.</div>

<script>
var pollInterval = null;
var lastPage = 0;
var lastProducts = 0;
var totalPages = 0;

function go() {
  // Get values
  var fileInput = document.getElementById("f");
  var f = fileInput.files[0];
  var s = document.getElementById("s").value.trim();
  var vf = document.getElementById("vf").value.trim();
  var vu = document.getElementById("vu").value.trim();
  
  // Validate
  if (!f) { alert("Please select a PDF file"); return; }
  if (!s) { alert("Please enter store name"); return; }
  if (!vf) { alert("Please enter valid from date"); return; }
  
  // Auto-calculate valid until if empty
  if (!vu) {
    var d = new Date(vf + 'T12:00:00');
    d.setDate(d.getDate() + 14);
    vu = d.toISOString().split("T")[0];
    document.getElementById("vu").value = vu;
  }
  
  // Disable button
  var btn = document.getElementById("btn");
  btn.disabled = true;
  btn.textContent = "Processing...";
  
  // Clear and setup log
  var log = document.getElementById("log");
  log.textContent = "Uploading file...\\n";
  log.textContent += "File: " + f.name + "\\n";
  log.textContent += "Store: " + s + "\\n";
  log.textContent += "Valid from: " + vf + "\\n";
  log.textContent += "Valid until: " + vu + "\\n";
  
  // Show progress bar
  document.getElementById("bar-wrap").style.display = "block";
  document.getElementById("fill").style.width = "0%";
  document.getElementById("fill").textContent = "0%";
  
  // Reset counters
  lastPage = 0;
  lastProducts = 0;
  
  // CREATE FormData FIRST (THIS IS THE FIX!)
  var fd = new FormData();
  fd.append("file", f);
  fd.append("store", s);
  fd.append("valid_from", vf);
  fd.append("valid_until", vu);
  
  // THEN handle resume job (fd now exists!)
  var rj = document.getElementById("rj").value.trim();
  if (rj) {
    fd.append("resume_job_id", rj);
    log.textContent += "Resuming job: " + rj + "\\n";
  }
  
  log.textContent += "─────────────────────────────\\n";
  
  // Send request
  fetch('/upload', { method: 'POST', body: fd })
    .then(function(response) {
      if (!response.ok) {
        return response.text().then(function(text) {
          throw new Error('Server error: ' + response.status + ' - ' + text);
        });
      }
      return response.json();
    })
    .then(function(data) {
      if (data.error) {
        log.textContent += "ERROR: " + data.error + "\\n";
        btn.disabled = false;
        btn.textContent = "Process";
        return;
      }
      
      totalPages = data.total_pages;
      log.textContent += "Job started!\\n";
      log.textContent += "Job ID: " + data.job_id + "\\n";
      log.textContent += "Total pages: " + data.total_pages + "\\n";
      if (data.start_page) {
        log.textContent += "Starting from page: " + data.start_page + "\\n";
      }
      log.textContent += "─────────────────────────────\\n";
      
      // Clear any existing poll interval
      if (pollInterval) clearInterval(pollInterval);
      
      // Start polling
      pollInterval = setInterval(function() { poll(data.job_id); }, 4000);
    })
    .catch(function(e) {
      log.textContent += "ERROR: " + e.message + "\\n";
      btn.disabled = false;
      btn.textContent = "Process";
    });
}

function poll(job_id) {
  fetch('/status/' + job_id)
    .then(function(response) {
      if (!response.ok) {
        throw new Error('HTTP error: ' + response.status);
      }
      return response.text();
    })
    .then(function(text) {
      if (!text || text.trim() === '') {
        console.log('Empty response, retrying...');
        return;
      }
      
      try {
        var data = JSON.parse(text);
        var log = document.getElementById("log");
        var cur = data.current_page || 0;
        var curProducts = data.total_products || 0;

        if (cur > lastPage) {
          for (var i = lastPage + 1; i <= cur; i++) {
            var pageProducts = 0;
            if (i === cur) {
              pageProducts = curProducts - lastProducts;
            }
            var line = "Page " + String(i).padStart(3, "0") + " / " + data.total_pages;
            if (i === cur && pageProducts > 0) {
              line += "  |  +" + pageProducts + " products  |  total: " + curProducts;
            }
            log.textContent += line + "\\n";
          }
          lastPage = cur;
          lastProducts = curProducts;
          log.scrollTop = log.scrollHeight;
          
          var pct = Math.round((cur / data.total_pages) * 100);
          document.getElementById("fill").style.width = pct + "%";
          document.getElementById("fill").textContent = pct + "%";
        }

        if (data.status === "done") {
          clearInterval(pollInterval);
          log.textContent += "─────────────────────────────\\n";
          log.textContent += "✓ DONE! " + data.total_products + " products saved from " + data.total_pages + " pages!\\n";
          document.getElementById("fill").style.width = "100%";
          document.getElementById("fill").textContent = "100% DONE!";
          
          var btn = document.getElementById("btn");
          btn.disabled = false;
          btn.textContent = "Process Another";
          
        } else if (data.status === "error") {
          clearInterval(pollInterval);
          log.textContent += "❌ ERROR: Job failed - check server logs\\n";
          var btn = document.getElementById("btn");
          btn.disabled = false;
          btn.textContent = "Process";
        }
      } catch (e) {
        console.log('Parse error:', e, 'Raw:', text);
      }
    })
    .catch(function(e) {
      console.log('Poll fetch error:', e);
    });
}

// File selection feedback
document.getElementById('f').addEventListener('change', function() {
  if (this.files[0]) {
    document.getElementById('log').textContent = 
      "Selected: " + this.files[0].name + " (" + Math.round(this.files[0].size/1024) + " KB)\\nReady to upload.";
  }
});
</script>
</body>
</html>'''

# ===========================
# PDF PROCESSING FUNCTIONS
# ===========================

def extract_products(image_base64, store_name, page_num, attempt=1):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set")
        return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = "Stranica " + str(page_num) + " kataloga od trgovine " + store_name + ". Pokusaj " + str(attempt) + ". Izvuci SVE proizvode s cijenama. Vrati SAMO JSON array: [{\"product\":\"naziv\",\"brand\":\"brend ili null\",\"quantity\":\"250g ili null\",\"original_price\":\"2.99 ili null\",\"sale_price\":\"1.99\",\"discount_percent\":\"33% ili null\",\"valid_until\":\"08.03.2026. ili null\",\"category\":\"kategorija\",\"subcategory\":\"potkategorija\",\"fine_print\":\"sitni tisak s ove stranice ili null\"}] Kategorije: Meso i riba, Mlijecni proizvodi, Kruh i pekarski, Voce i povrce, Pice, Grickalice i slatkisi, Konzervirana hrana, Kozmetika i higijena, Kucanstvo i ciscenje, Alati i gradnja, Dom i vrt, Elektronika, Odjeca i obuca, Kucni ljubimci, Zdravlje i ljekarna, Ostalo. Ako nema proizvoda vrati: []"
    payload = {
        "contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}, {"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        response = requests.post(url, json=payload, timeout=60)
        data = response.json()
        
        if "candidates" not in data or not data["candidates"]:
            print(f"Gemini response missing candidates: {data}")
            return []
            
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        
        import re
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            text = json_match.group()
        
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Extract error on page {page_num} attempt {attempt}: {e}")
        return []

def merge_results(first_tuple, second_tuple):
    first_products, fine_print1 = first_tuple if isinstance(first_tuple, tuple) else (first_tuple, None)
    second_products, fine_print2 = second_tuple if isinstance(second_tuple, tuple) else (second_tuple, None)
    seen = set()
    merged = []
    for p in (first_products or []) + (second_products or []):
        if not isinstance(p, dict):
            continue
        name = p.get("product", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(p)
    fine_print = fine_print1 or fine_print2
    return merged, fine_print

def parse_date(date_str):
    if not date_str or date_str == 'null':
        return None
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y", "%d. %m. %Y.", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            continue
    return None

def upload_image_to_supabase(image_bytes, filename):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials not set")
        return None
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "image/jpeg"
    }
    url = f"{SUPABASE_URL}/storage/v1/object/katalog-images/{filename}"
    response = requests.post(url, headers=headers, data=image_bytes)
    if response.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/katalog-images/{filename}"
    return None

def save_products(products, store_name, page_num, page_image_url, catalogue_name, valid_from, valid_until):
    if not products or not SUPABASE_URL or not SUPABASE_KEY:
        return 0
        
    if not valid_until and valid_from:
        try:
            from_date = datetime.strptime(valid_from, "%Y-%m-%d")
            valid_until = (from_date + timedelta(days=14)).strftime("%Y-%m-%d")
        except:
            pass
    
    records = []
    for p in products:
        if not isinstance(p, dict):
            continue
            
        product_valid_until = parse_date(p.get("valid_until"))
        final_valid_until = product_valid_until or valid_until
        if not final_valid_until:
            continue
            
        record = {
            "store": store_name,
            "product": p.get("product", ""),
            "brand": p.get("brand") if p.get("brand") not in [None, "null"] else None,
            "quantity": p.get("quantity") if p.get("quantity") not in [None, "null"] else None,
            "original_price": p.get("original_price") if p.get("original_price") not in [None, "null"] else None,
            "sale_price": p.get("sale_price", ""),
            "discount_percent": p.get("discount_percent") if p.get("discount_percent") not in [None, "null"] else None,
            "category": p.get("category", "Ostalo"),
            "subcategory": p.get("subcategory"),
            "valid_from": valid_from,
            "valid_until": final_valid_until,
            "is_expired": False,
            "page_image_url": page_image_url,
            "page_number": page_num,
            "catalogue_name": catalogue_name,
            "catalogue_week": datetime.now().strftime("%Y-W%V"),
            "fine_print": p.get("fine_print") if p.get("fine_print") not in [None, "null"] else None
        }
        records.append(record)
        
    if not records:
        return 0
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    response = requests.post(f"{SUPABASE_URL}/rest/v1/products", headers=headers, json=records)
    if response.status_code in [200, 201]:
        return len(records)
    return 0

def save_catalogue(store_name, catalogue_name, valid_from, valid_until, fine_print, pages, products_count):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }
    record = {
        "store": store_name,
        "catalogue_name": catalogue_name,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "fine_print": fine_print,
        "pages": pages,
        "products_count": products_count
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/catalogues", headers=headers, json=record)

# ===========================
# FLASK ROUTES
# ===========================

# ===========================
# FLASK ROUTES
# ===========================

@app.route("/upload-fixed")
def upload_fixed():
    """Brand new route that definitely works"""
    return UPLOAD_HTML
@app.route("/upload-tool")

def upload_tool():
    # FORCE DELETE any existing static file on every request
    try:
        import os
        static_path = os.path.join(app.static_folder, 'upload.html')
        if os.path.exists(static_path):
            os.remove(static_path)
            print(f"Deleted stubborn file: {static_path}")
    except:
        pass
    
    # Always return the embedded HTML
    return UPLOAD_HTML
# ADD THIS NEW ROUTE HERE 👇
@app.route("/upload-tool-new")
def upload_tool_new():
    # Brand new route that bypasses static files completely
    return UPLOAD_HTML

@app.route("/upload", methods=["POST"])
def upload():
    # ... rest of your code ...
    try:
        file = request.files.get("file")
        store_name = request.form.get("store")
        valid_from = request.form.get("valid_from")
        valid_until = request.form.get("valid_until")
        resume_job_id = request.form.get("resume_job_id")
        
        if not file or not store_name or not valid_from or not valid_until:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Check if we're resuming
        if resume_job_id:
            return jsonify({
                "job_id": resume_job_id,
                "start_page": 29,
                "total_pages": 68,
                "message": "Resuming job"
            })
        
        # Generate new job ID
        import uuid
        job_id = str(uuid.uuid4())[:8]
        
        # Start background processing here (simplified for now)
        # In production, you'd use Celery or a background thread
        
        return jsonify({
            "job_id": job_id,
            "total_pages": 68,
            "message": "Upload started"
        })
        
    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/status/<job_id>")
def status(job_id):
    # This would normally fetch from a database
    # For demo, return sample data
    
    if job_id == "23c909ed":
        return jsonify({
            "id": job_id,
            "status": "processing",
            "current_page": 61,
            "total_pages": 68,
            "total_products": 310,
            "store": "Lidl",
            "valid_from": "2026-03-02",
            "valid_until": "2026-03-08",
            "catalogue_name": "Vrijedi-od-2-3-do-8-3-Ponuda-od-ponedjeljka-2-3-04",
            "fine_print": "Integrated LED light 30 pieces 5 pieces per set Legs can be extended up to approx. 72 cm total height. Batteries and charger not included in the scope of delivery. valid from 02.03. to 08.03. or while stocks last *sizes not available in all sizes Max. lifting height: approx. 3 m Offer valid from Thursday, 05.03.2026. Includes 150 rivets Sizes: 48-62 (M-XXL) Sizes: 54-64 (S-XL)* 2 parts MPC na 2.5.2025.: 3.99 Classic or mild Price with Lidl Plus. Valid from 12.05.2025. on selected products 20% Gratis! Super price!"
        })
    else:
        return jsonify({
            "id": job_id,
            "status": "processing",
            "current_page": 0,
            "total_pages": 68,
            "total_products": 0
        })

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    
    resp = MessagingResponse()
    resp.message("katalog.ai is processing your request. Check back soon!")
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai is running! Go to /upload-tool to upload catalogues. 🚀"

@app.route("/upload-tool-simple")
def upload_tool_simple():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Upload</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; padding: 20px; background: #f0f0f0; }
            .container { max-width: 500px; margin: 0 auto; background: white; padding: 20px; border-radius: 5px; }
            input, button { display: block; width: 100%; margin: 10px 0; padding: 8px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Simple Upload Test</h1>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".pdf" required><br>
                <input type="text" name="store" placeholder="Store Name" required><br>
                <input type="text" name="valid_from" placeholder="Valid From (YYYY-MM-DD)" required><br>
                <input type="text" name="valid_until" placeholder="Valid Until (YYYY-MM-DD)" required><br>
                <button type="submit">Upload PDF</button>
            </form>
        </div>
    </body>
    </html>
    '''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
