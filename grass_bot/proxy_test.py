import sys
sys.path.insert(0, '/root/grass_bot')
from grass_manager import fetch_free_proxies
p = fetch_free_proxies()
print(f"TOTAL: {len(p)}")
for x in p[:10]:
    print(x)
