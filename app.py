from flask import Flask, request, jsonify, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import threading
from datetime import datetime, date, timedelta
import re

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===========================
# UPLOAD TOOL HTML
# ===========================
UPLOAD_HTML = '''<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>katalog.ai — Upload Tool</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Mono:wght@300;400;500&display=swap');
  
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  
  :root {
    --bg: #0a0a0a;
    --surface: #111111;
    --border: #222222;
    --accent: #00ff88;
    --accent2: #ff3366;
    --text: #f0f0f0;
    --muted: #666666;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Mono', monospace;
    min-height: 100vh;
    padding: 40px 20px;
  }

  .container { max-width: 800px; margin: 0 auto; }

  header { margin-bottom: 60px; }
  
  .logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 2.5rem;
    letter-spacing: -2px;
  }
  
  .logo span { color: var(--accent); }
  
  .subtitle {
    color: var(--muted);
    font-size: 0.8rem;
    margin-top: 6px;
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 2px;
    padding: 32px;
    margin-bottom: 24px;
  }

  .card-title {
    font-family: 'Syne', sans-serif;
    font-weight: 600;
    font-size: 0.7rem;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 20px;
  }

  .format-box {
    background: #0d0d0d;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    padding: 16px 20px;
    font-size: 0.8rem;
    line-height: 2;
    color: var(--muted);
    margin-bottom: 8px;
  }

  .format-box code {
    color: var(--accent);
    font-family: 'DM Mono', monospace;
  }

  .dropzone {
    border: 2px dashed var(--border);
    border-radius: 2px;
    padding: 60px 40px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
    margin-bottom: 24px;
  }

  .dropzone:hover, .dropzone.dragover {
    border-color: var(--accent);
    background: rgba(0, 255, 136, 0.03);
  }

  .dropzone input {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
    width: 100%;
    height: 100%;
  }

  .dropzone-icon {
    font-size: 3rem;
    margin-bottom: 16px;
    display: block;
  }

  .dropzone-text {
    font-family: 'Syne', sans-serif;
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 8px;
  }

  .dropzone-hint {
    font-size: 0.75rem;
    color: var(--muted);
  }

  .file-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 24px;
  }

  .file-item {
    display: flex;
    align-items: center;
    gap: 12px;
    background: #0d0d0d;
    border: 1px solid var(--border);
    padding: 12px 16px;
    font-size: 0.8rem;
  }

  .file-item .name { flex: 1; color: var(--text); }
  .file-item .store { color: var(--accent); min-width: 80px; }
  .file-item .dates { color: var(--muted); font-size: 0.7rem; }
  .file-item .status { min-width: 80px; text-align: right; }

  .status-pending { color: var(--muted); }
  .status-processing { color: #ffaa00; }
  .status-done { color: var(--accent); }
  .status-error { color: var(--accent2); }

  .btn {
    background: var(--accent);
    color: #000;
    border: none;
    padding: 16px 40px;
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 0.9rem;
    letter-spacing: 2px;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.15s ease;
    width: 100%;
  }

  .btn:hover { background: #00cc6e; }
  .btn:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }

  .progress-section { display: none; }
  .progress-section.visible { display: block; }

  .progress-bar-wrap {
    background: var(--border);
    height: 3px;
    margin: 16px 0;
    overflow: hidden;
  }

  .progress-bar {
    height: 100%;
    background: var(--accent);
    width: 0%;
    transition: width 0.3s ease;
  }

  .log {
    background: #000;
    border: 1px solid var(--border);
    padding: 20px;
    font-size: 0.75rem;
    line-height: 1.8;
    max-height: 300px;
    overflow-y: auto;
    color: var(--muted);
  }

  .log .success { color: var(--accent); }
  .log .error { color: var(--accent2); }
  .log .info { color: #888; }

  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-top: 24px;
  }

  .stat {
    background: #0d0d0d;
    border: 1px solid var(--border);
    padding: 20px;
    text-align: center;
  }

  .stat-value {
    font-family: 'Syne', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    color: var(--accent);
  }

  .stat-label {
    font-size: 0.65rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-top: 4px;
  }

  .warning {
    background: rgba(255, 51, 102, 0.05);
    border: 1px solid rgba(255, 51, 102, 0.2);
    border-left: 3px solid var(--accent2);
    padding: 12px 16px;
    font-size: 0.75rem;
    color: #ff6688;
    margin-bottom: 16px;
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">katalog<span>.ai</span></div>
    <div class="subtitle">Upload Tool — Catalogue Processor</div>
  </header>

  <div class="card">
    <div class="card-title">File naming format</div>
    <div class="format-box">
      Rename your PDFs before uploading:<br>
      <code>Konzum_2026-03-03_2026-03-09.pdf</code><br>
      <code>Lidl_2026-03-02_2026-03-08.pdf</code><br>
      <code>DM_2026-03-01_2026-03-15.pdf</code><br>
      <code>Kaufland_2026-03-03_2026-03-09.pdf</code><br>
      <br>
      Pattern: <code>StoreName_ValidFrom_ValidUntil.pdf</code>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Upload Catalogues</div>
    
    <div class="dropzone" id="dropzone">
      <input type="file" id="fileInput" multiple accept=".pdf" onchange="handleFiles(this.files)">
      <span class="dropzone-icon">📂</span>
      <div class="dropzone-text">Drop PDF catalogues here</div>
      <div class="dropzone-hint">or click to browse — multiple files supported</div>
    </div>

    <div class="file-list" id="fileList"></div>

    <button class="btn" id="uploadBtn" onclick="startUpload()" disabled>
      Process All Catalogues
    </button>
  </div>

  <div class="card progress-section" id="progressSection">
    <div class="card-title">Processing</div>
    <div id="progressText" style="font-size:0.8rem; color: var(--muted);">Initializing...</div>
    <div class="progress-bar-wrap">
      <div class="progress-bar" id="progressBar"></div>
    </div>
    <div class="log" id="log"></div>
    <div class="stats" id="stats" style="display:none">
      <div class="stat">
        <div class="stat-value" id="statFiles">0</div>
        <div class="stat-label">Catalogues</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="statProducts">0</div>
        <div class="stat-label">Products</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="statPages">0</div>
        <div class="stat-label">Pages</div>
      </div>
    </div>
  </div>
</div>

<script>
let selectedFiles = [];
let totalProducts = 0;
let totalPages = 0;

function parseFilename(filename) {
  const base = filename.replace('.pdf', '');
  const parts = base.split('_');
  if (parts.length >= 3) {
    return {
      store: parts[0],
      validFrom: parts[1],
      validUntil: parts[2],
      valid: true
    };
  }
  return { store: base, validFrom: null, validUntil: null, valid: false };
}

function handleFiles(files) {
  selectedFiles = Array.from(files);
  const fileList = document.getElementById('fileList');
  fileList.innerHTML = '';
  
  selectedFiles.forEach((file, i) => {
    const info = parseFilename(file.name);
    const item = document.createElement('div');
    item.className = 'file-item';
    item.id = 'file-' + i;
    
    if (!info.valid) {
      item.innerHTML = `
        <div class="name">${file.name}</div>
        <div class="status status-error">⚠ Bad name</div>
      `;
    } else {
      item.innerHTML = `
        <div class="name">${file.name}</div>
        <div class="store">${info.store}</div>
        <div class="dates">${info.validFrom} → ${info.validUntil}</div>
        <div class="status status-pending" id="status-${i}">Pending</div>
      `;
    }
    fileList.appendChild(item);
  });
  
  const validFiles = selectedFiles.filter(f => parseFilename(f.name).valid);
  document.getElementById('uploadBtn').disabled = validFiles.length === 0;
}

function addLog(message, type = 'info') {
  const log = document.getElementById('log');
  const line = document.createElement('div');
  line.className = type;
  line.textContent = new Date().toLocaleTimeString() + ' — ' + message;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

async function startUpload() {
  const validFiles = selectedFiles.filter(f => parseFilename(f.name).valid);
  if (validFiles.length === 0) return;
  
  document.getElementById('progressSection').classList.add('visible');
  document.getElementById('uploadBtn').disabled = true;
  totalProducts = 0;
  totalPages = 0;
  
  for (let i = 0; i < validFiles.length; i++) {
    const file = validFiles[i];
    const info = parseFilename(file.name);
    const fileIndex = selectedFiles.indexOf(file);
    
    document.getElementById('status-' + fileIndex).textContent = 'Processing...';
    document.getElementById('status-' + fileIndex).className = 'status status-processing';
    document.getElementById('progressText').textContent = `Processing ${i+1}/${validFiles.length}: ${info.store}`;
    document.getElementById('progressBar').style.width = ((i / validFiles.length) * 100) + '%';
    
    addLog(`Starting ${info.store} (${info.validFrom} to ${info.validUntil})...`);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('store', info.store);
      formData.append('valid_from', info.validFrom);
      formData.append('valid_until', info.validUntil);
      
      const response = await fetch('/upload', {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        totalProducts += result.products;
        totalPages += result.pages;
        document.getElementById('status-' + fileIndex).textContent = result.products + ' products';
        document.getElementById('status-' + fileIndex).className = 'status status-done';
        addLog(`✓ ${info.store}: ${result.products} products from ${result.pages} pages`, 'success');
      } else {
        document.getElementById('status-' + fileIndex).textContent = 'Error';
        document.getElementById('status-' + fileIndex).className = 'status status-error';
        addLog(`✗ ${info.store}: ${result.error}`, 'error');
      }
    } catch (err) {
      document.getElementById('status-' + fileIndex).textContent = 'Error';
      document.getElementById('status-' + fileIndex).className = 'status status-error';
      addLog(`✗ ${info.store}: ${err.message}`, 'error');
    }
    
    document.getElementById('statFiles').textContent = i + 1;
    document.getElementById('statProducts').textContent = totalProducts;
    document.getElementById('statPages').textContent = totalPages;
    document.getElementById('stats').style.display = 'grid';
  }
  
  document.getElementById('progressBar').style.width = '100%';
  document.getElementById('progressText').textContent = 'All catalogues processed!';
  addLog('All done! Database updated successfully.', 'success');
  document.getElementById('uploadBtn').disabled = false;
}

// Drag and drop
const dropzone = document.getElementById('dropzone');
dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  handleFiles(e.dataTransfer.files);
});
</script>
</body>
</html>'''

# ===========================
# PDF PROCESSING FUNCTIONS
# ===========================

def extract_products(image_base64, store_name, page_num, attempt=1):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = "Stranica " + str(page_num) + " kataloga od trgovine " + store_name + ". Pokusaj " + str(attempt) + ". Izvuci SVE proizvode s cijenama. Vrati SAMO JSON array: [{\"product\":\"naziv\",\"brand\":\"brend ili null\",\"quantity\":\"250g ili null\",\"original_price\":\"2.99 ili null\",\"sale_price\":\"1.99\",\"discount_percent\":\"33% ili null\",\"valid_until\":\"08.03.2026. ili null\",\"category\":\"kategorija\",\"subcategory\":\"potkategorija\",\"fine_print\":\"sitni tisak s ove stranice ili null\"}] Kategorije: Meso i riba, Mlijecni proizvodi, Kruh i pekarski, Voce i povrce, Pice, Grickalice i slatkisi, Konzervirana hrana, Kozmetika i higijena, Kucanstvo i ciscenje, Alati i gradnja, Dom i vrt, Elektronika, Odjeca i obuca, Kucni ljubimci, Zdravlje i ljekarna, Ostalo. Ako nema proizvoda vrati: []"
    payload = {
        "contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}, {"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        response = requests.post(url, json=payload, timeout=60)
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except:
        return []

def merge_results(first_tuple, second_tuple):
    first_products, fine_print1 = first_tuple if isinstance(first_tuple, tuple) else (first_tuple, None)
    second_products, fine_print2 = second_tuple if isinstance(second_tuple, tuple) else (second_tuple, None)
    seen = set()
    merged = []
    for p in (first_products or []) + (second_products or []):
        name = p.get("product", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(p)
    # Use whichever fine print we found
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
    if not products:
        return 0
    # Default valid_until = valid_from + 14 days if not provided
    if not valid_until and valid_from:
        try:
            from_date = datetime.strptime(valid_from, "%Y-%m-%d")
            valid_until = (from_date + timedelta(days=14)).strftime("%Y-%m-%d")
        except:
            pass
    records = []
    for p in products:
        product_valid_until = parse_date(p.get("valid_until"))
        final_valid_until = product_valid_until or valid_until
        if not final_valid_until:
            continue
        records.append({
            "store": store_name,
            "product": p.get("product", ""),
            "brand": p.get("brand") if p.get("brand") != "null" else None,
            "quantity": p.get("quantity") if p.get("quantity") != "null" else None,
            "original_price": p.get("original_price") if p.get("original_price") != "null" else None,
            "sale_price": p.get("sale_price", ""),
            "discount_percent": p.get("discount_percent") if p.get("discount_percent") != "null" else None,
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
        })
    if not records:
        return 0
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    response = requests.post(f"{SUPABASE_URL}/rest/v1/products", headers=headers, json=records)
    return len(records) if response.status_code in [200, 201] else 0

def save_catalogue(store_name, catalogue_name, valid_from, valid_until, fine_print, pages, products_count):
    """Save or update catalogue record with fine print"""
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

@app.route("/upload-tool")
def upload_tool():
    return render_template_string(UPLOAD_HTML)

@app.route("/upload", methods=["POST"])
def upload():
    try:
        import fitz
    except:
        return jsonify({"success": False, "error": "PyMuPDF not installed"})
    
    try:
        file = request.files.get("file")
        store_name = request.form.get("store")
        valid_from = request.form.get("valid_from")
        valid_until = request.form.get("valid_until")
        
        if not file or not store_name or not valid_from or not valid_until:
            return jsonify({"success": False, "error": "Missing required fields"})
        
        # Save file temporarily
        temp_path = f"/tmp/{file.filename}"
        file.save(temp_path)
        
        # Process PDF
        catalogue_name = file.filename.replace(".pdf", "")
        doc = fitz.open(temp_path)
        total_pages = len(doc)
        total_products = 0
        catalogue_fine_print = None
        
        for page_num in range(total_pages):
            page = doc[page_num]
            mat = fitz.Matrix(2.5, 2.5)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg")
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            
            # Upload page image
            page_filename = f"{store_name.lower()}_page_{str(page_num+1).zfill(3)}.jpg"
            page_image_url = upload_image_to_supabase(img_bytes, page_filename)
            
            # Double pass extraction
            first_pass = extract_products(img_base64, store_name, page_num + 1, attempt=1)
            second_pass = extract_products(img_base64, store_name, page_num + 1, attempt=2)
            merged, page_fine_print = merge_results(first_pass, second_pass)
            if page_fine_print:
                catalogue_fine_print = catalogue_fine_print + " " + page_fine_print if catalogue_fine_print else page_fine_print
            
            if merged:
                saved = save_products(merged, store_name, page_num + 1, page_image_url, catalogue_name, valid_from, valid_until)
                total_products += saved
        
        doc.close()
        os.remove(temp_path)
        
        # Save catalogue record with accumulated fine print
        save_catalogue(store_name, catalogue_name, valid_from, valid_until, catalogue_fine_print, total_pages, total_products)
        
        return jsonify({
            "success": True,
            "products": total_products,
            "pages": total_pages
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ===========================
# WHATSAPP BOT
# ===========================

def get_products():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    today = date.today().strftime("%Y-%m-%d")
    future = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    active = requests.get(f"{SUPABASE_URL}/rest/v1/products?valid_from=lte.{today}&valid_until=gte.{today}&is_expired=eq.false&limit=300&order=store", headers=headers)
    upcoming = requests.get(f"{SUPABASE_URL}/rest/v1/products?valid_from=gt.{today}&valid_from=lte.{future}&is_expired=eq.false&limit=100&order=valid_from", headers=headers)
    catalogues = requests.get(f"{SUPABASE_URL}/rest/v1/catalogues?valid_until=gte.{today}&select=store,fine_print", headers=headers)
    
    catalogue_fine_prints = {}
    if catalogues.status_code == 200:
        for c in catalogues.json():
            if c.get("fine_print"):
                catalogue_fine_prints[c["store"]] = c["fine_print"]
    
    return active.json() if active.status_code == 200 else [], upcoming.json() if upcoming.status_code == 200 else [], catalogue_fine_prints

def get_or_create_user(phone):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    response = requests.get(f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}&limit=1", headers=headers)
    if response.status_code == 200 and response.json():
        return response.json()[0]
    new_user = {"phone": phone, "total_searches": 0, "money_saved": 0}
    create = requests.post(f"{SUPABASE_URL}/rest/v1/users", headers={**headers, "Prefer": "return=representation"}, json=new_user)
    return create.json()[0] if create.status_code in [200, 201] else new_user

def update_user(phone, updates):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    requests.patch(f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}", headers=headers, json=updates)

def format_products_for_ai(active, upcoming, fine_prints={}):
    result = ""
    if active:
        result += "=== AKTIVNE AKCIJE DANAS ===\n"
        for p in active:
            result += f"{p.get('store')} | {p.get('product')}"
            if p.get('brand'): result += f" ({p.get('brand')})"
            if p.get('quantity'): result += f" {p.get('quantity')}"
            result += f" | {p.get('sale_price')}"
            if p.get('original_price'): result += f" (bilo {p.get('original_price')})"
            if p.get('fine_print'): result += f" | Napomena: {p.get('fine_print')}"
            result += f" | do: {p.get('valid_until')}\n"
    if upcoming:
        result += "\n=== NADOLAZECE AKCIJE ===\n"
        for p in upcoming:
            result += f"{p.get('store')} | {p.get('product')}"
            if p.get('brand'): result += f" ({p.get('brand')})"
            result += f" | {p.get('sale_price')}"
            result += f" | POCINJE: {p.get('valid_from')} do {p.get('valid_until')}\n"
    if fine_prints:
        result += "\n=== NAPOMENE PO TRGOVINAMA ===\n"
        for store, fp in fine_prints.items():
            result += f"{store}: {fp}\n"
    return result or "Baza je prazna."

def ask_gemini(user_message, products_context, user_profile):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    today = date.today().strftime("%d.%m.%Y.")
    user_context = ""
    if user_profile.get('name'): user_context += f"Ime: {user_profile.get('name')}\n"
    if user_profile.get('preferred_stores'): user_context += f"Preferira: {user_profile.get('preferred_stores')}\n"
    
    prompt = "Ti si katalog.ai - osobni shopping asistent za Hrvatsku. Danas je " + today + ". " + (("Korisnik: " + user_context) if user_context else "") + " KATALOZI: " + products_context + " PRAVILA: 1. Ako postoji aktivna akcija - reci gdje i po kojoj cijeni. 2. Ako nema aktivne ali ima nadolazece akcije - reci kada pocinje i gdje. 3. Maksimalno 4-5 proizvoda. 4. NIKAD ne koristi markdown zvjezdice ili bullet points - samo obican tekst. 5. Budi kao prijatelj koji zna sve cijene. 6. Za ostala pitanja odgovori normalno. Korisnik pita: " + user_message
    
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    response = requests.post(url, json=payload, timeout=30)
    data = response.json()
    try:
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return "Oprostite, doslo je do greske. Pokusajte ponovno!"
    except:
        return "Oprostite, doslo je do greske. Pokusajte ponovno!"

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    user = get_or_create_user(sender)
    active, upcoming, fine_prints = get_products()
    products_context = format_products_for_ai(active, upcoming, fine_prints)
    ai_response = ask_gemini(incoming_message, products_context, user)
    update_user(sender, {"total_searches": (user.get("total_searches") or 0) + 1, "last_active": date.today().strftime("%Y-%m-%d")})
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai is running! Go to /upload-tool to upload catalogues. 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
