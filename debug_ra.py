import cloudscraper
import re

url = "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/"
scraper = cloudscraper.create_scraper()
response = scraper.get(url)
html = response.text

print(f"URL: {url}")
print(f"Status: {response.status_code}")
print(f"Size: {len(html)}")

# Broad href search to find what they look like
all_links = re.findall(r'href=["\']([^"\']+)["\']', html)
# Find any link with an ID (longer digits)
# Typical RA ID has 8-9 digits
id_links = [l for l in all_links if re.search(r'\d{7,}', l)]
print(f"Links with 7+ digits: {len(id_links)}")
for l in list(set(id_links))[:10]:
    print(f"  ID Link: {l}")

# Check for the literal "go-case"
go_case_links = [l for l in all_links if "go-case" in l.lower()]
print(f"Links with go-case: {len(set(go_case_links))}")
for l in list(set(go_case_links))[:5]:
    print(f"  GoCase Link: {l}")

# Look for text suggesting total count
text_near_6419 = re.findall(r'[^<>]{1,30}6419[^<>]{1,30}', html)
print(f"Text near 6419: {text_near_6419}")

# Show some links to understand structure
print("First 20 hrefs found:")
for l in all_links[:20]:
    print(f"  {l}")
