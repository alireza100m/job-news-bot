import requests, feedparser, json, re, html
for s in json.load(open("sources.json",encoding="utf-8")):
    r=requests.get(s["url"],headers={"User-Agent":"Mozilla/5.0"},timeout=30); f=feedparser.parse(r.content)
    for e in f.entries[:4]:
        su=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html.unescape(e.get("summary",""))))
        c=e.get("content",[{}])[0].get("value","") if e.get("content") else ""
        c=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html.unescape(c)))
        print("DBG|", s["name"], "|", e.get("title"), "|S:", su[:500], "|C:", len(c), c[:900])
