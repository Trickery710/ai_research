
from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2
import uuid
import redis

app = FastAPI()
r = redis.Redis(host="redis", port=6379, decode_responses=True)

class IngestRequest(BaseModel):
    title: str
    source_url: str
    content: str

@app.post("/ingest")
def ingest(doc: IngestRequest):
    doc_id = str(uuid.uuid4())
    conn = psycopg2.connect(dbname="refinery", user="refinery", password="refinery", host="postgres")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO research.documents (id, title, source_url, content_hash, processing_stage) VALUES (%s,%s,%s,%s,'pending')",
        (doc_id, doc.title, doc.source_url, str(hash(doc.content)))
    )
    conn.commit()
    conn.close()
    r.lpush("jobs", f"chunk:{doc_id}:{doc.content}")
    return {"status": "queued", "id": doc_id}

@app.get("/health")
def health():
    return {"status": "running"}
