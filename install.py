"""Configure private dependencies without changing Blender's Python installation."""
import os
import sys
ROOT = os.path.dirname(__file__)
vendor = os.path.join(ROOT, "vendor")
if vendor not in sys.path:
    sys.path.append(vendor)
for directory in ("schem", "schemcache", "saves", "temp", "resourcepacks"):
    os.makedirs(os.path.join(ROOT, directory), exist_ok=True)
