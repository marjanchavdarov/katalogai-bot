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
  console.log('✅ FIXED go function running');
  
  // Get elements
  var fileInput = document.getElementById('f');
  var storeInput = document.getElementById('s');
  var fromInput = document.getElementById('vf');
  var untilInput = document.getElementById('vu');
  var jobInput = document.getElementById('rj');
  
  // Get values
  var f = fileInput?.files[0];
  var s = storeInput?.value.trim();
  var vf = fromInput?.value.trim();
  var vu = untilInput?.value.trim();
  var rj = jobInput?.value.trim();
  
  // Validate
  if (!f) { alert('Please select a PDF file'); return; }
  if (!s) { alert('Please enter store name'); return; }
  if (!vf) { alert('Please enter valid from date'); return; }
  
  // Auto-calculate valid until if empty
  if (!vu) {
    var d = new Date(vf + 'T12:00:00');
    d.setDate(d.getDate() + 14);
    vu = d.toISOString().split('T')[0];
    if (untilInput) untilInput.value = vu;
  }
  
  // Disable button
  var btn = document.getElementById('btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Processing...';
  }
  
  // Setup log
  var log = document.getElementById('log');
  if (log) {
    log.textContent = 'Uploading file...\n';
    log.textContent += 'File: ' + (f?.name || 'unknown') + '\n';
    log.textContent += 'Store: ' + s + '\n';
    log.textContent += 'Valid from: ' + vf + '\n';
    log.textContent += 'Valid until: ' + vu + '\n';
  }
  
  // Show progress bar
  var barWrap = document.getElementById('bar-wrap');
  var fill = document.getElementById('fill');
  if (barWrap) barWrap.style.display = 'block';
  if (fill) {
    fill.style.width = '0%';
    fill.textContent = '0%';
  }
  
  // Reset globals
  lastPage = 0;
  lastProducts = 0;
  
  // CREATE FormData FIRST - THIS IS THE FIX!
  var fd = new FormData();
  fd.append('file', f);
  fd.append('store', s);
  fd.append('valid_from', vf);
  fd.append('valid_until', vu);
  
  // THEN add resume job ID if exists
  if (rj) {
    fd.append('resume_job_id', rj);
    if (log) log.textContent += 'Resuming job: ' + rj + '\n';
  }
  
  if (log) log.textContent += '─────────────────────────────\n';
  
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
        if (log) log.textContent += 'ERROR: ' + data.error + '\n';
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Process';
        }
        return;
      }
      
      if (log) {
        log.textContent += 'Job started!\n';
        log.textContent += 'Job ID: ' + data.job_id + '\n';
        log.textContent += 'Total pages: ' + data.total_pages + '\n';
        if (data.start_page) {
          log.textContent += 'Starting from page: ' + data.start_page + '\n';
        }
        log.textContent += '─────────────────────────────\n';
      }
      
      totalPages = data.total_pages;
      
      // Clear any existing poll interval
      if (pollInterval) clearInterval(pollInterval);
      
      // Start polling
      pollInterval = setInterval(function() { poll(data.job_id); }, 4000);
    })
    .catch(function(err) {
      if (log) log.textContent += 'ERROR: ' + err.message + '\n';
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Process';
      }
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
        var log = document.getElementById('log');
        var cur = data.current_page || 0;
        var curProducts = data.total_products || 0;

        if (cur > lastPage) {
          for (var i = lastPage + 1; i <= cur; i++) {
            var pageProducts = 0;
            if (i === cur) {
              pageProducts = curProducts - lastProducts;
            }
            var line = 'Page ' + String(i).padStart(3, '0') + ' / ' + data.total_pages;
            if (i === cur && pageProducts > 0) {
              line += '  |  +' + pageProducts + ' products  |  total: ' + curProducts;
            }
            if (log) log.textContent += line + '\n';
          }
          lastPage = cur;
          lastProducts = curProducts;
          if (log) log.scrollTop = log.scrollHeight;
          
          var pct = Math.round((cur / data.total_pages) * 100);
          var fill = document.getElementById('fill');
          if (fill) {
            fill.style.width = pct + '%';
            fill.textContent = pct + '%';
          }
        }

        if (data.status === 'done') {
          clearInterval(pollInterval);
          if (log) {
            log.textContent += '─────────────────────────────\n';
            log.textContent += '✓ DONE! ' + data.total_products + ' products saved from ' + data.total_pages + ' pages!\n';
          }
          var fill = document.getElementById('fill');
          if (fill) {
            fill.style.width = '100%';
            fill.textContent = '100% DONE!';
          }
          
          var btn = document.getElementById('btn');
          if (btn) {
            btn.disabled = false;
            btn.textContent = 'Process Another';
          }
          
        } else if (data.status === 'error') {
          clearInterval(pollInterval);
          if (log) log.textContent += '❌ ERROR: Job failed - check server logs\n';
          var btn = document.getElementById('btn');
          if (btn) {
            btn.disabled = false;
            btn.textContent = 'Process';
          }
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
    var log = document.getElementById('log');
    if (log) {
      log.textContent = 'Selected: ' + this.files[0].name + ' (' + Math.round(this.files[0].size/1024) + ' KB)\nReady to upload.';
    }
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

def get_page_image_url(store, catalogue_name, page_num):
    """Generate URL for catalog page image from organized folders"""
    bucket = "katalog-images"
    store_clean = store.lower().replace(' ', '_')
    
    # Extract date from catalogue name
    import re
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', catalogue_name)
    if date_match:
        date_folder = date_match.group(1)
    else:
        # Fallback - you might want to store date in database
        date_folder = "2026-03-04"  # default
    
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{store_clean}/{date_folder}/page_{str(page_num).zfill(3)}.jpg"

def parse_date(date_str):
    if not date_str or date_str == 'null':
        return None
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y", "%d. %m. %Y.", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            continue
    return None

def upload_image_to_supabase(image_bytes, store_name, catalogue_name, page_num):
    """Upload image to organized folders"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials not set")
        return None
    
    bucket_name = "katalog-images"
    
    # Clean store name
    store_clean = store_name.lower().replace(' ', '_')
    
    # Extract date from catalogue name
    import re
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', catalogue_name)
    if date_match:
        date_folder = date_match.group(1)
    else:
        from datetime import datetime
        date_folder = datetime.now().strftime("%Y-%m-%d")
    
    # Create path: store/date/page_XXX.jpg
    folder_path = f"{store_clean}/{date_folder}"
    filename = f"page_{str(page_num).zfill(3)}.jpg"
    full_path = f"{folder_path}/{filename}"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "image/jpeg"
    }
    
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket_name}/{full_path}"
    response = requests.post(url, headers=headers, data=image_bytes)
    
    if response.status_code in [200, 201]:
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{full_path}"
        print(f"✅ Image uploaded to folder: {full_path}")
        return public_url
    
    print(f"❌ Upload failed: {response.status_code}")
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

@app.route("/upload-fixed")
def upload_fixed():
    """Brand new route that definitely works"""
    return UPLOAD_HTML

@app.route("/upload-tool")
def upload_tool():
    # Try to delete any stubborn static file (optional)
    try:
        import os
        static_path = os.path.join(app.static_folder, 'upload.html')
        if os.path.exists(static_path):
            os.remove(static_path)
            print(f"Deleted stubborn file: {static_path}")
    except:
        pass
    return UPLOAD_HTML

@app.route("/upload-tool-new")
def upload_tool_new():
    return UPLOAD_HTML

@app.route("/upload", methods=["POST"])
def upload():
    def generate():
        try:
            file = request.files.get("file")
            store_name = request.form.get("store")
            valid_from = request.form.get("valid_from")
            valid_until = request.form.get("valid_until")
            resume_job_id = request.form.get("resume_job_id")

            if not file or not store_name or not valid_from or not valid_until:
                yield json.dumps({"type": "error", "message": "Missing required fields"}) + "\n"
                return

            # For now, we ignore resume_job_id (you can implement job queue later)

            # Save PDF temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                file.save(tmp.name)
                temp_path = tmp.name

            catalogue_name = os.path.splitext(file.filename)[0]

            # Convert PDF to images (dpi=150 for speed)
            try:
                images = convert_from_path(temp_path, dpi=150)
                total_pages = len(images)
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"PDF conversion failed: {str(e)}"}) + "\n"
                os.unlink(temp_path)
                return

            total_products = 0
            catalogue_fine_print = None

            yield json.dumps({"type": "start", "pages": total_pages}) + "\n"

            for page_num in range(total_pages):
                try:
                    img = images[page_num]

                    # Convert PIL image to bytes
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=85)
                    img_bytes = img_byte_arr.getvalue()
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                    # Upload image to Supabase (new folder structure)
                    page_image_url = upload_image_to_supabase(
                        img_bytes,
                        store_name,
                        catalogue_name,
                        page_num + 1
                    )

                    # Two attempts to extract products
                    first_pass = extract_products(img_base64, store_name, page_num + 1, attempt=1)
                    second_pass = extract_products(img_base64, store_name, page_num + 1, attempt=2)
                    merged, page_fine_print = merge_results(first_pass, second_pass)

                    if page_fine_print:
                        catalogue_fine_print = (catalogue_fine_print + " " + page_fine_print) if catalogue_fine_print else page_fine_print

                    saved = 0
                    if merged:
                        saved = save_products(
                            merged,
                            store_name,
                            page_num + 1,
                            page_image_url,
                            catalogue_name,
                            valid_from,
                            valid_until
                        )
                        total_products += saved

                    yield json.dumps({
                        "type": "page",
                        "page": page_num + 1,
                        "total_pages": total_pages,
                        "products_found": len(merged) if merged else 0,
                        "products_saved": saved,
                        "total_products": total_products
                    }) + "\n"

                except Exception as page_error:
                    print(f"Page {page_num+1} error: {page_error}")
                    yield json.dumps({"type": "page_error", "page": page_num+1, "error": str(page_error)}) + "\n"
                    continue

            # Cleanup temp file
            os.unlink(temp_path)

            # Save catalogue summary
            if total_products > 0:
                save_catalogue(
                    store_name,
                    catalogue_name,
                    valid_from,
                    valid_until,
                    catalogue_fine_print,
                    total_pages,
                    total_products
                )

            yield json.dumps({
                "type": "done",
                "products": total_products,
                "pages": total_pages
            }) + "\n"

        except Exception as e:
            print(f"Upload error: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return app.response_class(generate(), mimetype="application/x-ndjson")

@app.route("/status/<job_id>")
def status(job_id):
    # For now, return mock data; you would normally query a job database.
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
