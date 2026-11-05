import requests, re, urllib.parse as u
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
h=requests.get("https://www.iranestekhdam.ir/",headers=UA,timeout=30).text
for m in re.finditer(r'href="([^"]*category[^"]*)"',h):
    l=m.group(1)
    if any(k in u.unquote(l) for k in ["دولتی","نظامی","آموزش","بهداشت","قضا","آزمون"]): print("DBG RAW", l)
for page in ["https://iranestekhdam.ir/category/%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85%E2%80%8C%D9%87%D8%A7%DB%8C-%D8%AF%D9%88%D9%84%D8%AA%DB%8C-%D9%88-%D8%B3%D8%A7%D8%B2%D9%85%D8%A7%D9%86%DB%8C"]:
    r=requests.get(page,headers=UA,timeout=30); print("DBG PAGE",r.status_code,r.url)
    for f in re.findall(r'<link[^>]+application/rss\+xml[^>]+>',r.text): print("DBG FEED",u.unquote(f))
