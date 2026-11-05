import requests, re, html
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
base="https://www.e-estekhdam.com/%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85-%D9%87%D8%A7%DB%8C-%D8%B3%D8%B1%D8%A7%D8%B3%D8%B1%DB%8C"
h=requests.get(base,headers=UA,timeout=30).text
i=h.find("وزارت دفاع و پشتیبانی")
print("DBG HTML", repr(h[i-1500:i+300]).replace("\\n"," ")[:1800])
m=re.search(r'href="([^"]+)"[^>]*>[^<]*(?:<[^>]+>[^<]*){0,6}وزارت دفاع',h)
