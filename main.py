import os
import requests
from flask import Flask, request
from supabase import create_client
from groq import Groq

app = Flask(__name__)

# Клиенты инициализируются через переменные окружения
supabase = create_client(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_KEY'))
groq_client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
MODEL_NAME = "llama-3.1-8b-instant"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': text})

def load_history(chat_id):
    data = supabase.table('users').select('history').eq('chat_id', chat_id).execute()
    if data.data:
        return data.data[0].get('history', [])
    else:
        supabase.table('users').insert({'chat_id': chat_id, 'history': []}).execute()
        return []

def save_history(chat_id, history):
    supabase.table('users').upsert({'chat_id': chat_id, 'history': history}).execute()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if 'message' not in update:
        return 'OK'

    msg = update['message']
    chat_id = msg['chat']['id']
    text = msg.get('text', '')

    if text == '/start':
        send_telegram_message(chat_id, "Привет! Я бот с Groq и Supabase. Задай вопрос!")
        return 'OK'

    history = load_history(chat_id)
    history.append({"role": "user", "content": text})
    
    chat_completion = groq_client.chat.completions.create(
        messages=history,
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=1024
    )
    answer = chat_completion.choices[0].message.content
    
    history.append({"role": "assistant", "content": answer})
    if len(history) > 20:
        history = history[-20:]
    save_history(chat_id, history)

    send_telegram_message(chat_id, answer)
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
