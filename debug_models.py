import requests, re, feedparser, html, json
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
src=json.load(open("sources.json",encoding="utf-8"))
for s in src[:2]+src[3:4]:
    f=feedparser.parse(requests.get(s["url"],headers=UA,timeout=30).content)
    for e in f.entries[:2]:
        h=requests.get(e.link,headers=UA,timeout=30).text
        cls=set(re.findall(r'<(?:div|article)[^>]+class="([^"]+)"',h))
        print("DBG ===",e.title, e.link[:80]); print("DBG CLS", [c for c in cls if any(k in c for k in ["content","entry","post","article","single"])][:15])
        m=re.search(r'<div[^>]+class="[^"]*(entry-content|post-content|single-content|content-post)[^"]*"[^>]*>(.*)',h,re.S)
        body=m.group(2) if m else h
        txt=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",re.sub(r"<(script|style)[^>]*>.*?</\1>"," ",body,flags=re.S))))
        for mm in re.finditer(r"[^.]{0,200}(ثبت نام|ثبت‌نام|مهلت)[^.]{0,200}",txt[:15000]): print("DBG SENT", mm.group(0)[:400])
        links=re.findall(r'href="(https?://[^"]+)"[^>]*>([^<]{0,60})',body[:60000])
        print("DBG LINKS",[ (l,t) for l,t in links if "iranestekhdam" not in l and "e-estekhdam" not in l][:25])
