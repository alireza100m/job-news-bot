import requests, re, html, feedparser
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
base="https://www.e-estekhdam.com/%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85-%D9%87%D8%A7%DB%8C-%D8%B3%D8%B1%D8%A7%D8%B3%D8%B1%DB%8C"
for u in [base+"/feed", base+"/feed/", base]:
    r=requests.get(u,headers=UA,timeout=30); f=feedparser.parse(r.content)
    print("DBG",u[-6:],r.status_code,r.headers.get("content-type"),len(f.entries))
h=requests.get(base,headers=UA,timeout=30).text
for l in re.findall(r'<link[^>]+rss[^>]+>',h): print("DBG RSSLINK",l)
links=[]
for href,t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',h,re.S):
    t=re.sub(r"<[^>]+>","",t).strip()
    if len(t)>12 and ("استخدام" in t or "آزمون" in t): links.append((href,t))
seen=set()
for href,t in links:
    if href in seen: continue
    seen.add(href); print("DBG ITEM",t[:80],"|",href[:120])
    if len(seen)>=25: break
arts=[x for x in links if "e-estekhdam.com/" in x[0] or x[0].startswith("/")]
for href,t in arts[:2]:
    url=href if href.startswith("http") else "https://www.e-estekhdam.com"+href
    p=requests.get(url,headers=UA,timeout=30).text
    txt=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",re.sub(r"<(script|style)[^>]*>.*?</\1>"," ",p,flags=re.S))))
    print("DBG ART",url[:100])
    for m in re.finditer(r".{0,120}(مهلت|ثبت نام|ثبت‌نام|زمان برگزاری).{0,160}",txt): print("DBG SENT",m.group(0)[:300])
    ext=[(a,re.sub(r"<[^>]+>","",b).strip()[:40]) for a,b in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',p,re.S) if "e-estekhdam" not in a]
    print("DBG EXT",ext[:15])
