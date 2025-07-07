import csv
import requests
import pandas as pd
from datetime import datetime
from io import StringIO
import os

VIDAXL_URL = "https://transport.productsup.io/de8254c69e698a08e904/channel/188044/vidaXL_dk_dropshipping.csv"
PRICE_MARKUP = 1.60

def calculate_retail_price(b2b_price):
    try:
        import math
        price = float(b2b_price) * PRICE_MARKUP
        return int(10 * math.ceil(price / 10) - 1)
    except:
        return 0

print(f"Starting VidaXL DELTA transformation - {datetime.now()}")

response = requests.get(VIDAXL_URL)
response.raise_for_status()
current_data = pd.read_csv(StringIO(response.text))
print(f"Loaded {len(current_data)} products from VidaXL")

current_data['Retail_Price'] = current_data['B2B price'].apply(calculate_retail_price)
current_data['SKU'] = current_data['SKU'].astype(str)

if os.path.exists('last_prices.csv'):
    print("Loading previous prices...")
    last_prices = pd.read_csv('last_prices.csv', dtype={'SKU': str})

    merged = current_data.merge(
        last_prices[['SKU', 'Retail_Price', 'Stock']],
        on='SKU',
        how='left',
        suffixes=('_new', '_old')
    )
    price_changed = merged['Retail_Price_new'] != merged['Retail_Price_old']
    stock_changed = merged['Stock_new'] != merged['Stock_old']
    is_new = merged['Retail_Price_old'].isna()
    changes = merged[price_changed | stock_changed | is_new]
    print(f"Found {len(changes)} products with changes")
else:
    print("No previous data found - processing all products")
    changes = current_data
    changes['Stock_new'] = changes['Stock']

# --- HER ER DIT OUTPUT FORMAT OPDATERET TIL VARIANT COMMAND ---
if len(changes) > 0:
    output_rows = []
    for _, row in changes.iterrows():
        output_rows.append({
            'Variant SKU': row['SKU'],
            'Variant Price': row['Retail_Price_new'] if 'Retail_Price_new' in row else row['Retail_Price'],
            'Variant Cost': row['B2B price'],
            'Variant Inventory Qty': row['Stock_new'] if 'Stock_new' in row else row['Stock'],
            'Variant Command': 'UPDATE'     # <-- RIGTIGT FELTNAVN
        })

    with open('matrixify_delta_update.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Variant SKU',
            'Variant Price',
            'Variant Cost',
            'Variant Inventory Qty',
            'Variant Command'   # <-- RIGTIGT FELTNAVN
        ])
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"Written {len(output_rows)} changes to matrixify_delta_update.csv")
else:
    with open('matrixify_delta_update.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Variant SKU',
            'Variant Price',
            'Variant Cost',
            'Variant Inventory Qty',
            'Variant Command'   # <-- RIGTIGT FELTNAVN
        ])
        writer.writeheader()
    print("No changes detected - created empty update file")

current_data[['SKU', 'Retail_Price', 'Stock']].to_csv('last_prices.csv', index=False)
print("Saved current prices for next run")
