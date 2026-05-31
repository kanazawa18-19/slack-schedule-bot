"""GitHub Actions 内でトークンファイルを復元する。"""
import base64
import json
import os

TOKENS_DIR = os.environ.get("TOKENS_DIR", "tokens")
tokens_json = os.environ.get("TOKENS_JSON", "{}")

os.makedirs(TOKENS_DIR, exist_ok=True)

try:
    tokens = json.loads(tokens_json)
    for user_id, encoded in tokens.items():
        path = os.path.join(TOKENS_DIR, f"{user_id}.pickle")
        with open(path, "wb") as f:
            f.write(base64.b64decode(encoded))
    print(f"トークンを {len(tokens)} 件復元しました。")
except Exception as e:
    print(f"トークンの復元をスキップ: {e}")
