import requests
import pandas as pd
from datetime import datetime
from io import StringIO
import json
import csv

# Config
SHOPIFY_STORE = 'b7916a-38.myshopify.com'
SHOPIFY_TOKEN = os.environ['SHOPIFY_ACCESS_TOKEN']
VIDAXL_URL = "https://transport.productsup.io/de8254c69e698a08e904/channel/188044/vidaXL_dk_dropshipping.csv"
PRICE_MARKUP = 1.60

def calculate_retail_price(b2b_price):
    """Beregn dansk salgspris"""
    try:
        import math
        price = float(b2b_price) * PRICE_MARKUP
        return int(10 * math.ceil(price / 10) - 1)
    except:
        return 0

def fetch_shopify_products():
    """Hent ALLE produkter fra Shopify med GraphQL - HURTIGT!"""
    print("🚀 Fetching all products from Shopify...")
    
    products = {}
    has_next_page = True
    cursor = None
    page = 0
    
    while has_next_page:
        query = """
        query getProducts($cursor: String) {
          productVariants(first: 250, after: $cursor) {
            edges {
              node {
                id
                sku
                price
                inventoryQuantity
                inventoryItem {
                  unitCost {
                    amount
                  }
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        
        response = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
            headers={
                'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                'Content-Type': 'application/json'
            },
            json={'query': query, 'variables': {'cursor': cursor}}
        )
        
        data = response.json()
        variants = data['data']['productVariants']
        
        # Process variants
        for edge in variants['edges']:
            node = edge['node']
            if node['sku']:
                products[str(node['sku'])] = {
                    'id': node['id'],
                    'price': float(node['price']) if node['price'] else 0,
                    'inventory': node['inventoryQuantity'] or 0,
                    'cost': float(node['inventoryItem']['unitCost']['amount']) if node['inventoryItem']['unitCost'] else 0
                }
        
        has_next_page = variants['pageInfo']['hasNextPage']
        cursor = variants['pageInfo']['endCursor']
        page += 1
        
        print(f"  Fetched page {page} - Total products: {len(products)}")
    
    return products

def main():
    print(f"🚀 VidaXL Direct Sync - {datetime.now()}")
    
    # Step 1: Hent Shopify data
    shopify_products = fetch_shopify_products()
    print(f"✅ Loaded {len(shopify_products)} products from Shopify")
    
    # Step 2: Hent VidaXL feed
    print("📥 Fetching VidaXL feed...")
    response = requests.get(VIDAXL_URL)
    vidaxl_data = pd.read_csv(StringIO(response.text))
    print(f"✅ Loaded {len(vidaxl_data)} products from VidaXL")
    
    # Step 3: Find ændringer
    changes = []
    
    for _, row in vidaxl_data.iterrows():
        sku = str(row['SKU'])
        vidaxl_price = calculate_retail_price(row['B2B price'])
        vidaxl_cost = float(row['B2B price'])
        vidaxl_stock = int(row['Stock'])
        
        if sku in shopify_products:
            shopify = shopify_products[sku]
            
            # Check for ændringer
            price_changed = abs(vidaxl_price - shopify['price']) > 0.01
            cost_changed = abs(vidaxl_cost - shopify['cost']) > 0.01
            stock_changed = vidaxl_stock != shopify['inventory']
            
            if price_changed or cost_changed or stock_changed:
                changes.append({
                    'sku': sku,
                    'price': vidaxl_price,
                    'cost': vidaxl_cost,
                    'inventory': vidaxl_stock,
                    'changes': {
                        'price': price_changed,
                        'cost': cost_changed,
                        'stock': stock_changed
                    }
                })
    
    print(f"📊 Found {len(changes)} products with changes")
    
    # Step 4: Output CSV
    if changes:
        with open('matrixify_delta_update.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'Variant SKU', 'Variant Price', 'Variant Cost', 
                'Variant Inventory Qty', 'Variant Command'
            ])
            writer.writeheader()
            
            for change in changes:
                writer.writerow({
                    'Variant SKU': change['sku'],
                    'Variant Price': change['price'],
                    'Variant Cost': change['cost'],
                    'Variant Inventory Qty': change['inventory'],
                    'Variant Command': 'UPDATE'
                })
        
        print(f"✅ Written {len(changes)} changes to matrixify_delta_update.csv")
    else:
        # Tom fil
        with open('matrixify_delta_update.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'Variant SKU', 'Variant Price', 'Variant Cost', 
                'Variant Inventory Qty', 'Variant Command'
            ])
            writer.writeheader()
        
        print("ℹ️ No changes detected - created empty update file")

if __name__ == "__main__":
    main()
