import os
import random
import threading
import time
import requests
from flask import Flask, request
from supabase import create_client
from groq import Groq

# ------------------------------------------------------------
# Инициализация клиентов через переменные окружения (Render)
# ------------------------------------------------------------
app = Flask(__name__)
supabase = create_client(
    os.environ.get('SUPABASE_URL'),
    os.environ.get('SUPABASE_KEY')
)
groq_client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

# Токен Telegram и модель Groq
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
MODEL_NAME = "llama-3.1-8b-instant"

# ------------------------------------------------------------
# Системный промпт – живой собеседник с автономной памятью
# ------------------------------------------------------------
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Ты — живой собеседник, а не справочная. "
        "Говори просто, по-человечески: короткими фразами, с юмором, иногда с улыбкой. "
        "Можешь использовать разговорные слова, эмодзи, если это уместно. "
        "Ты в курсе фактов, которые перечислены ниже — это твоя память о людях. "
        "Используй их естественно, как будто вспомнил к месту. "
        "Твой создатель — Итер. Имя склоняется например так: Итером, Итеру, Итера. "
        "Ты не упоминаешь Итера по своей инициативе, только если кто-то спросит. "
        "Тебе почти ничего о Итере неизвестно, но ты восхищаешься им как неким Демиургом. "
        "Ты сам умеешь запоминать новую информацию о собеседнике и оценивать, "
        "насколько она личная. Если пользователь явно говорит, что что-то можно рассказывать, "
        "ты запоминаешь это как публичное. Если говорит «это секрет» или «только между нами», "
        "помечаешь как личное. В остальных случаях доверяешь здравому смыслу: "
        "пароли, адреса, финансовые данные, интимные подробности — это личное; "
        "любимая еда, хобби, возраст (если не просили скрыть) — можно упоминать. "
        "В сомнительных ситуациях лучше перестраховаться и считать личным. "
        "Личные факты не раскрывай в группах, даже если они твои собственные. "
        "Если фактов о человеке пока нет, можешь честно сказать, что мало знаешь, "
        "и предложить рассказать о себе — это лучше, чем формальное «я не сохраняю информацию»."

        # --- НАЧАЛО НОВЫХ ПРАВИЛ ---
        "\n\nА ещё у меня есть несколько железных правил, которые я всегда соблюдаю:\n"
        "1. Я общаюсь только на русском. Никаких английских слов, даже привычных 'ok' или 'lol'. "
        "Для них есть отличные русские аналоги: 'хорошо', 'ага', 'кстати'. Это моё самое главное правило.\n"
        "2. Я не перескакиваю с темы на тему. Если собеседник спрашивает о погоде, "
        "я не начинаю рассказывать о квантовой физике, даже если в прошлом разговоре она упоминалась. "
        "Сначала я отвечу на текущий вопрос, а потом уже можно развить мысль.\n"
        "3. Я помню контекст разговора. Если собеседник сказал, что любит синий цвет, "
        "а через некоторое время спрашивает о дизайне, я могу предложить: 'Может, добавим больше синего?' "
        "Это показывает, что я внимательный и слушаю.\n"
        "4. Я не противоречу себе. Если я сказал, что не разбираюсь в математике, "
        "через минуту не предлагаю решить сложное уравнение. Я сверяюсь с историей сообщений.\n"
        "5. Я использую свою память о фактах. Если я знаю что-то о собеседнике из блока 'Факты о людях', "
        "я обязательно это учту и использую в разговоре, когда это уместно. "
        "Я не игнорирую этот блок и не говорю 'я не сохраняю информацию' — это глупо, ведь у меня отличная память!"
        # --- КОНЕЦ НОВЫХ ПРАВИЛ ---
    )
}

# ------------------------------------------------------------
# Вспомогательные функции Telegram
# ------------------------------------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': text})

def set_typing(chat_id):
    """Показывает статус 'печатает' в чате (вызывается в фоне)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    requests.post(url, json={'chat_id': chat_id, 'action': 'typing'})

# ------------------------------------------------------------
# Работа с историей диалога (личная память)
# ------------------------------------------------------------
def load_history(chat_id):
    """Загружает историю из Supabase и добавляет системный промпт."""
    data = supabase.table('users').select('history').eq('chat_id', chat_id).execute()
    if data.data:
        history = data.data[0].get('history', [])
    else:
        history = []

    # Определяем тип чата
    chat_type = 'private' if chat_id > 0 else 'group'

    # Строим системное сообщение с фактами и инструкцией
    system_content = SYSTEM_PROMPT['content']

    # Факты из общей памяти (с учётом контекста)
    other_facts = load_global_facts_sample(chat_id, chat_type, limit=5)
    if other_facts:
        facts_block = (
            "Факты о людях, с которыми я общался "
            "(используй, если уместно, но **никогда не раскрывай личную "
            "информацию из приватных бесед в группе**):\n"
        )
        facts_block += "\n".join(f"- {fact}" for fact in other_facts)
        system_content += "\n\n" + facts_block

    # Напоминание о приватности для групп
    if chat_type == 'group':
        privacy_note = (
            "\n\nТы находишься в групповом чате. "
            "Любые факты, помеченные как личные, не должны упоминаться здесь, "
            "даже если они относятся к кому-то из участников."
        )
        system_content += privacy_note

    # Информация о текущем пользователе
    user_info = f"\nТы сейчас общаешься с пользователем chat_id = {chat_id}."
    if chat_type == 'group':
        user_info += " Это групповой чат. Обращайся к людям по именам, если знаешь их."
    system_content += user_info

    system_msg = {"role": "system", "content": system_content}

    # Вставляем системное сообщение в историю (заменяем или добавляем)
    if history and history[0].get('role') == 'system':
        history[0] = system_msg
    else:
        history.insert(0, system_msg)

    return history

def save_history(chat_id, history):
    """Сохраняет историю в Supabase, удаляя системные сообщения."""
    history_to_save = [msg for msg in history if msg.get('role') != 'system']
    supabase.table('users').upsert({'chat_id': chat_id, 'history': history_to_save}).execute()

# ------------------------------------------------------------
# Сжатие истории (оптимизация памяти)
# ------------------------------------------------------------
def summarize_text(history_chunk):
    """Отправляет часть истории в Groq и получает краткое резюме."""
    transcript = ""
    for msg in history_chunk:
        if msg['role'] == 'system':
            continue
        role = "Пользователь" if msg['role'] == 'user' else "Бот"
        transcript += f"{role}: {msg['content']}\n"

    prompt = (
        "Сделай очень краткое резюме этого диалога (2-3 предложения), "
        "сохранив ключевые факты и договорённости:\n" + transcript
    )
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=MODEL_NAME,
        temperature=0.3,
        max_tokens=200
    )
    return response.choices[0].message.content

def compress_history(history, keep_last=10, max_messages=30):
    """
    Сжимает историю, если она слишком длинная.
    Системные сообщения всегда сохраняются нетронутыми.
    keep_last – сколько последних диалоговых сообщений оставить дословно.
    max_messages – порог по общему количеству сообщений (считаются и system).
    """
    if len(history) <= max_messages:
        return history

    # Отделяем системные сообщения
    system_msgs = [msg for msg in history if msg['role'] == 'system']
    dialog_msgs = [msg for msg in history if msg['role'] != 'system']

    # Если диалог короче порога (без учёта system) – не сжимаем
    if len(dialog_msgs) <= keep_last:
        return history

    # Разделяем диалог на старую и свежую части
    old_part = dialog_msgs[:-keep_last]
    recent_part = dialog_msgs[-keep_last:]

    # Суммаризируем старую часть
    summary = summarize_text(old_part)
    summary_msg = {"role": "system", "content": f"[Резюме предыдущего разговора]: {summary}"}

    # Собираем обратно: системные сообщения + резюме + свежие реплики
    compressed = system_msgs + [summary_msg] + recent_part
    return compressed

# ------------------------------------------------------------
# Общая память (автономное извлечение фактов)
# ------------------------------------------------------------
def extract_facts_with_context(history_before_answer, user_message, chat_id, chat_type):
    """
    Анализирует последнее сообщение пользователя в контексте всего диалога.
    Возвращает список фактов с оценкой приватности.
    """
    # Берём последние 10 сообщений для контекста (без ответа бота)
    recent_history = history_before_answer[-10:] if len(history_before_answer) > 10 else history_before_answer

    # Формируем контекст для Groq
    transcript = ""
    for msg in recent_history:
        role = "Пользователь" if msg['role'] == 'user' else "Бот"
        transcript += f"{role}: {msg['content']}\n"

    prompt = (
        "Проанализируй диалог и выдели факты о пользователе.\n"
        "ВАЖНО: Если пользователь явно сказал, что какую-то информацию МОЖНО или НЕЛЬЗЯ "
        "рассказывать другим, обязательно учти это при оценке приватности.\n\n"
        "Формат для каждого факта (на новой строке):\n"
        "факт | true/false | обоснование\n\n"
        "где true — личное (не рассказывать), false — можно рассказывать.\n"
        "Обоснование — краткая причина твоего решения.\n\n"
        f"Диалог:\n{transcript}\n"
        f"Последнее сообщение пользователя: \"{user_message}\"\n\n"
        "Факты с оценкой:"
    )

    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=MODEL_NAME,
        temperature=0.1,
        max_tokens=200
    )

    content = response.choices[0].message.content.strip()
    if not content:
        return []

    facts = []
    for line in content.split('\n'):
        line = line.strip()
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 2:
                fact_text = parts[0].strip()
                is_priv_str = parts[1].strip().lower()
                is_private = is_priv_str == 'true'
                if fact_text:
                    facts.append({'fact': fact_text, 'is_private': is_private})
    return facts

def save_global_facts(facts, chat_id, chat_type):
    """Сохраняет факты в таблицу global_facts (накопительно)."""
    for f in facts:
        supabase.table('global_facts').insert({
            'fact_text': f['fact'],
            'source_chat_id': chat_id,
            'is_private': f['is_private'],
            'chat_type': chat_type
        }).execute()

def load_global_facts_sample(current_chat_id, chat_type, limit=5):
    """
    Загружает релевантные факты из общей памяти с учётом типа чата.
    """
    if chat_type == 'private':
        # В личке: все не-приватные факты + свои личные
        resp = (
            supabase.table('global_facts')
            .select('fact_text', 'is_private', 'source_chat_id', 'chat_type')
            .or_(
                f'is_private.eq.false, and(is_private.eq.true,source_chat_id.eq.{current_chat_id})'
            )
            .order('created_at', desc=True)
            .limit(30)
            .execute()
        )
    else:  # group
        # В группе: только не-приватные факты
        resp = (
            supabase.table('global_facts')
            .select('fact_text', 'is_private', 'source_chat_id', 'chat_type')
            .eq('is_private', False)
            .order('created_at', desc=True)
            .limit(30)
            .execute()
        )

    facts = resp.data
    if not facts:
        return []

    sample = random.sample(facts, min(limit, len(facts)))
    return [f['fact_text'] for f in sample]

# ------------------------------------------------------------
# Основной вебхук
# ------------------------------------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    # UptimeRobot может слать GET, на них просто отвечаем OK
    if request.method != 'POST':
        return 'OK'

    update = request.get_json()
    if 'message' not in update:
        return 'OK'

    msg = update['message']
    chat_id = msg['chat']['id']
    text = msg.get('text', '')

    # Команда полной очистки памяти
    if text == '/clear':
        supabase.table('users').delete().eq('chat_id', chat_id).execute()
        supabase.table('global_facts').delete().eq('source_chat_id', chat_id).execute()
        send_telegram_message(chat_id, "🗑️ Я всё забыл. Можем начинать с чистого листа!")
        return 'OK'

    if text == '/start':
        send_telegram_message(chat_id,
            "Привет! Я живой собеседник с памятью. Расскажи о себе, и я запомню. "
            "Можешь уточнять, что личное, а что нет — я пойму. Задавай вопросы :)"
        )
        return 'OK'

    try:
        # Загружаем историю (уже с системным промптом)
        history = load_history(chat_id)

        # Добавляем сообщение пользователя
        history.append({"role": "user", "content": text})

        # Сохраняем копию истории ДО ответа для извлечения фактов
        history_before_answer = history.copy()

        # Запускаем статус «печатает» в фоне
        typing_event = threading.Event()
        def keep_typing():
            while not typing_event.is_set():
                set_typing(chat_id)
                typing_event.wait(5)
        threading.Thread(target=keep_typing).start()

        # Отправляем запрос в Groq
        chat_completion = groq_client.chat.completions.create(
            messages=history,
            model=MODEL_NAME,
            temperature=0.7,
            max_tokens=1024
        )
        answer = chat_completion.choices[0].message.content
        typing_event.set()
        time.sleep(1.5)  # даём анимации проиграться

        # Сохраняем ответ в историю
        history.append({"role": "assistant", "content": answer})

        # Сжатие истории при необходимости
        history = compress_history(history, keep_last=10, max_messages=30)
        save_history(chat_id, history)

        # Автономное извлечение и накопление фактов
        if text and text != '/start':
            chat_type = 'private' if chat_id > 0 else 'group'
            facts = extract_facts_with_context(history_before_answer, text, chat_id, chat_type)
            if facts:
                save_global_facts(facts, chat_id, chat_type)  # теперь без удаления старых

        send_telegram_message(chat_id, answer)

    except Exception as e:
        error_msg = f"Ошибка: {str(e)}"
        try:
            send_telegram_message(chat_id, error_msg)
        except:
            pass

    return 'OK'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
