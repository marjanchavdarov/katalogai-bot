from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import threading
from datetime import datetime, date, timedelta
import re
import io

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===========================
# UPLOAD TOOL HTML (embedded as fallback)
# ===========================
UPLOAD_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>katalog.ai Upload</title>
<style>
body { font-family: monospace; background: #111; color: #eee; padding: 40px; max-width: 700px; margin: 0 auto; }
h1 { color: #00ff88; }
.info { background: #222; padding: 15px; margin: 20px 0; border-left: 3px solid #00ff88; font-size: 13px; }
input[type=file] { display: block; margin: 20px 0; color: #eee; font-size: 14px; }
input[type=text] { background: #222; border: 1px solid #444; color: #eee; padding: 8px; width: 100%; margin: 5px 0 15px 0; font-family: monospace; }
label { color: #aaa; font-size: 13px; }
button { background: #00ff88; color: #000; border: none; padding: 15px 30px; font-weight: bold; font-size: 16px; cursor: pointer; width: 100%; margin-top: 10px; }
button:disabled { background: #444; color: #888; cursor: not-allowed; }
#log { background: #000; padding: 20px; margin-top: 20px; min-height: 100px; font-size: 12px; line-height: 1.8; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>katalog.ai — Upload Tool</h1>

<div class="info">
Select your PDF catalogue, fill in the details, and click Process.<br>
No need to rename files — just fill in the form!
</div>

<label>PDF Catalogue:</label>
<input type="file" id="fileInput" accept=".pdf">

<label>Store Name:</label>
<input type="text" id="storeName" placeholder="e.g. Lidl, Konzum, DM">

<label>Valid From (YYYY-MM-DD):</label>
<input type="text" id="validFrom" placeholder="e.g. 2026-03-02">

<label>Valid Until (YYYY-MM-DD, leave empty for 14 days):</label>
<input type="text" id="validUntil" placeholder="e.g. 2026-03-16 (optional)">

<button id="btn" onclick="startUpload()">Process Catalogue</button>

<div id="log">Waiting for upload...</div>

<script>
document.getElementById("fileInput").addEventListener("change", function() {
    const f = this.files[0];
    if (f) {
        document.getElementById("log").textContent = "File selected: " + f.name + " (" + Math.round(f.size/1024) + " KB)";
    }
});

async function startUpload() {
    const fileInput = document.getElementById("fileInput");
    const store = document.getElementById("storeName").value.trim();
    const validFrom = document.getElementById("validFrom").value.trim();
    let validUntil = document.getElementById("validUntil").value.trim();
    
    if (!fileInput.files[0]) { alert("Please select a PDF file!"); return; }
    if (!store) { alert("Please enter store name!"); return; }
    if (!validFrom) { alert("Please enter valid from date!"); return; }
    
    // Default 14 days if no end date
    if (!validUntil) {
        const from = new Date(validFrom);
        from.setDate(from.getDate() + 14);
        validUntil = from.toISOString().split("T")[0];
    }
    
    const btn = document.getElementById("btn");
    btn.disabled = true;
    btn.textContent = "Processing...";
    
    const log = document.getElementById("log");
    log.textContent = "Starting upload...\\n";
    
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("store", store);
    formData.append("valid_from", validFrom);
    formData.append("valid_until", validUntil);
    
    try {
        const response = await fetch("/upload", { method: "POST", body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.type === "start") {
                        log.textContent += "Total pages: " + data.pages + "\\n";
                    } else if (data.type === "page") {
                        log.textContent += "Page " + data.page + "/" + data.total_pages + ": " + data.products_found + " products\\n";
                        log.scrollTop = log.scrollHeight;
                    } else if (data.type === "done") {
                        log.textContent += "\\n✓ DONE! " + data.products + " products saved from " + data.pages + " pages!\\n";
                        btn.textContent = "Process Another Catalogue";
                        btn.disabled = false;
                    } else if (data.type === "error") {
                        log.textContent += "ERROR: " + data.message + "\\n";
                        btn.disabled = false;
                        btn.textContent = "Try Again";
                    } else if (data.type === "page_error") {
                        log.textContent += "Page " + data.page + " error: " + data.error + "\\n";
                    }
                } catch(e) {}
            }
        }
    } catch(err) {
        log.textContent += "ERROR: " + err.message + "\\n";
        btn.disabled = false;
        btn.textContent = "Try Again";
    }
}
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
    except Exception as e:
        print(f"Extract error: {e}")
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
    # Try to serve static file first, fallback to embedded HTML
    try:
        return app.send_static_file("upload.html")
    except:
        return UPLOAD_HTML

@app.route("/upload", methods=["POST"])
def upload():
    try:
        from pdf2image import convert_from_path
        from PIL import Image
    except ImportError:
        return jsonify({"success": False, "error": "pdf2image or PIL not installed. Please add them to requirements.txt"})
    
    def generate():
        try:
            file = request.files.get("file")
            store_name = request.form.get("store")
            valid_from = request.form.get("valid_from")
            valid_until = request.form.get("valid_until")
            
            if not file or not store_name or not valid_from or not valid_until:
                yield json.dumps({"type": "error", "message": "Missing required fields"}) + "\n"
                return
            
            # Save file temporarily
            temp_path = f"/tmp/{datetime.now().timestamp()}_{file.filename}"
            file.save(temp_path)
            
            catalogue_name = file.filename.replace(".pdf", "")
            
            # Convert PDF to images
            try:
                images = convert_from_path(temp_path, dpi=200)
                total_pages = len(images)
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"PDF conversion failed: {str(e)}"}) + "\n"
                return
            
            total_products = 0
            catalogue_fine_print = None
            
            yield json.dumps({"type": "start", "pages": total_pages}) + "\n"
            
            for page_num in range(total_pages):
                try:
                    # Get image from converted PDF
                    img = images[page_num]
                    
                    # Convert PIL Image to bytes
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    img_bytes = img_byte_arr.getvalue()
                    
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                    
                    page_filename = f"{store_name.lower()}_page_{str(page_num+1).zfill(3)}_{datetime.now().strftime('%Y%m%d')}.jpg"
                    page_image_url = upload_image_to_supabase(img_bytes, page_filename)
                    
                    first_pass = extract_products(img_base64, store_name, page_num + 1, attempt=1)
                    second_pass = extract_products(img_base64, store_name, page_num + 1, attempt=2)
                    merged, page_fine_print = merge_results(first_pass, second_pass)
                    
                    if page_fine_print:
                        catalogue_fine_print = (catalogue_fine_print + " " + page_fine_print) if catalogue_fine_print else page_fine_print
                    
                    saved = 0
                    if merged:
                        saved = save_products(merged, store_name, page_num + 1, page_image_url, catalogue_name, valid_from, valid_until)
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
            
            # Clean up
            try:
                os.remove(temp_path)
            except:
                pass
            
            save_catalogue(store_name, catalogue_name, valid_from, valid_until, catalogue_fine_print, total_pages, total_products)
            
            yield json.dumps({
                "type": "done",
                "products": total_products,
                "pages": total_pages
            }) + "\n"
            
        except Exception as e:
            print(f"Upload error: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
    
    return app.response_class(generate(), mimetype="application/x-ndjson")

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

@app.route("/upload-tool")
def upload_tool():
    return UPLOAD_HTML

@app.route("/upload-tool-simple")
def upload_tool_simple():
    return '''
    <!DOCTYPE html>
    <html>
    <head><title>Simple Upload</title></head>
    <body>
        <h1>Simple Upload Test</h1>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file"><br><br>
            <input type="text" name="store" placeholder="Store Name"><br><br>
            <input type="text" name="valid_from" placeholder="Valid From (YYYY-MM-DD)"><br><br>
            <input type="text" name="valid_until" placeholder="Valid Until (YYYY-MM-DD)"><br><br>
            <button type="submit">Upload PDF</button>
        </form>
    </body>
    </html>
    '''


