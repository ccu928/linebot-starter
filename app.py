import os
import json
from datetime import datetime, timedelta
import traceback
import fitz
from docx import Document
import pytesseract
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FileMessage, ImageMessage
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from linebot.models import (
    FlexSendMessage
)

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
        now = (
            datetime.utcnow()
            + timedelta(hours=8)
        ).strftime("%Y-%m-%d %H:%M:%S")
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
    你是一位大學教師。
    
    請根據提供的教材內容產生5題選擇題。
    
    規則：
    
    1. 所有題目必須直接來自教材內容
    2. 不可使用教材外知識
    3. 不可自行推測
    4. 題目必須能在教材中找到答案
    5. 若教材內容不足，請回傳：
    
    {{
      "error":"教材內容不足"
    }}
    
    請只輸出JSON
    
    格式：
    
    {{
      "questions":[
        {{
          "question":"題目",
          "A":"選項A",
          "B":"選項B",
          "C":"選項C",
          "D":"選項D",
          "answer":"A"
        }}
      ]
    }}
    
    教材：
    
    {text}
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    user_msg = event.message.text

    try:

        quiz = generate_quiz(user_msg)
        log_to_sheets(
            user_msg,
            quiz
        )

        # 去掉 Gemini 可能加的 ```json
        quiz = quiz.replace("```json", "")
        quiz = quiz.replace("```", "")
        quiz = quiz.strip()

        quiz_data = json.loads(quiz)

        flex_msg = create_quiz_flex(
            quiz_data["questions"]
        )

        line_bot_api.reply_message(
            event.reply_token,
            flex_msg
        )

    except Exception as e:

        print(f"Gemini error:{e}")

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"AI錯誤：{str(e)}"
            )
        )
#Flex Message 呈現#
def create_quiz_flex(questions):
    bubbles = []
    # ===== 每一題一張卡 =====

    for idx, q in enumerate(questions):
        bubble = {
            "type":"bubble",
            "size":"mega",
            "body":{
                "type":"box",
                "layout":"vertical",
                "contents":[

                    {
                        "type":"text",
                        "text":f"📚 第 {idx+1} 題",
                        "weight":"bold",
                        "size":"xl"
                    },

                    {
                        "type":"separator",
                        "margin":"md"
                    },

                    {
                        "type":"text",
                        "text":q["question"],
                        "wrap":True,
                        "weight":"bold",
                        "margin":"md"
                    },

                    {
                        "type":"text",
                        "text":f"🅰 {q['A']}",
                        "wrap":True
                    },

                    {
                        "type":"text",
                        "text":f"🅱 {q['B']}",
                        "wrap":True
                    },

                    {
                        "type":"text",
                        "text":f"🅲 {q['C']}",
                        "wrap":True
                    },

                    {
                        "type":"text",
                        "text":f"🅳 {q['D']}",
                        "wrap":True
                    }

                ]
            }
        }
        bubbles.append(bubble)

    # ===== 答案卡 =====

    answers = []

    for i,q in enumerate(questions):

        answers.append(
            f"{i+1}. {q['answer']}"
        )


    bubbles.append({
        "type":"bubble",
        "size":"mega",
        "body":{
            "type":"box",
            "layout":"vertical",
            "contents":[

                {
                    "type":"text",
                    "text":"📖 參考答案",
                    "weight":"bold",
                    "size":"xl"
                },

                {
                    "type":"separator",
                    "margin":"md"
                },

                {
                    "type":"text",
                    "text":"\n".join(answers),
                    "wrap":True
                }

            ]
        }
    })

    # ===== Carousel =====

    return FlexSendMessage(
        alt_text="AI測驗",
        contents={
            "type":"carousel",
            "contents":bubbles
        }
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
    
    quiz = generate_quiz(text)

    quiz = quiz.replace(
        "```json",
        ""
    )
    
    quiz = quiz.replace(
        "```",
        ""
    )
    
    quiz = quiz.strip()
    
    quiz_data = json.loads(
        quiz
    )
    
    flex_msg = create_quiz_flex(
        quiz_data["questions"]
    )
    
    line_bot_api.reply_message(
        event.reply_token,
        flex_msg
    )
  
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    file_id = event.message.id
    content = line_bot_api.get_message_content(
        file_id
    )
    filepath="image.jpg"
    with open(filepath,"wb") as f:
        for chunk in content.iter_content():
            f.write(chunk)
    text = extract_text(
        filepath,
        "image"
    )
    quiz = generate_quiz(text)
    quiz = quiz.replace("json","") 
    quiz = quiz.replace("","")
    quiz = quiz.strip()
    quiz_data = json.loads(quiz)
    flex_msg = create_quiz_flex(
        quiz_data["questions"]
    )
    line_bot_api.reply_message(
        event.reply_token,
        flex_msg
    )
