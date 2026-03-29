"""Build a vector search index on the chip surface.

Chunks content from .jeff/docs/ and datasets/, embeds via Ollama,
stores the index at .jeff/index/ as pure JSON. No external
dependencies beyond Ollama running locally.

Usage:
    python3 build_index.py /Volumes/YELLOW
"""

import json
import os
import sys
import math


def chunk_markdown(text, source, max_chars=800):
    """Split markdown into chunks by headers and paragraphs."""
    chunks = []
    current = []
    current_header = source

    for line in text.split("\n"):
        if line.startswith("## ") or line.startswith("# "):
            if current:
                body = "\n".join(current).strip()
                if body and len(body) > 40:
                    chunks.append({
                        "text": body,
                        "source": source,
                        "section": current_header,
                    })
            current = [line]
            current_header = line.lstrip("#").strip()
        else:
            current.append(line)
            joined = "\n".join(current)
            if len(joined) > max_chars:
                body = joined.strip()
                if body:
                    chunks.append({
                        "text": body,
                        "source": source,
                        "section": current_header,
                    })
                current = []

    if current:
        body = "\n".join(current).strip()
        if body and len(body) > 40:
            chunks.append({
                "text": body,
                "source": source,
                "section": current_header,
            })

    return chunks


def chunk_json_dataset(data, source):
    """Turn a JSON dataset into searchable text chunks."""
    chunks = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text = json.dumps(item, indent=2)
                name = item.get("name", item.get("label", item.get("symbol", "")))
                chunks.append({
                    "text": text,
                    "source": source,
                    "section": str(name),
                })
    elif isinstance(data, dict):
        for key, val in data.items():
            text = "%s: %s" % (key, json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val))
            chunks.append({
                "text": text,
                "source": source,
                "section": key,
            })

    return chunks


def cosine_similarity(a, b):
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_index(volume_path):
    """Build search index from card content."""

    # Add inference.py to path (it lives in mcp/ on the card or chip/ in repo)
    mcp_dir = os.path.join(volume_path, "mcp")
    if os.path.isdir(mcp_dir):
        sys.path.insert(0, mcp_dir)
    chip_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, chip_dir)

    import inference

    # Check Ollama
    st = inference.status()
    if not st.get("available"):
        print("ERROR: Ollama not available at %s" % inference.OLLAMA_URL)
        sys.exit(1)

    print("  Building search index...")

    # Collect chunks
    all_chunks = []

    # Markdown docs
    docs_dir = os.path.join(volume_path, ".jeff", "docs")
    if os.path.isdir(docs_dir):
        for fname in sorted(os.listdir(docs_dir)):
            if fname.endswith(".md"):
                path = os.path.join(docs_dir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                chunks = chunk_markdown(text, fname)
                all_chunks.extend(chunks)
                print("    %s: %d chunks" % (fname, len(chunks)))

    # JSON datasets
    datasets_dir = os.path.join(volume_path, "datasets")
    if os.path.isdir(datasets_dir):
        for fname in sorted(os.listdir(datasets_dir)):
            if fname.endswith(".json"):
                path = os.path.join(datasets_dir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                chunks = chunk_json_dataset(data, fname)
                all_chunks.extend(chunks)
                print("    %s: %d chunks" % (fname, len(chunks)))

    if not all_chunks:
        print("  No content to index.")
        return

    print("  Total: %d chunks" % len(all_chunks))
    print("  Embedding...")

    # Embed in batches
    batch_size = 32
    all_embeddings = []
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        texts = [c["text"][:2000] for c in batch]
        embeddings = inference.embed_batch(texts)
        all_embeddings.extend(embeddings)
        done = min(i + batch_size, len(all_chunks))
        pct = int(done / len(all_chunks) * 100)
        sys.stdout.write("\r    [%s%s] %d%% (%d/%d)" % (
            "#" * (pct // 3), "-" * (33 - pct // 3),
            pct, done, len(all_chunks)
        ))
        sys.stdout.flush()

    sys.stdout.write("\n")

    # Build index
    index = {
        "version": 1,
        "embed_model": inference.EMBED_MODEL,
        "chunk_count": len(all_chunks),
        "dimensions": len(all_embeddings[0]) if all_embeddings else 0,
        "chunks": [],
    }

    for chunk, embedding in zip(all_chunks, all_embeddings):
        index["chunks"].append({
            "text": chunk["text"],
            "source": chunk["source"],
            "section": chunk["section"],
            "embedding": embedding,
        })

    # Write index
    index_dir = os.path.join(volume_path, ".jeff", "index")
    os.makedirs(index_dir, exist_ok=True)
    index_path = os.path.join(index_dir, "search.json")

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    size_mb = os.path.getsize(index_path) / 1_000_000
    print("  Index written: %s (%.1fMB, %d chunks, %d dimensions)" % (
        index_path, size_mb, len(all_chunks),
        index["dimensions"],
    ))


def search(index_path, query_embedding, top_k=5):
    """Search the index with a query embedding."""
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    results = []
    for chunk in index["chunks"]:
        sim = cosine_similarity(query_embedding, chunk["embedding"])
        results.append({
            "text": chunk["text"],
            "source": chunk["source"],
            "section": chunk["section"],
            "score": round(sim, 4),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 build_index.py /Volumes/MYCARD")
        sys.exit(1)
    build_index(sys.argv[1])
