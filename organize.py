import requests
import os
import re

SUPABASE_URL = "https://kowvowrmtzzbbkgbfgsk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtvd3Zvd3JtdHp6YmJrZ2JmZ3NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzMjMzNzUsImV4cCI6MjA4Nzg5OTM3NX0.Y8vowp5mP1h_Im1Qt_dTH7gNTO66-OJla5fYV9DB-xU"

# Step 1: Get all files
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
files = requests.post(f"{SUPABASE_URL}/storage/v1/object/list/katalog-images", 
                      headers=headers, json={"limit": 1000}).json()

print(f"Found {len(files)} files")

# Step 2: Move each file to its folder
for f in files:
    name = f['name']
    if name == '.emptyFolderPlaceholder': continue
    
    # Determine folder
    if 'kaufland' in name:
        if '04-03-2026-10-03-2026-04' in name: folder = 'kaufland/2026-03-04'
        elif '04-03-2026-10-03-2026-05' in name: folder = 'kaufland/2026-03-05'
        else: folder = 'kaufland/2026-03-06'
    elif 'konzum' in name: folder = 'konzum/2026-03-04'
    elif 'lidl' in name:
        if '21-21' in name: folder = 'lidl/2026-03-06'
        else: folder = 'lidl/2026-03-02'
    elif 'spar' in name: folder = 'spar/2026-03-04'
    elif 'studenac' in name: folder = 'studenac/2026-03-04'
    else: continue
    
    # Get page number
    page = re.search(r'page_(\d+)', name).group(1).zfill(3)
    new_path = f"{folder}/page_{page}.jpg"
    
    # Download and upload
    img = requests.get(f"{SUPABASE_URL}/storage/v1/object/public/katalog-images/{name}").content
    r = requests.post(f"{SUPABASE_URL}/storage/v1/object/katalog-images/{new_path}", 
                      headers={**headers, "Content-Type": "image/jpeg"}, data=img)
    
    print(f"✅ {name} -> {new_path}" if r.ok else f"❌ Failed: {name}")

print("🎉 Done!")
