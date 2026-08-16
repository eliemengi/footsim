import sys

with open('static/script.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if '// Form logic' in line:
        start_idx = i
    if '// Init' in line:
        end_idx = i

if start_idx == -1 or end_idx == -1:
    print("Could not find blocks")
    sys.exit(1)

print(f"Found from {start_idx} to {end_idx}")

auth_code = lines[start_idx:end_idx]
with open('auth_section.js', 'w', encoding='utf-8') as f:
    f.writelines(auth_code)

