import cloudscraper
import re

urls = [
    "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/",
    "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/?pagina=2",
    "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/?pagina=3"
]

scraper = cloudscraper.create_scraper()

for url in urls:
    print(f"URL: {url}")
    try:
        response = scraper.get(url)
        print(f"Status: {response.status_code}")
        html = response.text
        print(f"Size: {len(html)}")

        # Looking for paths like /go-case/something_TOKEN/
        # They often look like href="/go-case/ma-qualidade_YP28Q2GVW_RirQht/"
        # Correct regex based on debug: _[A-Z0-9]+
        complaint_links = re.findall(r'href=["\'](/go-case/[^"\']+_[\w-]+/?)["\']', html)
        unique_links = set(complaint_links)
        print(f"Valid complaint links: {len(unique_links)}")

        if "pagina" not in url:
            print("--- Analysis of Page 1 ---")
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
            terms = ["pagina", "respondidas", "nao", "avaliadas", "status", "reclamacoes"]
            relevant = [h for h in set(all_hrefs) if any(t in h.lower() for t in terms)]
            print(f"Relevant hrefs (top 30):")
            for h in list(relevant)[:30]: print(f"  {h}")

            print("Pagination/Total indicators:")
            # Look for numbers near "reclamacoes" or "de"
            # In RA it is often: <span>6419</span> ou "reclamacoes (6419)"
            text_bits = re.findall(r'>([^<]+)<', html)
            indicators = [t.strip() for t in text_bits if any(s.lower() in t.lower() for s in ["reclamacoes", "de", "total", "6419"]) and re.search(r'\d', t)]
            for i in set(indicators):
                if len(i) < 40: print(f"  {i}")
    except Exception as e:
        print(f"Err: {e}")
