import requests, re, feedparser, urllib.parse as u
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
for home in ["https://www.iranestekhdam.ir/","https://www.e-estekhdam.com/"]:
    try:
        h=requests.get(home,headers=UA,timeout=30).text
        links=sorted(set(re.findall(r'href="(https?://[^"]*(?:category|tag)/[^"]+)"',h)))
        for l in links[:80]: print("DBG LINK", u.unquote(l))
    except Exception as e: print("DBG ERR",home,e)
for q in ["استخدام","آزمون استخدامی","استخدام دولتی"]:
    for extra in ["","&hl=fa&gl=IR&ceid=IR:fa"]:
        url="https://news.google.com/rss/search?q="+u.quote(q)+extra
        r=requests.get(url,headers=UA,timeout=30); f=feedparser.parse(r.content)
        print("DBG GN",q,extra[:6],r.status_code,len(f.entries),repr(r.text[:120]) if not f.entries else f.entries[0].title)
