import os
import re

def clean_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find sequences of ═ or ─ (at least 2 in a row) and replace with standard -
    new_content = re.sub(r'[--]{2,}', lambda m: '-' * len(m.group(0)), content)
    
    # Also catch emojis if there are any robot emojis left in text outputs
    new_content = new_content.replace('', '')

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Cleaned {filepath}")

def main():
    base_dir = r"c:\Users\jayesh\Desktop\aemptyfolder\trade"
    for root, dirs, files in os.walk(base_dir):
        if '.git' in root or '.venv' in root or '__pycache__' in root or 'trading_model.egg-info' in root:
            continue
        for file in files:
            if file.endswith(('.h', '.c', '.java', '.sh', '.md', '.py', '.txt', '.yaml', '.xml')):
                clean_file(os.path.join(root, file))

if __name__ == "__main__":
    main()
