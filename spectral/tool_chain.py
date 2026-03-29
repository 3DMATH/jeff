"""Merkle-VRGB tool chain -- derive a chip's root color from its tool set.

Each MCP tool hashes to a 6-char hex color. Tools pair up in a binary
Merkle tree. The root hash (truncated to 6 hex chars) is the chip's
identity color in VRGB colorspace.

Two chips with identical tools produce identical root colors.
Change one tool, the root shifts. Walk the tree to find the divergence.

Usage:
    from tool_chain import compute_chain
    chain = compute_chain(["chip_status", "chip_query", "chip_read_file"])
    print(chain["root"])   # "#A23DC7"
    print(chain["leaves"]) # {"chip_status": "#3A7F2B", ...}
"""

import hashlib
import json


def tool_to_hex(tool_name):
    """Hash a tool name to a 6-char hex color.

    Args:
        tool_name: Tool function name (e.g. "chip_status").

    Returns:
        6-char hex string with # prefix (e.g. "#3A7F2B").
    """
    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()
    return "#" + digest[:6].upper()


def hash_pair(hex_a, hex_b):
    """Hash two hex colors together to produce a parent node.

    Args:
        hex_a: First hex color (e.g. "#3A7F2B").
        hex_b: Second hex color (e.g. "#8C4DE1").

    Returns:
        6-char hex color derived from the pair.
    """
    combined = (hex_a.lstrip("#") + hex_b.lstrip("#")).encode("utf-8")
    digest = hashlib.sha256(combined).hexdigest()
    return "#" + digest[:6].upper()


def compute_chain(tool_names):
    """Compute the Merkle-VRGB chain for a set of tools.

    Args:
        tool_names: List of tool function names.

    Returns:
        Dict with:
            root: Root hex color (the chip's identity color).
            leaves: Dict mapping tool names to their hex colors.
            tree: List of tree levels, each a list of [left, right, parent] triples.
            depth: Number of tree levels.
    """
    if not tool_names:
        return {"root": "#000000", "leaves": {}, "tree": [], "depth": 0}

    # Sort for deterministic ordering
    sorted_tools = sorted(tool_names)

    # Compute leaves
    leaves = {}
    for name in sorted_tools:
        leaves[name] = tool_to_hex(name)

    # Build tree bottom-up
    current_level = [leaves[name] for name in sorted_tools]
    tree = []

    while len(current_level) > 1:
        next_level = []
        level_triples = []

        for i in range(0, len(current_level), 2):
            left = current_level[i]
            # If odd number, duplicate the last node
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            parent = hash_pair(left, right)
            next_level.append(parent)
            level_triples.append([left, right, parent])

        tree.append(level_triples)
        current_level = next_level

    root = current_level[0] if current_level else "#000000"

    return {
        "root": root,
        "leaves": leaves,
        "tree": tree,
        "depth": len(tree),
    }


def verify_chain(chain):
    """Verify a stored chain by recomputing from leaves.

    Args:
        chain: Dict with root, leaves, tree as returned by compute_chain.

    Returns:
        Dict with valid (bool) and divergence (str or None).
    """
    if not chain.get("leaves"):
        return {"valid": True, "divergence": None}

    recomputed = compute_chain(list(chain["leaves"].keys()))

    if recomputed["root"] == chain["root"]:
        return {"valid": True, "divergence": None}

    # Find divergence point
    for level_idx, (stored_level, recomp_level) in enumerate(
        zip(chain.get("tree", []), recomputed.get("tree", []))
    ):
        for triple_idx, (stored_triple, recomp_triple) in enumerate(
            zip(stored_level, recomp_level)
        ):
            if stored_triple != recomp_triple:
                return {
                    "valid": False,
                    "divergence": "level %d, node %d: stored %s vs computed %s" % (
                        level_idx, triple_idx, stored_triple[2], recomp_triple[2]
                    ),
                }

    return {"valid": False, "divergence": "root mismatch: %s vs %s" % (chain["root"], recomputed["root"])}


def chain_to_json(chain):
    """Serialize a chain for storage in heartbeat.json."""
    return json.dumps(chain, indent=2, ensure_ascii=False)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: tool_chain.py <tool_name> [tool_name ...]")
        print("       tool_chain.py --verify <chain.json>")
        sys.exit(1)

    if sys.argv[1] == "--verify":
        with open(sys.argv[2]) as f:
            chain = json.load(f)
        result = verify_chain(chain)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    tools = sys.argv[1:]
    chain = compute_chain(tools)
    print(chain_to_json(chain))
