import json, os


def save_json(data: dict, path: str) -> str:
    """Saves dict to path. Creates parent dirs. Returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_text(content: str, path: str) -> str:
    """Saves raw text to path. Returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def load_text(path: str) -> str:
    with open(path, "r") as f:
        return f.read()
