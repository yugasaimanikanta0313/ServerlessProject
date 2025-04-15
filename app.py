import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/chat")
async def chat(req: Request):
    data = await req.json()
    prompt = data.get("prompt", "")

    # Replace this with your Qwen endpoint if using Ollama or custom server
    res = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "qwen2.5:1.5b", "prompt": prompt, "stream": False}
    )
    result = res.json()
    return {"response": result.get("response", "Sorry, I couldn't understand.")}
