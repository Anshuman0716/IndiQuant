import requests
import re
from bs4 import BeautifulSoup

url = 'https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/'
try:
    resp = requests.get(url, verify=False)
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        if 'Daily' in a['href'] or 'csv' in a['href'].lower() or 'xls' in a['href'].lower():
            print(a['href'])
except Exception as e:
    print(e)
