import cloudscraper
import re

urls = ["https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/"]
scraper = cloudscraper.create_scraper()
response = scraper.get(urls[0])
html = response.text

# Try different pattern for complaint links
# Usually they are inside <a> tags within a list
# Example: /go-case/reclamacao-title_12345/
links = re.findall(r'href=["\']([^"\']+)["\']', html)
complaint_links = [l for l in links if re.search(r'_[a-zA-Z0-9]{10,}/?$', l) or re.search(r'_\d+/?$', l)]
filtered = [l for l in set(complaint_links) if 'go-case' in l]

print(f"Total hrefs: {len(links)}")
print(f"Filtered links: {len(filtered)}")
for l in filtered[:5]: print(f" Example: {l}")

# Look for patterns like "1 - 10 de 6000" or similar
text_only = re.sub(r'<[^>]+>', ' ', html)
indicators = re.findall(r'(\d+[^0-9]+de[^0-9]+\d+)', text_only)
print(f"Total/Page indicators: {indicators}")

# Print snippet of HTML around a known term
idx = html.find('6419')
if idx != -1:
    print(f"Snippet around 6419: {html[max(0, idx-100):idx+100]}")
