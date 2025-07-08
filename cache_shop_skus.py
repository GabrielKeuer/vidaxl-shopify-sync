import requests
import json
import os
from datetime import datetime

# Shopify credentials
SHOPIFY_STORE = 'b7916a-38.myshopify.com'  # <-- Din rigtige URL
SHOPIFY_TOKEN = os.environ['SHOPIFY_ACCESS_TOKEN']  # <-- Hentes fra GitHub Secrets

def fetch_all_skus():
    """Hent alle SKUs fra Shopify via REST API"""
    print(f"🔄 Fetching SKUs from {SHOPIFY_STORE}...")
    
    all_skus = set()
    page_info = None
    
    while True:
        # Build URL with pagination
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?fields=variants&limit=250"
        if page_info:
            url += f"&page_info={page_info}"
        
        response = requests.get(url, headers={
            'X-Shopify-Access-Token': SHOPIFY_TOKEN
        })
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            break
            
        data = response.json()
        
        # Extract SKUs from all variants
        for product in data.get('products', []):
            for variant in product.get('variants', []):
                if variant.get('sku'):
                    all_skus.add(str(variant['sku']).strip())
        
        # Check for next page
        link_header = response.headers.get('Link', '')
        if 'rel="next"' in link_header:
            # Extract page_info from Link header
            import re
            match = re.search(r'page_info=([^&>]+)', link_header)
            if match:
                page_info = match.group(1)
            else:
                break
        else:
            break
        
        print(f"  Progress: {len(all_skus)} SKUs...")
    
    return sorted(list(all_skus))

def main():
    print(f"🚀 Shop SKU Cache - {datetime.now()}")
    
    try:
        # Fetch all SKUs
        skus = fetch_all_skus()
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
