import os
import csv
import json
import requests
import time
from datetime import datetime

SHOPIFY_STORE = 'b7916a-38.myshopify.com'
SHOPIFY_TOKEN = os.environ['SHOPIFY_ACCESS_TOKEN']
LOCATION_ID = '97768178013'

def read_csv_changes():
    """Læs matrixify_delta_update.csv"""
    changes = []
    try:
        with open('matrixify_delta_update.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                changes.append({
                    'sku': row['Variant SKU'],
                    'price': row['Variant Price'],
                    'cost': row['Variant Cost'],
                    'inventory': int(row['Variant Inventory Qty'])
                })
        print(f"📊 Loaded {len(changes)} changes from CSV")
        return changes
    except FileNotFoundError:
        print("❌ No matrixify_delta_update.csv found!")
        return []

def batch_update_variants(changes):
    """Opdater i batches af 50 - ligesom vi henter!"""
    print(f"🚀 Starting batch updates for {len(changes)} products...")
    
    updated = 0
    failed = 0
    batch_size = 50  # Shopify kan håndtere dette fint
    
    for i in range(0, len(changes), batch_size):
        batch = changes[i:i+batch_size]
        
        # Byg mutation for batch
        mutation = "mutation batchUpdate {\n"
        
        for idx, change in enumerate(batch):
            # Product variant update
            mutation += f"""
            variant{idx}: productVariantUpdate(input: {{
                id: "gid://shopify/ProductVariant/TEMP_{change['sku']}",
                price: "{change['price']}",
                cost: "{change['cost']}"
            }}) {{
                productVariant {{ id }}
                userErrors {{ field message }}
            }}
            """
            
            # Inventory update
            mutation += f"""
            inv{idx}: inventorySetQuantities(input: {{
                reason: "correction",
                quantities: [{{
                    inventoryItemId: "gid://shopify/InventoryItem/TEMP_{change['sku']}",
                    locationId: "gid://shopify/Location/{LOCATION_ID}",
                    quantity: {change['inventory']}
                }}]
            }}) {{
                inventoryAdjustmentGroup {{ id }}
                userErrors {{ field message }}
            }}
            """
        
        mutation += "\n}"
        
        # Send batch
        response = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
            headers={
                'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                'Content-Type': 'application/json'
            },
            json={'query': mutation}
        )
        
        if response.status_code == 200:
            updated += len(batch)
        else:
            failed += len(batch)
            print(f"  ❌ Batch failed: {response.text[:200]}")
        
        # Progress
        if updated % 1000 == 0:
            elapsed = (i / len(changes)) * 100
            print(f"  Progress: {updated:,} updated ({elapsed:.1f}%) ...")
        
        # Rate limit respect (2 req/sec)
        time.sleep(0.5)
    
    print(f"✅ Complete! Updated: {updated:,} | Failed: {failed}")
    return updated, failed

def find_and_update_smart(changes):
    """Smart approach - find IDs og opdater i samme flow"""
    print("🧠 Using smart batch approach...")
    
    updated = 0
    not_found = 0
    batch_size = 100
    
    for i in range(0, len(changes), batch_size):
        batch = changes[i:i+batch_size]
        sku_conditions = ' OR '.join([f'sku:{c["sku"]}' for c in batch])
        
        # First find variants
        find_query = f"""
        query {{
          productVariants(first: {batch_size}, query: "{sku_conditions}") {{
            edges {{
              node {{
                id
                sku
                inventoryItem {{ id }}
              }}
            }}
          }}
        }}
        """
        
        response = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
            headers={
                'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                'Content-Type': 'application/json'
            },
            json={'query': find_query}
        )
        
        variants = {}
        data = response.json()
        for edge in data['data']['productVariants']['edges']:
            node = edge['node']
            variants[node['sku']] = {
                'id': node['id'],
                'inventory_id': node['inventoryItem']['id']
            }
        
        # Now update found variants
        mutation = "mutation batchUpdate {\n"
        update_count = 0
        
        for change in batch:
            if change['sku'] in variants:
                v = variants[change['sku']]
                
                mutation += f"""
                v{update_count}: productVariantUpdate(input: {{
                    id: "{v['id']}",
                    price: "{change['price']}",
                    cost: "{change['cost']}"
                }}) {{
                    productVariant {{ id }}
                    userErrors {{ field message }}
                }}
                inv{update_count}: inventorySetQuantities(input: {{
                    reason: "correction",
                    quantities: [{{
                        inventoryItemId: "{v['inventory_id']}",
                        locationId: "gid://shopify/Location/{LOCATION_ID}",
                        quantity: {change['inventory']}
                    }}]
                }}) {{
                    inventoryAdjustmentGroup {{ id }}
                    userErrors {{ field message }}
                }}
                """
                update_count += 1
            else:
                not_found += 1
        
        mutation += "\n}"
        
        if update_count > 0:
            # Send updates
            response = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
                headers={
                    'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                    'Content-Type': 'application/json'
                },
                json={'query': mutation}
            )
            
            if response.status_code == 200:
                updated += update_count
            else:
                print(f"  ❌ Error: {response.text[:200]}")
        
        # Progress
        if i % 5000 == 0 and i > 0:
            print(f"  Progress: {updated:,} updated, {not_found:,} not found...")
        
        # Rate limit
        time.sleep(0.5)
    
    return updated, not_found

def main():
    print(f"🚀 Shopify GraphQL Sync - {datetime.now()}")
    
    # Læs ændringer
    changes = read_csv_changes()
    if not changes:
        return
    
    # Smart update
    start_time = time.time()
    updated, not_found = find_and_update_smart(changes)
    elapsed = time.time() - start_time
    
    print(f"\n📊 FINAL RESULTS:")
    print(f"  Total changes: {len(changes):,}")
    print(f"  Updated: {updated:,}")
    print(f"  Not found: {not_found:,}")
    print(f"  Time: {elapsed/60:.1f} minutes")
    print(f"  Speed: {updated/(elapsed/60):.0f} products/minute")

if __name__ == "__main__":
    main()
