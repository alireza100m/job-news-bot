import os, requests
T=os.environ["GITHUB_TOKEN"]
body={"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"say hi"}]}
for url in ["https://models.github.ai/inference/chat/completions","https://models.inference.ai.azure.com/chat/completions"]:
    for model in ["openai/gpt-4o-mini","gpt-4o-mini"]:
        body["model"]=model
        try:
            r=requests.post(url,headers={"Authorization":f"Bearer {T}","Content-Type":"application/json","Accept":"application/json"},json=body,timeout=60,allow_redirects=False)
            print("DBG",url,model,r.status_code,r.headers.get("content-type"),r.headers.get("location"),repr(r.text[:200]))
        except Exception as e: print("DBG",url,model,"ERR",e)
