import requests
import json
import os
from datetime import datetime

# Shopify credentials
SHOPIFY_STORE = 'b7916a-38.myshopify.com'
SHOPIFY_TOKEN = os.environ['SHOPIFY_ACCESS_TOKEN']

def fetch_all_skus_graphql():
    """Hent alle SKUs via GraphQL - MEGET hurtigere!"""
    print(f"🚀 Fetching SKUs via GraphQL...")
    
    all_skus = set()
    has_next_page = True
    cursor = None
    page_count = 0
    
    while has_next_page:
        query = """
        query getVariants($cursor: String) {
          productVariants(first: 250, after: $cursor) {
            edges {
              node {
                sku
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
            json={
                'query': query,
                'variables': {'cursor': cursor}
            }
        )
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            break
            
        data = response.json()
        
        if 'errors' in data:
            print(f"❌ GraphQL errors: {data['errors']}")
            break
            
        variants = data['data']['productVariants']
        
        # Extract SKUs
        for edge in variants['edges']:
            sku = edge['node'].get('sku')
            if sku and sku.strip():
                all_skus.add(str(sku).strip())
        
        # Pagination
        has_next_page = variants['pageInfo']['hasNextPage']
        cursor = variants['pageInfo']['endCursor']
        page_count += 1
        
        print(f"  Progress: {len(all_skus)} SKUs... (Page {page_count})")
    
    return sorted(list(all_skus))

def main():
    print(f"🚀 Shop SKU Cache - {datetime.now()}")
    
    try:
        # Fetch all SKUs
        skus = fetch_all_skus_graphql()
        print(f"✅ Found {len(skus)} total SKUs")
        
        # Save to JSON
        output = {
            'skus': skus,
            'count': len(skus),
            'updated': datetime.now().isoformat()
        }
        
        with open('shop_skus.json', 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"💾 Saved to shop_skus.json")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Create empty file so workflows don't fail
        with open('shop_skus.json', 'w') as f:
            json.dump({
                'skus': [],
                'count': 0,
                'updated': datetime.now().isoformat(),
                'error': str(e)
            }, f, indent=2)

if __name__ == "__main__":
    main()
