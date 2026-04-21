import os

files = [
    "src/lumina/services/ingestion/routes.py",
    "src/lumina/staging/staging_service.py",
    "src/lumina/session/blackbox_triggers.py",
]

for path in files:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    original = content
    content = content.replace('"domain_authority"', '"admin"')
    content = content.replace("'domain_authority'", "'admin'")
    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated: {path}")
    else:
        print(f"No change: {path}")
