
import redis
import psycopg2
import time
import uuid
import requests

r = redis.Redis(host="redis", port=6379, decode_responses=True)

def chunk_text(text, size=500):
    return [text[i:i+size] for i in range(0, len(text), size)]

print("Worker started...")

while True:
    job = r.brpop("jobs", timeout=5)
    if job:
        data = job[1]
        if data.startswith("chunk:"):
            _, doc_id, content = data.split(":", 2)
            chunks = chunk_text(content)
            conn = psycopg2.connect(dbname="refinery", user="refinery", password="refinery", host="postgres")
            cur = conn.cursor()
            for i, chunk in enumerate(chunks):
                cur.execute(
                    "INSERT INTO research.document_chunks (id, document_id, chunk_index, content) VALUES (%s,%s,%s,%s)",
                    (str(uuid.uuid4()), doc_id, i, chunk)
                )
            conn.commit()
            conn.close()
            print(f"Chunked document {doc_id} into {len(chunks)} chunks")
        # LLM evaluation placeholder
        # You can call local Ollama like:
        # requests.post("http://llm:11434/api/generate", json={...})
    time.sleep(1)
