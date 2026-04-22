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

        # Looking for paths like /go-case/complain-title_ID/
        # They often look like href="/empresa/go-case/reclamacao-xyz_12345/"
        complaint_links = re.findall(r'href=["\'](/[^"\']*go-case[^"\']*_\d+/?)["\']', html)
        # Unique and filter
        unique_links = set(complaint_links)
        print(f"Valid complaint links: {len(unique_links)}")

        if url == urls[0]:
            print("--- Page 1 Stats ---")
            terms = ["pagina", "respondidas", "nao", "avaliadas", "status", "reclamacoes"]
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
            relevant = [h for h in set(all_hrefs) if any(t in h.lower() for t in terms)]
            print(f"Relevant hrefs (30):")
            for h in list(relevant)[:30]:
                print(f"  {h}")

            print("Indicators:")
            search_terms = ["de", "6419", "pagina", "reclamacoes", "total"]
            text_bits = re.findall(r'>([^<]+)<', html)
            for t in set(text_bits):
                if any(s in t.lower() for s in search_terms) and re.search(r'\d', t) and len(t) < 40:
                    print(f"  {t.strip()}")
    except Exception as e:
        print(f"Err: {e}")
