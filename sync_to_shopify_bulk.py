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
    batch_size = 50
    
    for i in range(0, len(changes), batch_size):
        batch = changes[i:i+batch_size]
        sku_conditions = ' OR '.join([f'sku:{c["sku"]}' for c in batch])
        
        # First find variants - RETTET QUERY
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
                    inventoryLevels(first: 10) {{
                        edges {{
                            node {{
                                id
                                location {{ id }}
                                quantities(names: ["available"]) {{
                                    name
                                    quantity
                                }}
                            }}
                        }}
                    }}
                }}
              }}
            }}
          }}
        }}
        """
        
        try:
            response = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
                headers={
                    'X-Shopify-Access-Token': SHOPIFY_TOKEN,
                    'Content-Type': 'application/json'
                },
                json={'query': find_query}
            )
            
            # Check HTTP response
            if response.status_code != 200:
                print(f"❌ HTTP Error {response.status_code}: {response.text[:500]}")
                continue
                
            data = response.json()
            
            # Check for GraphQL errors
            if 'errors' in data:
                print(f"❌ GraphQL errors in find query:")
                for error in data['errors'][:3]:
                    print(f"   - {error.get('message', error)}")
                continue
                
            # Check response structure
            if 'data' not in data:
                print(f"❌ No 'data' field in response. Keys: {list(data.keys())}")
                continue
                
            if 'productVariants' not in data['data']:
                print(f"❌ No 'productVariants' in data. Keys: {list(data['data'].keys())}")
                continue
            
            variants = {}
            variant_edges = data['data']['productVariants']['edges']
            
            print(f"\n🔍 BATCH {i//batch_size + 1}: Found {len(variant_edges)} variants")
            
            for edge in variant_edges:
                node = edge['node']
                
                # Find inventory level for our location
                inventory_level_id = None
                current_available = 0
                
                if 'inventoryItem' in node and 'inventoryLevels' in node['inventoryItem']:
                    for inv_edge in node['inventoryItem']['inventoryLevels']['edges']:
                        inv_node = inv_edge['node']
                        if LOCATION_ID in inv_node['location']['id']:
                            inventory_level_id = inv_node['id']
                            
                            # Find available quantity
                            for q in inv_node.get('quantities', []):
                                if q['name'] == 'available':
                                    current_available = q['quantity']
                                    break
                            break
                
                variants[node['sku']] = {
                    'id': node['id'],
                    'inventory_item_id': node['inventoryItem']['id'] if 'inventoryItem' in node else None,
                    'inventory_level_id': inventory_level_id,
                    'current_price': node.get('price', '0'),
                    'current_available': current_available
                }
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error: {e}")
            continue
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            continue
        except Exception as e:
            print(f"❌ Unexpected error in find query: {e}")
            continue
        
        # Now update found variants
        mutation = "mutation batchUpdate {\n"
        update_count = 0
        batch_updated_skus = []
        
        for change in batch:
            if change['sku'] in variants:
                v = variants[change['sku']]
                
                # DEBUG: Vis første 3
                if update_count < 3:
                    print(f"\n📦 SKU {change['sku']}:")
                    print(f"   Current price: {v['current_price']} → New: {change['price']}")
                    print(f"   Current stock: {v['current_available']} → New: {change['inventory']}")
                
                # Opdater pris
                mutation += f"""
                v{update_count}: productVariantUpdate(input: {{
                    id: "{v['id']}",
                    price: {change['price']}
                }}) {{
                    productVariant {{ 
                        id 
                        price
                    }}
                    userErrors {{ field message }}
                }}
                """
                
                # Opdater inventory hvis vi har inventory item ID - RETTET MUTATION
                if v['inventory_item_id']:
                    quantity_delta = change['inventory'] - v['current_available']
                    if quantity_delta != 0:
                        mutation += f"""
                        inv{update_count}: inventoryAdjustQuantities(input: {{
                            name: "available",
                            reason: "correction",
                            changes: [{{
                                inventoryItemId: "{v['inventory_item_id']}",
                                locationId: "gid://shopify/Location/{LOCATION_ID}",
                                delta: {quantity_delta}
                            }}]
                        }}) {{
                            inventoryAdjustmentGroup {{ 
                                id 
                                reason
                            }}
                            userErrors {{ field message }}
                        }}
                        """
                
                # Opdater cost hvis vi har inventory item ID
                if v['inventory_item_id']:
                    mutation += f"""
                    cost{update_count}: inventoryItemUpdate(
                        id: "{v['inventory_item_id']}",
                        input: {{
                            cost: {change['cost']}
                        }}
                    ) {{
                        inventoryItem {{
                            id
                            unitCost {{ amount }}
                        }}
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
            
            try:
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
                    
                    # Check for GraphQL errors
                    if 'errors' in result_data:
                        print(f"  ⚠️ GraphQL errors in mutation:")
                        for error in result_data['errors'][:5]:
                            print(f"     - {error.get('message', error)}")
                    
                    # Check mutation results
                    errors_found = False
                    if 'data' in result_data:
                        for key, value in result_data['data'].items():
                            if value and 'userErrors' in value and value['userErrors']:
                                print(f"  ❌ Error in {key}: {value['userErrors']}")
                                errors_found = True
                    
                    if not errors_found and 'data' in result_data:
                        updated += update_count
                        updated_skus.extend(batch_updated_skus)
                        print(f"  ✅ Batch successful!")
                    else:
                        print(f"  ⚠️ Batch completed with some errors")
                else:
                    print(f"  ❌ HTTP Error {response.status_code}: {response.text[:200]}")
                    
            except Exception as e:
                print(f"  ❌ Error sending mutation: {e}")
        
        # Rate limit
        time.sleep(1)
    
    return updated, not_found, updated_skus

def main():
    print(f"🚀 Shopify GraphQL Sync - {datetime.now()}")
    
    # TEST MODE - kun første 100 produkter
    TEST_MODE = True
    
    # Læs ændringer
    changes = read_csv_changes()
    if not changes:
        return
    
    # DEBUG: Vis sample
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
    if updated > 0:
        print(f"  Speed: {updated/(elapsed/60):.0f} products/minute")
    
    # Gem rapport
    if len(changes) > 0:
        report_file = save_update_report(changes, updated_skus)
        print(f"\n✅ Check {report_file} for details!")

if __name__ == "__main__":
    main()
