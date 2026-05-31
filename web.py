import os
from flask import Flask, request
from slack_sdk import WebClient
import auth

flask_app = Flask(__name__)
_slack = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))


@flask_app.route("/oauth/callback")
def oauth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h1>認証がキャンセルされました</h1><p>{error}</p>", 400

    if not code or not state:
        return "<h1>エラー</h1><p>認証情報が不正です</p>", 400

    user_id = auth.complete_oauth(state, code)
    if not user_id:
        return "<h1>エラー</h1><p>セッションが切れました。もう一度 /日程調整 を実行してください。</p>", 400

    try:
        _slack.chat_postMessage(
            channel=user_id,
            text="✅ Google カレンダーとの連携が完了しました！\n`/日程調整` を実行してください。",
        )
    except Exception:
        pass

    return """
    <html><body style="font-family:sans-serif;text-align:center;padding:60px">
    <h1>✅ 認証完了！</h1>
    <p>Slackに戻って <code>/日程調整</code> を実行してください。</p>
    <p>このタブは閉じて大丈夫です。</p>
    </body></html>
    """


def run(port: int = 8080):
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)
