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

        complaint_links = re.findall(r'href=["\']([^"\']*/[^"\']*_\d+/)["\']', html)
        filtered_links = [l for l in set(complaint_links) if 'go-case' in l.lower()]
        print(f"Links: {len(filtered_links)}")

        if "pagina" not in url:
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
            terms = ["pagina", "respondidas", "nao", "avaliadas", "status", "reclamacoes"]
            relevant = [h for h in set(all_hrefs) if any(t in h.lower() for t in terms)]
            print("Hrefs (30):")
            for h in relevant[:30]: print(f"  {h}")

            text_chunks = re.findall(r'>([^<]+)<', html)
            search = ["de", "6419", "pagina", "reclamacoes", "total"]
            print("Indicators:")
            for t in set(text_chunks):
                if any(s in t.lower() for s in search) and re.search(r'\d', t) and len(t) < 50:
                    print(f"  {t.strip()}")
    except Exception as e:
        print(f"Err: {e}")
