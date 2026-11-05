import requests, re, html
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
base="https://www.e-estekhdam.com/%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85-%D9%87%D8%A7%DB%8C-%D8%B3%D8%B1%D8%A7%D8%B3%D8%B1%DB%8C"
h=requests.get(base,headers=UA,timeout=30).text
T=lambda x: re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",x))).strip()
items=re.findall(r'<a class="item[^"]*" href="([^"]+)"[^>]*>(.*?)</a>',h,re.S)
print("DBG N",len(items))
for href,body in items[:40]:
    title=T(re.search(r'class="title[^"]*">(.*?)</div>',body,re.S).group(1))
    sub=re.search(r'class="subtitle">(.*?)</div>',body,re.S); sub=T(sub.group(1)) if sub else ""
    vals=[T(v) for v in re.findall(r'class="v">(.*?)</div>',body,re.S)]
    print("DBG IT",title,"|",sub,"|",vals,"|",href)
for href,body in items:
    if "انتقال خون" in body:
        p=requests.get(href,headers=UA,timeout=30).text
        t=T(re.sub(r"<(script|style)[^>]*>.*?</\1>"," ",p,flags=re.S))
        print("DBG PTITLE", re.search(r"<title>(.*?)</title>",p,re.S).group(1)[:150])
        for m in re.finditer(r".{0,150}(شروع شد|آغاز شد|مهلت ثبت).{0,200}",t): print("DBG SENT",m.group(0)[:350])
        ext=[(a,T(b)[:40]) for a,b in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',p,re.S) if "e-estekhdam" not in a and "google" not in a and "linkedin" not in a and "twitter" not in a]
        print("DBG EXT",ext[:12]); break
