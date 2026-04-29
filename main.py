import os
import requests
from flask import Flask, request
from supabase import create_client
from groq import Groq

# Инициализация клиентов
app = Flask(__name__)
supabase = create_client(os.environ.get('https://dkvxsnnqejircflgbeop.supabase.co'), os.environ.get('sb_publishable_tbpfVpzqpjRvXHJIrgUWEg_w9_fERH8'))
groq_client = Groq(api_key=os.environ.get('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'))

TELEGRAM_TOKEN = os.environ.get('8744004969:AAHzBpcln3b3jBpbMegEoPsh1oOdlyJ8SmA')
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

    # Управление историей
    history = load_history(chat_id)
    history.append({"role": "user", "content": text})
    
    # Отправка в ИИ
    chat_completion = groq_client.chat.completions.create(
        messages=history,
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=1024
    )
    answer = chat_completion.choices[0].message.content
    
    # Сохранение контекста
    history.append({"role": "assistant", "content": answer})
    if len(history) > 20:
        history = history[-20:]
    save_history(chat_id, history)

    send_telegram_message(chat_id, answer)
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
