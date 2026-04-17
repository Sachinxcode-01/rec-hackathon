import os

file_path = 'app.py'
search_strings = ['HACKTHEPLANET2026', 'RECKON-GUEST-5G']

found = False
with open(file_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        for s in search_strings:
            if s in line:
                print(f"Found '{s}' at line {i}: {line.strip()}")
                found = True

if not found:
    print("No old wifi strings found in app.py")
