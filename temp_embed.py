import os
import base64
import re

def get_b64(path):
    if not os.path.exists(path):
        return None
    # Skip large files > 300KB
    if os.path.getsize(path) > 300000:
        return None
        
    with open(path, 'rb') as f:
        ext = os.path.splitext(path)[1].lower()[1:]
        if ext == 'jpg': ext = 'jpeg'
        mime = f"image/{ext}"
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('utf-8')}"

target_files = ['index.html']
images_dir = 'images'

image_map = {}
if os.path.exists(images_dir):
    for f in os.listdir(images_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            b64 = get_b64(os.path.join(images_dir, f))
            if b64:
                image_map[f'images/{f}'] = b64
                image_map[f'/images/{f}'] = b64

for target in target_files:
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()
    
    modified = False
    for path, b64 in image_map.items():
        pattern = f'src=["\']?{re.escape(path)}["\']?'
        replacement = f'src="{b64}"'
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            modified = True
            
    if modified:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {target}")
