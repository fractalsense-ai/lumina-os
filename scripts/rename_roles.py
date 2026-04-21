import os

test_dir = "tests"
replacements = [
    ("DOMAIN_AUTHORITY_ROLES", "DOMAIN_ADMIN_ROLES"),
    ('"domain_authority"', '"admin"'),
    ("'domain_authority'", "'admin'"),
    ('"it_support"', '"super_admin"'),
    ("'it_support'", "'super_admin'"),
    ('"qa"', '"operator"'),
    ("'qa'", "'operator'"),
    ('"auditor"', '"half_operator"'),
    ("'auditor'", "'half_operator'"),
    ("actor_role=\"admin\"", "actor_role=\"admin\""),  # already correct no-op
    ('map_role_to_actor_role("admin") == "admin"', 'map_role_to_actor_role("admin") == "domain_authority"'),
]

changed = []
for fname in os.listdir(test_dir):
    if not fname.endswith(".py"):
        continue
    path = os.path.join(test_dir, fname)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    original = content
    for old, new in replacements:
        content = content.replace(old, new)
    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        changed.append(fname)

print("Changed:", changed)
