import csv
import requests
import pandas as pd
from datetime import datetime
from io import StringIO
import os
import json

VIDAXL_URL = "https://transport.productsup.io/de8254c69e698a08e904/channel/188044/vidaXL_dk_dropshipping.csv"
PRICE_MARKUP = 1.60

def calculate_retail_price(b2b_price):
    try:
        import math
        price = float(b2b_price) * PRICE_MARKUP
        return int(10 * math.ceil(price / 10) - 1)
    except:
        return 0

def load_shop_skus():
    """Load cached SKUs from GitHub"""
    try:
        response = requests.get(
            'https://raw.githubusercontent.com/GabrielKeuer/vidaxl-shopify-sync/main/shop_skus.json'
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Loaded {data['count']} shop SKUs (updated: {data['updated']})")
            return set(str(sku) for sku in data['skus'])  # Ensure all are strings
        else:
            print("⚠️ Shop SKUs not found - will process all changes")
            return None
    except Exception as e:
        print(f"⚠️ Could not load shop SKUs: {e}")
        return None

print(f"🚀 Starting VidaXL Delta Sync - {datetime.now()}")

# Hent VidaXL data
try:
    response = requests.get(VIDAXL_URL)
    response.raise_for_status()
    current_data = pd.read_csv(StringIO(response.text))
    print(f"✅ Loaded {len(current_data)} products from VidaXL")
except Exception as e:
    print(f"❌ Failed to fetch VidaXL data: {e}")
    # Create empty update file
    with open('matrixify_delta_update.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Variant SKU', 'Variant Price', 'Variant Cost', 
            'Variant Inventory Qty', 'Variant Command'
        ])
        writer.writeheader()
    exit(0)

# Beregn retail priser
current_data['Retail_Price'] = current_data['B2B price'].apply(calculate_retail_price)
current_data['SKU'] = current_data['SKU'].astype(str)

# Load shop SKUs for filtering
shop_skus = load_shop_skus()

# Find ændringer
changes_found = False
if os.path.exists('last_prices.csv'):
    print("📊 Comparing with previous data...")
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
    
    changes = merged[price_changed | stock_changed | is_new].copy()
    
    if len(changes) > 0:
        print(f"📝 Found {len(changes)} products with changes")
        
        # FILTER: Kun produkter i shoppen
        if shop_skus:
            changes['in_shop'] = changes['SKU'].isin(shop_skus)
            filtered_changes = changes[changes['in_shop']].copy()
            
            print(f"🎯 Filtered: {len(changes)} total → {len(filtered_changes)} in shop")
            changes = filtered_changes
        
        changes_found = len(changes) > 0
else:
    print("🆕 No previous data - processing all as new")
    changes = current_data.copy()
    changes['Stock_new'] = changes['Stock']
    changes['Retail_Price_new'] = changes['Retail_Price']
    
    # Filter even for initial run
    if shop_skus:
        changes = changes[changes['SKU'].isin(shop_skus)].copy()
        print(f"🎯 Filtered to {len(changes)} products in shop")
    
    changes_found = len(changes) > 0

# Skriv output
if changes_found and len(changes) > 0:
    output_rows = []
    for _, row in changes.iterrows():
        output_rows.append({
            'Variant SKU': row['SKU'],
            'Variant Price': row.get('Retail_Price_new', row.get('Retail_Price')),
            'Variant Cost': row['B2B price'],
            'Variant Inventory Qty': row.get('Stock_new', row.get('Stock')),
            'Variant Command': 'UPDATE'
        })
    
    with open('matrixify_delta_update.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Variant SKU', 'Variant Price', 'Variant Cost', 
            'Variant Inventory Qty', 'Variant Command'
        ])
        writer.writeheader()
        writer.writerows(output_rows)
    
    print(f"✅ Written {len(output_rows)} changes to matrixify_delta_update.csv")
else:
    # Ingen ændringer - lav tom fil
    print("ℹ️ No changes detected - creating empty update file")
    with open('matrixify_delta_update.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Variant SKU', 'Variant Price', 'Variant Cost', 
            'Variant Inventory Qty', 'Variant Command'
        ])
        writer.writeheader()

# Gem current state
print("💾 Saving current state...")
current_data[['SKU', 'Retail_Price', 'Stock']].to_csv('last_prices.csv', index=False)
print("✅ Delta sync complete!")
