import requests, re
resp = requests.get("https://finanzasdigital.com/", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
articulo_match = re.search(r'href="(https://finanzasdigital\.com/tasa-de-cambio-bcv[^"]*)"', resp.text)
if articulo_match:
    url = articulo_match.group(1)
    print(f"Articulo: {url}")
    resp2 = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    match = re.search(r'Tasa de Cambio BCV.*?:\s*([\d.,]+)\s*Bs/USD', resp2.text)
    if match:
        tasa = float(match.group(1).replace('.', '').replace(',', '.'))
        print(f"Tasa BCV: {tasa:.2f} VES/USD")
    else:
        print("No match en articulo")
else:
    print("No se encontro articulo BCV")
