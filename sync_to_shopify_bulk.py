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

def save_update_report(changes, updated_skus):
    """Gem detaljeret rapport over hvad der blev opdateret"""
    # Opret reports mappe hvis den ikke findes
    os.makedirs('reports', exist_ok=True)
    
    report_time = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f'reports/update_report_{report_time}.csv'
    
    with open(report_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'SKU', 'Status', 'New_Price', 'New_Cost', 'New_Stock'
        ])
        writer.writeheader()
        
        for change in changes:
            writer.writerow({
                'SKU': change['sku'],
                'Status': 'Updated' if change['sku'] in updated_skus else 'Not Found',
                'New_Price': change['price'],
                'New_Cost': change['cost'],
                'New_Stock': change['inventory']
            })
    
    print(f"📄 Report saved: {report_file}")
    return report_file
    
def find_and_update_smart(changes):
    """Smart approach - find IDs og opdater i samme flow"""
    print("🧠 Using smart batch approach...")
    
    updated = 0
    not_found = 0
    updated_skus = []
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
                price
                inventoryItem {{ 
                    id 
                    unitCost {{ amount }}
                }}
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
        
        # DEBUG: Vis hvad vi fandt
        print(f"\n🔍 BATCH {i//batch_size + 1}: Found {len(data['data']['productVariants']['edges'])} variants")
        
        for edge in data['data']['productVariants']['edges']:
            node = edge['node']
            variants[node['sku']] = {
                'id': node['id'],
                'inventory_id': node['inventoryItem']['id'],
                'current_price': node['price'],
                'current_cost': node['inventoryItem']['unitCost']['amount'] if node['inventoryItem']['unitCost'] else '0'
            }
        
        # Now update found variants
        mutation = "mutation batchUpdate {\n"
        update_count = 0
        batch_updated_skus = []
        
        for change in batch:
            if change['sku'] in variants:
                v = variants[change['sku']]
                
                # DEBUG: Vis hvad vi opdaterer
                if update_count < 3:  # Vis første 3 som eksempel
                    print(f"\n📦 SKU {change['sku']}:")
                    print(f"   Current price: {v['current_price']} → New: {change['price']}")
                    print(f"   Current cost: {v['current_cost']} → New: {change['cost']}")
                    print(f"   New inventory: {change['inventory']}")
                
                mutation += f"""
                v{update_count}: productVariantUpdate(input: {{
                    id: "{v['id']}",
                    price: {change['price']},
                    cost: {change['cost']}
                }}) {{
                    productVariant {{ 
                        id 
                        price
                    }}
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
                batch_updated_skus.append(change['sku'])
            else:
                not_found += 1
        
        mutation += "\n}"
        
        if update_count > 0:
            print(f"\n📤 SENDING BATCH: {update_count} updates")
            
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
                result_data = response.json()
                
                # DEBUG: Check for errors
                if 'errors' in result_data:
                    print(f"  ⚠️ GraphQL errors: {result_data['errors']}")
                
                # Check each mutation result
                errors_found = False
                for key, value in result_data.get('data', {}).items():
                    if 'userErrors' in value and value['userErrors']:
                        print(f"  ❌ Error in {key}: {value['userErrors']}")
                        errors_found = True
                    elif key.startswith('v') and 'productVariant' in value:
                        # DEBUG: Vis opdateret pris
                        new_price = value['productVariant'].get('price', 'N/A')
                        if update_count < 3:
                            print(f"  ✅ {key} updated - new price: {new_price}")
                
                if not errors_found:
                    updated += update_count
                    updated_skus.extend(batch_updated_skus)
                    print(f"  ✅ Batch successful!")
            else:
                print(f"  ❌ HTTP Error {response.status_code}: {response.text[:200]}")
        
        # Progress
        if i % 5000 == 0 and i > 0:
            print(f"\n📊 Progress: {updated:,} updated, {not_found:,} not found...")
        
        # Rate limit
        time.sleep(0.5)
    
    return updated, not_found, updated_skus

def main():
    print(f"🚀 Shopify GraphQL Sync - {datetime.now()}")
    
    # TEST MODE - kun første 100 produkter
    TEST_MODE = True
    
    # Læs ændringer
    changes = read_csv_changes()
    if not changes:
        return
    
    # DEBUG: Vis sample af data
    print("\n📋 SAMPLE DATA (first 3 products):")
    for i, change in enumerate(changes[:3]):
        print(f"{i+1}. SKU: {change['sku']} - Price: {change['price']} - Cost: {change['cost']} - Stock: {change['inventory']}")
    
    if TEST_MODE and len(changes) > 100:
        print("\n⚠️ TEST MODE: Only processing first 100 changes")
        changes = changes[:100]
    
    # Smart update
    start_time = time.time()
    updated, not_found, updated_skus = find_and_update_smart(changes)
    elapsed = time.time() - start_time
    
    print(f"\n📊 FINAL RESULTS:")
    print(f"  Total changes: {len(changes):,}")
    print(f"  Updated: {updated:,}")
    print(f"  Not found: {not_found:,}")
    print(f"  Time: {elapsed/60:.1f} minutes")
    print(f"  Speed: {updated/(elapsed/60):.0f} products/minute")
    
    # Gem rapport
    if len(changes) > 0:
        report_file = save_update_report(changes, updated_skus)
        print(f"\n✅ Check {report_file} for details!")

if __name__ == "__main__":
    main()
