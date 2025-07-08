import os
import csv
import time
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Config
SHOPIFY_STORE = "b7916a-38.myshopify.com"
SHOPIFY_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
LOCATION_ID = "97768178013"
BATCH_SIZE = 100
TEST_MODE = True  # Set to False for full run

def read_csv_changes():
    """Read changes from CSV file"""
    changes = []
    try:
        with open('matrixify_delta_update.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('Variant SKU'):
                    changes.append({
                        'sku': row['Variant SKU'],
                        'price': row['Variant Price'],
                        'cost': row['Variant Cost'],
                        'inventory': row['Variant Inventory Qty']
                    })
        print(f"📁 Loaded {len(changes)} changes from CSV")
        return changes
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return []

def find_and_update_smart(changes):
    """Smart update: Find variants and update in same batch"""
    total_updated = 0
    total_not_found = 0
    update_log = []  # Log for rapport
    
    # Process in batches
    for i in range(0, len(changes), BATCH_SIZE):
        batch = changes[i:i+BATCH_SIZE]
        print(f"\n🔄 Processing batch {i//BATCH_SIZE + 1}/{(len(changes)-1)//BATCH_SIZE + 1}")
        
        # Build SKU list for find query
        sku_list = [f'"{change["sku"]}"' for change in batch]
        
        # Find variants by SKU
        find_query = f"""
        {{
          productVariants(first: {len(batch)}, query: "sku:({' OR '.join(sku_list)})") {{
            edges {{
              node {{
                id
                sku
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
        
        # Map SKU to variant info
        variants = {}
        data = response.json()
        
        if 'data' in data and data['data']['productVariants']:
            for edge in data['data']['productVariants']['edges']:
                node = edge['node']
                variants[node['sku']] = {
                    'id': node['id']
                }
        
        # Build bulk update mutation
        variants_to_update = []
        for change in batch:
            if change['sku'] in variants:
                v = variants[change['sku']]
                variants_to_update.append({
                    "id": v['id'],
                    "price": change['price'],
                    "cost": change['cost'],
                    "inventoryQuantities": [{
                        "locationId": f"gid://shopify/Location/{LOCATION_ID}",
                        "availableQuantity": int(change['inventory'])
                    }]
                })
                # Log successful mapping
                update_log.append({
                    'sku': change['sku'],
                    'status': 'found',
                    'price': change['price'],
                    'inventory': change['inventory']
                })
            else:
                total_not_found += 1
                print(f"⚠️ SKU not found: {change['sku']}")
                update_log.append({
                    'sku': change['sku'],
                    'status': 'not_found'
                })
        
        # Execute bulk update if we have variants
        if variants_to_update:
            mutation = """
            mutation bulkUpdate($productVariants: [ProductVariantsBulkInput!]!) {
              productVariantsBulkUpdate(productVariants: $productVariants) {
                productVariants {
                  id
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            
            update_response = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
                headers={
                    'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                    'Content-Type': 'application/json'
                },
                json={
                    'query': mutation,
                    'variables': {
                        'productVariants': variants_to_update
                    }
                }
            )
            
            # Check for errors
            update_data = update_response.json()
            if 'errors' in update_data:
                print(f"❌ GraphQL errors: {update_data['errors']}")
            else:
                result = update_data.get('data', {}).get('productVariantsBulkUpdate', {})
                if result.get('userErrors'):
                    print(f"⚠️ User errors: {result['userErrors']}")
                else:
                    updated_count = len(result.get('productVariants', []))
                    total_updated += updated_count
                    print(f"✅ Updated {updated_count} variants in batch")
        
        # Rate limit pause
        time.sleep(0.5)
    
    # Save detailed log
    log_file = f"reports/update_details_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs('reports', exist_ok=True)
    with open(log_file, 'w') as f:
        json.dump(update_log, f, indent=2)
    
    return total_updated, total_not_found

def main():
    print("🚀 Starting Shopify Bulk Update")
    print(f"📍 Store: {SHOPIFY_STORE}")
    print(f"📍 Location ID: {LOCATION_ID}")
    print(f"📍 TEST MODE: {TEST_MODE}")
    
    # Read changes
    changes = read_csv_changes()
    if not changes:
        return
    
    # Apply test mode limit
    if TEST_MODE and len(changes) > 100:
        print("⚠️ TEST MODE: Only processing first 100 changes")
        changes = changes[:100]
    
    # Smart update
    start_time = time.time()
    updated, not_found = find_and_update_smart(changes)
    elapsed = time.time() - start_time
    
    # Final results
    results = {
        'timestamp': datetime.now().isoformat(),
        'test_mode': TEST_MODE,
        'total_changes': len(changes),
        'updated': updated,
        'not_found': not_found,
        'elapsed_seconds': round(elapsed, 2),
        'elapsed_minutes': round(elapsed/60, 1),
        'speed_per_minute': round(updated/(elapsed/60)) if elapsed > 0 else 0
    }
    
    print(f"\n📊 FINAL RESULTS:")
    print(f"  Total changes: {results['total_changes']:,}")
    print(f"  Updated: {results['updated']:,}")
    print(f"  Not found: {results['not_found']:,}")
    print(f"  Time: {results['elapsed_minutes']} minutes")
    print(f"  Speed: {results['speed_per_minute']} products/minute")
    
    # Create reports directory if it doesn't exist
    os.makedirs('reports', exist_ok=True)
    
    # Save report
    report_file = f"reports/update_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n📄 Report saved to: {report_file}")

if __name__ == "__main__":
    main()
