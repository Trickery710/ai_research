"""Client for Ollama LLM API (embeddings and text generation)."""
import requests
import json
from shared.config import Config


def generate_embedding(text, model=None, base_url=None):
    """Generate a 768-dimensional embedding vector.

    Args:
        text: Input text to embed.
        model: Model name override. Default: Config.EMBEDDING_MODEL.
        base_url: Ollama URL override. Default: Config.OLLAMA_BASE_URL.

    Returns:
        list[float]: The embedding vector (768 floats for nomic-embed-text).

    Raises:
        requests.exceptions.RequestException: On HTTP failure.
        KeyError: If response JSON lacks "embedding" key.
    """
    url = f"{base_url or Config.OLLAMA_BASE_URL}/api/embeddings"
    payload = {
        "model": model or Config.EMBEDDING_MODEL,
        "prompt": text
    }
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["embedding"]


def generate_completion(prompt, model=None, base_url=None, temperature=0.1,
                        system_prompt=None, format_json=False):
    """Generate a text completion from Ollama.

    Args:
        prompt: The user/instruction prompt.
        model: Model name override. Default: Config.REASONING_MODEL.
        base_url: Ollama URL override. Default: Config.OLLAMA_BASE_URL.
        temperature: Sampling temperature (lower = more deterministic).
        system_prompt: Optional system-level instruction.
        format_json: If True, request structured JSON output from Ollama.

    Returns:
        str: The generated text.
    """
    url = f"{base_url or Config.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model or Config.REASONING_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }
    if system_prompt:
        payload["system"] = system_prompt
    if format_json:
        payload["format"] = "json"

    response = requests.post(url, json=payload, timeout=300)
    response.raise_for_status()
    return response.json()["response"]


def ensure_model_available(model_name, base_url=None):
    """Check if a model is loaded in Ollama; pull it if not.

    This is blocking and may take minutes on first call.
    """
    url_base = base_url or Config.OLLAMA_BASE_URL
    tags_url = f"{url_base}/api/tags"

    try:
        response = requests.get(tags_url, timeout=30)
        response.raise_for_status()
        models = [m["name"] for m in response.json().get("models", [])]
        if model_name in models or f"{model_name}:latest" in models:
            print(f"Model {model_name} is already available.")
            return True
    except Exception as e:
        print(f"Could not check models: {e}")

    print(f"Pulling model {model_name} (this may take several minutes)...")
    pull_url = f"{url_base}/api/pull"
    response = requests.post(
        pull_url,
        json={"name": model_name},
        stream=True,
        timeout=1800
    )
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            try:
                status = json.loads(line)
                if "status" in status:
                    print(f"  {status['status']}")
            except json.JSONDecodeError:
                pass
    print(f"Model {model_name} is ready.")
    return True
