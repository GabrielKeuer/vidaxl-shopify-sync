import csv
import requests
from datetime import datetime
from io import StringIO

# VidaXL CSV URL
VIDAXL_URL = "https://transport.productsup.io/de8254c69e698a08e904/channel/188044/vidaXL_dk_dropshipping.csv"

# Pris markup settings
PRICE_MARKUP = 1.60  # 60% markup

def calculate_retail_price(b2b_price):
    """Beregn salgspris med markup og afrunding til 9"""
    try:
        import math
        price = float(b2b_price) * PRICE_MARKUP
        # Rund op til nærmeste 10, træk 1 fra så det ender på 9
        return int(10 * math.ceil(price / 10) - 1)
    except:
        return 0

print(f"Starting VidaXL transformation - {datetime.now()}")

# Download VidaXL CSV
print("Downloading VidaXL feed...")
response = requests.get(VIDAXL_URL)
response.raise_for_status()

# Parse input
reader = csv.DictReader(StringIO(response.text))

# Prepare output
output_rows = []
processed = 0

for row in reader:
    sku = row.get('SKU', '')
    b2b_price = row.get('B2B price', '0')
    stock = row.get('Stock', '0')
    
    if sku:  # Only process if SKU exists
        output_rows.append({
        'Variant SKU': sku,
        'Variant Price': calculate_retail_price(b2b_price),
        'Variant Cost': b2b_price,  # ← TILFØJ DENNE LINJE
        'Variant Inventory Qty': stock,
        'Variant Command': 'UPDATE'
        })
        processed += 1

# Write output
with open('matrixify_update.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['Variant SKU', 'Variant Price', 'Variant Cost', 'Variant Inventory Qty', 'Variant Command'])
    writer.writeheader()
    writer.writerows(output_rows)

print(f"Processed {processed} products")
print(f"Output saved to matrixify_update.csv")
