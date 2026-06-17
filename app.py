import os
import json
import datetime
import traceback
import fitz
from docx import Document
from PIL import Image
import pytesseract
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FileMessage, ImageMessage
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

# =================================
# 不同格式轉文字
# =================================

def extract_text(filepath, file_type):

    try:

        # PDF
        if file_type == "pdf":

            doc = fitz.open(filepath)

            text = ""

            for page in doc:
                text += page.get_text()

            return text


        # Word
        elif file_type == "docx":

            doc = Document(filepath)

            text = ""

            for p in doc.paragraphs:
                text += p.text + "\n"

            return text


        # 圖片OCR
        elif file_type == "image":

            img = Image.open(filepath)

            text = pytesseract.image_to_string(
                img,
                lang="chi_tra+eng"
            )

            return text


        return ""


    except Exception as e:

        print(
            f"文字解析錯誤:{e}"
        )

        return ""
# =================================
# AI產生測驗題
# =================================

def generate_quiz(text):

    prompt = f"""

你是一位教師。

請根據以下教材：

{text}


產生：

【選擇題】
5題
每題四個選項
標示答案


【是非題】
3題
附答案


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

# ==========================
# LINE文字訊息
# ==========================

@handler.add( MessageEvent,message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    try:
        reply = generate_quiz(user_msg)
    except Exception as e:

        print(
            f"Gemini error:{e}"
        )
        reply = ("AI錯誤：" + str(e))

    log_to_sheets(user_msg, reply)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply[:4500])
    )


# ==========================
# LINE檔案(PDF / Word)
# ==========================

@handler.add(MessageEvent,message=FileMessage)
def handle_file(event):
    file_id = event.message.id
    filename = event.message.file_name
    content = line_bot_api.get_message_content(file_id)
    filepath = filename

    with open(
        filepath,
        "wb"
    ) as f:
    for chunk in content.iter_content():
        f.write(chunk)
    if filename.endswith(".pdf"):
        file_type = "pdf"
    elif filename.endswith(".docx"):
        file_type = "docx"
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="只支援 PDF 或 Word"
            )
        )
        return
    text = extract_text(
        filepath,
        file_type
    )
    quiz = generate_quiz(
        text
    )
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=quiz[:4500]
        )
    )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    file_id = event.message.id
    content = line_bot_api.get_message_content(
        file_id
    )
    filepath="image.jpg"
    with open(
        filepath,
        "wb"
    ) as f:
        for chunk in content.iter_content():
            f.write(chunk)
    text = extract_text(
        filepath,
        "image"
    )
    quiz = generate_quiz(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=quiz[:4500]
        )
    )
