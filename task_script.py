import cloudscraper
from bs4 import BeautifulSoup

url = "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/"
scraper = cloudscraper.create_scraper()
response = scraper.get(url)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, 'html.parser')
    anchors = soup.find_all('a', href=True)
    
    unique_hrefs = []
    seen = set()
    terms = ["respond", "nao", "não", "avaliad", "reclam", "status", "pagina"]
    
    for a in anchors:
        href = a['href']
        text = a.get_text().lower()
        href_lower = href.lower()
        
        match = False
        if any(term in text or term in href_lower for term in terms):
            match = True
        if "pagina=" in href_lower or "nao-respond" in href_lower or "respondidas" in href_lower:
            match = True
            
        if match and href not in seen:
            unique_hrefs.append(href)
            seen.add(href)
            if len(unique_hrefs) >= 60:
                break
                
    for href in unique_hrefs:
        print(href)
else:
    print(f"Failed: {response.status_code}")
