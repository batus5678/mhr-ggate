import os, httpx, uvicorn, base64
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()
SECRET = "YOUR_SECRET_KEY" # MUST MATCH Code.gs[cite: 3]
XRAY_URL = "http://127.0.0.1:10000/mhr" # Path must match xray_server.json[cite: 3, 4]

@app.post("/{path:path}")
async def relay(request: Request):
      if request.headers.get("X-MHR-Secret") != SECRET:
        return PlainTextResponse("Forbidden", status_code=403)
    
    body = base64.b64decode(await request.body())
    async with httpx.AsyncClient() as client:
        resp = await client.post(XRAY_URL, content=body)
    
       return PlainTextResponse(base64.b64encode(resp.content).decode())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080) 
