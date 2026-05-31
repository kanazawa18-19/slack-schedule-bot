"""
ローカルのトークンファイルを GitHub Secrets 用の JSON 文字列に変換する。

使い方:
  python scripts/export_tokens.py

出力された文字列を GitHub の TOKENS_JSON シークレットに貼り付ける。
"""
import base64
import json
import os

TOKENS_DIR = os.environ.get("TOKENS_DIR", "tokens")

tokens = {}
if os.path.exists(TOKENS_DIR):
    for fname in os.listdir(TOKENS_DIR):
        if fname.endswith(".pickle"):
            user_id = fname.replace(".pickle", "")
            with open(os.path.join(TOKENS_DIR, fname), "rb") as f:
                tokens[user_id] = base64.b64encode(f.read()).decode()

if tokens:
    print("以下を GitHub Secrets の TOKENS_JSON に貼り付けてください:\n")
    print(json.dumps(tokens))
else:
    print("tokens/ にファイルが見つかりませんでした。")
    print("先に python app.py を起動してユーザー認証を済ませてください。")
