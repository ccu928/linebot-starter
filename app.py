import os
import json
import datetime
import traceback
import fitz
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FileMessage
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = genai.Client(api_key=GEMINI_API_KEY)

def get_sheets_service():
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f'Sheets 連線錯誤: {e}')
        traceback.print_exc()
        return None

def log_to_sheets(user_msg, bot_reply):
    try:
        service = get_sheets_service()
        if not service:
            return
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        values = [[now, user_msg, bot_reply]]
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='工作表1!A:C',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        print(f'記錄成功: {now}')
    except Exception as e:
        print(f'記錄失敗: {e}')
        traceback.print_exc()

# ==========================
# 讀取 PDF 文字內容
# ==========================
def read_pdf(filepath):
    try:
        doc = fitz.open(filepath)

        text = ""

        for page in doc:
            text += page.get_text()

        return text

    except Exception as e:
        print(f"PDF讀取錯誤: {e}")
        return ""

# ==========================
# Gemini 產生測驗題
# ==========================
def generate_quiz(note_text):

    prompt = f"""
你是一位專業教師。

請根據以下教材內容：

產生：

【選擇題】
5題單選題
每題4個選項
標示正確答案

【是非題】
3題

請直接輸出題目。

教材內容：

{note_text}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_msg
        )
        reply = response.text
    except Exception as e:
        print(f'Gemini error: {e}')
        reply = f'錯誤：{str(e)}'
    log_to_sheets(user_msg, reply)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    app.run()

# ==========================
# 接收PDF檔案
# ==========================
@handler.add(MessageEvent, message=FileMessage)
def handle_file(event):

    try:

        file_id = event.message.id

        file_name = event.message.file_name

        # 只接受PDF
        if not file_name.lower().endswith(".pdf"):

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="目前僅支援 PDF 檔案上傳"
                )
            )

            return

        # 下載檔案
        message_content = line_bot_api.get_message_content(
            file_id
        )

        filepath = f"upload_{file_id}.pdf"

        with open(filepath, "wb") as fd:

            for chunk in message_content.iter_content():
                fd.write(chunk)

        print(f"檔案已下載: {filepath}")

        # 讀取PDF內容
        pdf_text = read_pdf(filepath)

        if not pdf_text.strip():

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="無法讀取PDF內容"
                )
            )

            return

        # 產生測驗題
        quiz = generate_quiz(pdf_text)

        # 記錄到 Google Sheets
        log_to_sheets(
            f"PDF:{file_name}",
            quiz[:1000]
        )

        # LINE訊息長度限制
        if len(quiz) > 4500:
            quiz = quiz[:4500] + "\n\n(內容過長已截斷)"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=quiz)
        )

        # 刪除暫存檔
        if os.path.exists(filepath):
            os.remove(filepath)

    except Exception as e:

        print(f"檔案處理錯誤: {e}")
        traceback.print_exc()

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"檔案處理失敗：{str(e)}"
            )
        )
