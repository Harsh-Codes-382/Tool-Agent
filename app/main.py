from fastapi import FastAPI
from pydantic import BaseModel

from app.agent import run_agent

app = FastAPI()


class AskQuestion(BaseModel):
    question: str

@app.post("/ask")
def ask(req: AskQuestion):
    return {"answer": run_agent(req.question)}

