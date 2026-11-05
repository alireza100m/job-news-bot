import os, requests
T=os.environ["GITHUB_TOKEN"]
H={"Authorization":f"Bearer {T}","Content-Type":"application/json","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
r=requests.get("https://models.github.ai/catalog/models",headers=H,timeout=30)
print("DBG catalog",r.status_code,r.headers.get("content-type"),repr(r.text[:200]))
for url in ["https://models.github.ai/inference/chat/completions","https://models.github.ai/orgs/alireza100m/inference/chat/completions"]:
    r=requests.post(url,headers=H,json={"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"say hi"}]},timeout=60,allow_redirects=False)
    print("DBG",url,r.status_code,r.headers.get("content-type"),dict((k,v) for k,v in r.headers.items() if k.lower().startswith(("x-","server","via"))),repr(r.text[:300]))
