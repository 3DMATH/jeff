"""Chip-scoped Ollama inference client.

Follows the C2D2 pattern: pure HTTP against localhost Ollama.
Model is specified by the chip manifest, loaded on mount.
"""

import json
import os
import urllib.request
import urllib.error


OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
CHIP_MODEL = os.environ.get("CHIP_MODEL", "qwen2.5:7b-instruct-q4_K_M")


class ChipInferenceError(Exception):
    """Raised when inference fails."""
    pass


def _post(path, payload, timeout=120):
    """POST JSON to Ollama and return parsed response."""
    url = OLLAMA_URL.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ChipInferenceError("Ollama unavailable at %s: %s" % (url, exc))
    except Exception as exc:
        raise ChipInferenceError("Inference failed: %s" % exc)


def generate(prompt, model=None, system=None, max_tokens=2048, temperature=0.7):
    """Generate text using the chip model.

    Args:
        prompt: User prompt text.
        model: Override model name (defaults to CHIP_MODEL).
        system: Optional system prompt.
        max_tokens: Maximum response tokens.
        temperature: Sampling temperature.

    Returns:
        Response text string.
    """
    model = model or CHIP_MODEL
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    if system:
        payload["system"] = system

    result = _post("/api/generate", payload)
    return result.get("response", "")


def chat(messages, model=None, max_tokens=2048, temperature=0.7, tools=None):
    """Chat completion with tool support.

    Args:
        messages: List of {role, content} dicts.
        model: Override model name.
        max_tokens: Maximum response tokens.
        temperature: Sampling temperature.
        tools: Optional list of tool definitions for function calling.

    Returns:
        Dict with 'message' key containing the response.
    """
    model = model or CHIP_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    if tools:
        payload["tools"] = tools

    result = _post("/api/chat", payload)
    return result.get("message", {})


EMBED_MODEL = os.environ.get("CHIP_EMBED_MODEL", "nomic-embed-text")


def embed(text, model=None):
    """Generate embedding vector for text.

    Args:
        text: String to embed.
        model: Override embedding model (defaults to CHIP_EMBED_MODEL).

    Returns:
        List of floats (embedding vector).
    """
    model = model or EMBED_MODEL
    payload = {
        "model": model,
        "input": text,
    }
    result = _post("/api/embed", payload, timeout=30)
    embeddings = result.get("embeddings", [])
    if embeddings:
        return embeddings[0]
    return []


def embed_batch(texts, model=None):
    """Generate embeddings for multiple texts in one call.

    Args:
        texts: List of strings to embed.
        model: Override embedding model.

    Returns:
        List of embedding vectors.
    """
    model = model or EMBED_MODEL
    payload = {
        "model": model,
        "input": texts,
    }
    result = _post("/api/embed", payload, timeout=120)
    return result.get("embeddings", [])


def status():
    """Check Ollama availability and loaded models.

    Returns:
        Dict with host, available, models, chip_model_loaded.
    """
    try:
        url = OLLAMA_URL.rstrip("/") + "/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {
            "host": OLLAMA_URL,
            "available": False,
            "models": [],
            "chip_model_loaded": False,
        }

    models = [m.get("name", "") for m in data.get("models", [])]
    chip_loaded = any(CHIP_MODEL.split(":")[0] in m for m in models)

    return {
        "host": OLLAMA_URL,
        "available": True,
        "models": models,
        "chip_model": CHIP_MODEL,
        "chip_model_loaded": chip_loaded,
    }
