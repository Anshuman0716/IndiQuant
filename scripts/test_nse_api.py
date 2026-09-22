import httpx
from datetime import date
from bs4 import BeautifulSoup

def test_nse_api():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }
    
    with httpx.Client(headers=headers, timeout=10.0) as client:
        # Prime the session
        print("Priming session...")
        r = client.get("https://www.nseindia.com")
        print("Primed. Status:", r.status_code)
        
        # Test 1: Recent date
        url1 = "https://www.nseindia.com/api/corporates-financial-results?index=equities&period=1Months"
        print(f"\nTest 1: {url1}")
        try:
            r1 = client.get(url1, headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"})
            print(r1.status_code)
            print(r1.text[:200])
        except Exception as e:
            print(e)
            
        # Test 2: Date range
        url2 = "https://www.nseindia.com/api/corporates-financial-results?index=equities&from_date=01-05-2024&to_date=30-05-2024"
        print(f"\nTest 2: {url2}")
        try:
            r2 = client.get(url2, headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"})
            print(r2.status_code)
            print(r2.text[:200])
        except Exception as e:
            print(e)

if __name__ == "__main__":
    test_nse_api()
