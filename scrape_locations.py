import requests
from bs4 import BeautifulSoup
import concurrent.futures
import re

# ==========================================
# CONFIGURATION
# ==========================================
BASE_URL = "https://www.rdc.in/contactus?parent_id={}"
OUTPUT_FILE = "locations.txt"

# Region IDs on the contact page that list plant addresses
VALID_IDS = [
    1, 119, 118, 112, 108, 105, 6, 80, 7, 8, 9, 10, 
    12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 85, 93
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Global set to prevent duplicates (just in case)
SEEN_ADDRESSES = set()

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def is_garbage(text):
    """Filters out the Head Office and website footer text."""
    text_lower = text.lower()
    if "thane one corporate" in text_lower: return True
    if "sales@rdc.in" in text_lower and len(text) < 150: return True
    if "copyright" in text_lower: return True
    if "design by" in text_lower: return True
    if len(text) < 25: return True
    return False

def scrape_specific_id(location_id):
    url = BASE_URL.format(location_id)
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the City Name (usually in the black header bar or h2)
        header = soup.find('div', class_=re.compile(r'black-bar|title'))
        city_name = clean_text(header.get_text()) if header else f"Region-{location_id}"

        # Find content blocks
        content_divs = soup.find_all('div', class_=re.compile(r'col-md|address|plant|loc'))
        
        found_lines = []

        for div in content_divs:
            text = clean_text(div.get_text())
            
            # 1. Filter Garbage
            if is_garbage(text): continue
            
            # 2. Must look like an address (has digits)
            if not any(char.isdigit() for char in text): continue

            # 3. Deduplicate
            signature = text[:50]
            if signature in SEEN_ADDRESSES: continue
            
            SEEN_ADDRESSES.add(signature)
            
            # Format nicely
            found_lines.append(f"Region: {city_name} (ID: {location_id}) | Address: {text}")

        return found_lines

    except Exception as e:
        print(f"Error scraping ID {location_id}: {e}")
        return None

def main():
    print(f"🚀 Starting Targeted Scraper for {len(VALID_IDS)} regions...")
    
    all_results = []

    # Use parallel processing to fetch all 24 pages instantly
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(scrape_specific_id, i): i for i in VALID_IDS}
        
        for future in concurrent.futures.as_completed(future_to_id):
            result = future.result()
            if result:
                all_results.extend(result)
                print(f"✅ Extracted data from ID {future_to_id[future]}")

    # Write to file
    if all_results:
        # Sort mainly for neatness
        all_results.sort()
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("OFFICIAL RDC PLANT LOCATIONS\n============================\n")
            f.write("\n".join(all_results))
            
        print(f"\n🎉 Done! Saved {len(all_results)} unique plant addresses to '{OUTPUT_FILE}'")
        print("👉 You can now restart 'app.py'")
    else:
        print("❌ No data found. Something went wrong.")

if __name__ == "__main__":
    main()