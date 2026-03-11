import os

with open('main.py', 'r') as f:
    main_content = f.read()

with open('extra_handlers.py', 'r') as f:
    extra_content = f.read()

# Find the insertion point
insert_marker = "# --- VOICE RECOGNITION ---"
if insert_marker in main_content:
    parts = main_content.split(insert_marker)
    new_content = parts[0] + extra_content + "\n" + insert_marker + parts[1]
    
    with open('main.py', 'w') as f:
        f.write(new_content)
    print("Successfully merged.")
else:
    print("Marker not found.")
