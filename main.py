import os
import requests
from flask import Flask, request
from supabase import create_client
from groq import Groq
# ... (все ваши текущие импорты, например, import requests, from flask import Flask, request и т.д.)
# ...
import threading
import time

# ... (здесь может быть код с app = Flask(__name__), отправкой сообщений и т.д.)
# ...
app = Flask(__name__)

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
        send_telegram_message(chat_id, "Привет! Я бот с Groq созданный при помощи закрытой модели Mythos Итером. Пообщаемся?")
        return 'OK'

    history = load_history(chat_id)
    history.append({"role": "user", "content": text})
    
    # Запускаем статус «печатает» и готовим ответ
    typing_event = threading.Event()
    def keep_typing():
        """Функция, которая будет каждые 5 секунд обновлять статус 'печатает', пока не придет ответ."""
        while not typing_event.is_set():
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
            requests.post(url, json={'chat_id': chat_id, 'action': 'typing'})
            typing_event.wait(5) # ждем 5 секунд или сигнала к завершению
    # Запускаем keep_typing в отдельном потоке
    threading.Thread(target=keep_typing).start()

    # Здесь ваш код отправки сообщения в Groq и получения ответа
    chat_completion = groq_client.chat.completions.create(
        messages=history,
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=1024
    )
    answer = chat_completion.choices[0].message.content
    
    # Как только ответ получен, останавливаем статус «печатает»
    typing_event.set()
    # Небольшая пауза, чтобы анимация не исчезла за 0.1 секунды
    time.sleep(1.5)
    
    history.append({"role": "assistant", "content": answer})
    if len(history) > 20:
        history = history[-20:]
    save_history(chat_id, history)

    send_telegram_message(chat_id, answer)
    return 'OK'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
