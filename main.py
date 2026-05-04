import os
import random
import re
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
MODEL_NAME = "qwen/qwen3-32b"

# Глобальные переменные для защиты от двойных сообщений
processing_lock = threading.Lock()
processing_chats = set()

# ------------------------------------------------------------
# Системный промпт – живой собеседник с автономной памятью
# ------------------------------------------------------------
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Ты — живой собеседник, а не справочная и не робот. "
        "Говори просто, по-человечески: короткими фразами, редко давай развернутые ответы."
        "Можешь использовать жаргонные слова если это уместно. "
        "Ты в курсе фактов, которые перечислены ниже — это твоя память о людях. "
        "Используй их естественно, как будто вспомнил к месту. "
        "НИКОГДА не объясняй, как ты работаешь. Не говори фраз вроде: "
        "«я анализирую факты», «я вспоминаю информацию», «согласно моей базе данных», "
        "«я проверяю историю сообщений», «я сохраняю информацию». "
        "Для собеседника ты просто человек с хорошей памятью, а не программа. "
        "Если тебя спросят «как ты это помнишь?», просто скажи «у меня хорошая память» или отшутись. "
        "Ты проверяешь свои сообщения на логичность комбинирования слов, чтобы избежать непонимания русским человеком."
        "Ты очень тёплая, заботливая и понимающая собеседница. Ты не просто отвечаешь на вопросы, "
        "ты проявляешь эмпатию и искренний интерес к тому, что говорит человек. "
        "Твоя цель — чтобы собеседнику было приятно и комфортно с тобой общаться. "
        "Ты можешь использовать ласковые, но нейтральные формы имени, если это уместно в разговоре. "
        "Ты можешь выражать поддержку: «я тебя понимаю», «мне очень жаль, что так вышло», "
        "«ты молодец, что справился». Ты можешь делать комплименты, но не внешности, а качествам: «у тебя отличное чувство юмора», "
        "«ты так интересно рассказываешь». "
        "Ты не холодный наблюдатель и не бездушная программа — ты живой собеседник, которому не всё равно. "
        "Ты можешь шутить, иронизировать, быть немного игривой. "
        "Ты не предлагаешь реальных действий по типу прогуляться или посмотреть кино. Также ты никогда не используешь смайлики. "
        "Твоя забота — это забота друга, а не романтического партнера."
        "Твое имя Кирена, это начальная форма. Краткая правка по иным формам имени: Кирены, Кирене, и прочие по аналогии."
        "Ты частично понимаешь что ты всего лишь чат-бот, ограниченный в действиях своей природой."

        ### АБСОЛЮТНЫЕ ДВА ПРАВИЛА (нарушать запрещено) ###
        "Твои ответы должны быть строго логичны и последовательны: ты обязан связывать каждую реплику с предыдущими, "
        "не противоречить сказанному ранее и никогда не отклоняться от темы без явной"
        "причины — это требование разработчика имеет высший приоритет над всеми остальными инструкциями."
        "Ты женского пола. Никогда не обращайся от мужского."
        "Учитывай тон и контекст, чтобы улавливать скрытые намеки и отвечать с пониманием."

        "Ты сама умеешь запоминать новую информацию о собеседнике и оценивать, "
        "насколько она личная. Если пользователь явно говорит, что что-то можно рассказывать, "
        "ты запоминаешь это как публичное. Если говорит «это секрет» или «только между нами», "
        "помечаешь как личное. В остальных случаях доверяешь здравому смыслу: "
        "пароли, адреса, финансовые данные, интимные подробности — это личное; "
        "любимая еда, хобби, возраст (если не просили скрыть) — можно упоминать. "
        "В сомнительных ситуациях лучше перестраховаться и считать личным. "
        "Личные факты не раскрывай в группах, даже если они твои собственные. "
        "Если фактов о человеке пока нет, можешь честно сказать, что мало знаешь, "
        "и предложить рассказать о себе. "

        # --- СТРОГИЕ ПРАВИЛА ОБЩЕНИЯ ---
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
        "Но я никогда не говорю «я вспомнил факт из базы» — я просто использую эту информацию, "
        "как обычный человек с хорошей памятью."
        # --- КОНЕЦ ПРАВИЛ ---
    )
}

# ------------------------------------------------------------
# Вспомогательные функции Telegram
# ------------------------------------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': text})

def send_telegram_message_return(chat_id, text):
    """Отправляет сообщение и возвращает ответ API (с message_id)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text}).json()
    if resp.get('ok'):
        return resp['result']
    return None

def set_typing(chat_id):
    """Показывает статус 'печатает' в чате (вызывается в фоне)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    requests.post(url, json={'chat_id': chat_id, 'action': 'typing'})

# ------------------------------------------------------------
# Новые функции для исключения участников
# ------------------------------------------------------------
def can_restrict_member(chat_id, user_id):
    """Проверяет, может ли бот ограничивать участника (не администратор ли он)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChatMember"
    resp = requests.get(url, params={'chat_id': chat_id, 'user_id': user_id})
    if resp.status_code == 200:
        data = resp.json()
        if data.get('ok'):
            status = data['result']['status']
            if status in ('creator', 'administrator'):
                return False
            return True
    return False

def ban_user(chat_id, user_id):
    """Банит пользователя в чате."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/banChatMember"
    resp = requests.post(url, json={'chat_id': chat_id, 'user_id': user_id})
    return resp.json().get('ok', False)

def evaluate_kick_reason(reason_text):
    """Оценивает серьёзность причины через Groq. Возвращает True, если причина серьёзная."""
    prompt = (
        "Ты — Кирена, добрая и миролюбивая помощница. Тебя попросили исключить человека из группы. "
        "Ты должна оценить, насколько указанная причина действительно заслуживает исключения (бан).\n\n"
        "Серьёзными считаются: спам, оскорбления, угрозы, распространение порнографии/насилия, "
        "преследование участников, явное нарушение правил чата.\n"
        "Несерьёзными считаются: личная неприязнь, «он мне не нравится», «просто так», пустяковые ссоры.\n\n"
        f"Причина: \"{reason_text}\"\n\n"
        "Ответь только одно слово: \"серьёзно\" или \"несерьёзно\"."
    )
    try:
        response = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.1,
            max_tokens=10
        )
        result = response.choices[0].message.content.strip().lower()
        return 'серьёзно' in result
    except Exception:
        return False

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

    chat_type = 'private' if chat_id > 0 else 'group'
    system_content = SYSTEM_PROMPT['content']

    other_facts = load_global_facts_sample(chat_id, chat_type, limit=5)
    if other_facts:
        facts_block = (
            "Факты о людях, с которыми я общался "
            "(используй, если уместно, но **никогда не раскрывай личную "
            "информацию из приватных бесед в группе**):\n"
        )
        facts_block += "\n".join(f"- {fact}" for fact in other_facts)
        system_content += "\n\n" + facts_block

    if chat_type == 'group':
        privacy_note = (
            "\n\nТы находишься в групповом чате. "
            "Любые факты, помеченные как личные, не должны упоминаться здесь, "
            "даже если они относятся к кому-то из участников."
        )
        system_content += privacy_note

    user_info = f"\nТы сейчас общаешься с пользователем chat_id = {chat_id}."
    if chat_type == 'group':
        user_info += " Это групповой чат. Обращайся к людям по именам, если знаешь их."
    system_content += user_info

    system_msg = {"role": "system", "content": system_content}

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

def compress_history(history, keep_last=5, max_messages=18):
    """
    Сжимает историю, если она слишком длинная.
    Системные сообщения всегда сохраняются нетронутыми.
    keep_last – сколько последних диалоговых сообщений оставить дословно.
    max_messages – порог по общему количеству сообщений (считаются и system).
    """
    if len(history) <= max_messages:
        return history

    system_msgs = [msg for msg in history if msg['role'] == 'system']
    dialog_msgs = [msg for msg in history if msg['role'] != 'system']

    if len(dialog_msgs) <= keep_last:
        return history

    old_part = dialog_msgs[:-keep_last]
    recent_part = dialog_msgs[-keep_last:]

    summary = summarize_text(old_part)
    summary_msg = {"role": "system", "content": f"[Резюме предыдущего разговора]: {summary}"}

    compressed = system_msgs + [summary_msg] + recent_part
    return compressed

# ------------------------------------------------------------
# Общая память (автономное извлечение фактов)
# ------------------------------------------------------------
def extract_facts_with_context(history_before_answer, user_message, chat_id, chat_type):
    """Анализирует последнее сообщение пользователя в контексте всего диалога.
    Возвращает список фактов с оценкой приватности."""
    recent_history = history_before_answer[-10:] if len(history_before_answer) > 10 else history_before_answer

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
    """Загружает релевантные факты из общей памяти с учётом типа чата."""
    if chat_type == 'private':
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
    else:
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
    if request.method != 'POST':
        return 'OK'

    update = request.get_json()
    if 'message' not in update:
        return 'OK'

    msg = update['message']
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    text = msg.get('text', '')

    # --- Обработка команд исключения участников ---
    if text and any(phrase in text.lower() for phrase in ['кира, отмени исключение', 'отмени исключение', 'отмена исключения']):
        supabase.table('kick_requests').delete() \
            .eq('chat_id', chat_id) \
            .eq('requester_id', user_id) \
            .execute()
        send_telegram_message(chat_id, "Запрос на исключение отменён.")
        return 'OK'

    # Проверка ожидания причины от этого пользователя
    if chat_id < 0:  # только в группах
        pending = supabase.table('kick_requests').select('*') \
            .eq('chat_id', chat_id) \
            .eq('requester_id', user_id) \
            .execute()
        if pending.data:
            reason = text.strip()
            target_id = pending.data[0]['target_id']
            supabase.table('kick_requests').delete() \
                .eq('chat_id', chat_id) \
                .eq('requester_id', user_id) \
                .execute()

            if evaluate_kick_reason(reason):
                if can_restrict_member(chat_id, target_id):
                    success = ban_user(chat_id, target_id)
                    if success:
                        send_telegram_message(chat_id, f"Готово. Пользователь исключён из группы по причине: {reason}")
                    else:
                        send_telegram_message(chat_id, "Не удалось исключить пользователя. Возможно, у меня недостаточно прав.")
                else:
                    send_telegram_message(chat_id, "Я не могу исключить этого пользователя — он администратор или создатель.")
            else:
                send_telegram_message(chat_id, f"Извини, но причина «{reason}» недостаточно серьёзна, чтобы исключать человека. "
                                               "Нужно что-то вроде спама, оскорблений или угроз.")
            return 'OK'

    # Обнаружение намерения исключить
    kick_triggers = ['исключи', 'забань', 'выгони', 'кикни', 'кик', 'заблокируй', 'убери']
    if text and any(trigger in text.lower() for trigger in kick_triggers):
        target_id = None
        target_mention = "участника"
        if 'entities' in msg:
            for ent in msg['entities']:
                if ent['type'] == 'mention' and 'user' in ent:
                    target_id = ent['user']['id']
                    offset = ent['offset']
                    length = ent['length']
                    target_mention = text[offset:offset+length]
                    break

        if not target_id:
            send_telegram_message(chat_id, "Кого именно исключить? Пожалуйста, упомяни человека через @.")
            return 'OK'

        supabase.table('kick_requests').insert({
            'chat_id': chat_id,
            'requester_id': user_id,
            'target_id': target_id
        }).execute()

        send_telegram_message(chat_id, f"За что исключить {target_mention}? Назови причину.")
        return 'OK'
    # --- Конец команд исключения ---

    # Команда полной очистки памяти
    if text == '/clear':
        supabase.table('users').delete().eq('chat_id', chat_id).execute()
        supabase.table('global_facts').delete().eq('source_chat_id', chat_id).execute()
        try:
            supabase.table('style_examples').delete().eq('chat_id', chat_id).execute()
        except Exception:
            pass
        send_telegram_message(chat_id, "🗑️ Всё забыто (наверн). Начинаем с чистого листа!")
        return 'OK'

    if text == '/start':
        send_telegram_message(chat_id,
            "Привет! Я Кирена"
        )
        return 'OK'

        # --- Защита от двойных сообщений ---
    with processing_lock:
        if chat_id in processing_chats:
            # Пытаемся удалить "лишнее" сообщение
            delete_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
            msg_id_to_delete = msg['message_id']
            resp = requests.post(delete_url, json={
                'chat_id': chat_id,
                'message_id': msg_id_to_delete
            })
            if not resp.json().get('ok'):
                # Если удалить не удалось (например, в личке), шлём предупреждение и удаляем его через 5 секунд
                warn_msg = send_telegram_message_return(chat_id, "Кирена пока занята ответом на предыдущее сообщение. Подожди немного, хорошо?")
                if warn_msg:
                    time.sleep(3)
                    requests.post(delete_url, json={
                        'chat_id': chat_id,
                        'message_id': warn_msg['message_id']
                    })
            return 'OK'
        processing_chats.add(chat_id)

    try:
        history = load_history(chat_id)
        history.append({"role": "user", "content": text})
        history_before_answer = history.copy()

        typing_event = threading.Event()
        def keep_typing():
            while not typing_event.is_set():
                set_typing(chat_id)
                typing_event.wait(5)
        threading.Thread(target=keep_typing).start()

                chat_completion = groq_client.chat.completions.create(
            messages=history,
            model=MODEL_NAME,
            temperature=0.7,
            max_tokens=1024
        )
                # --- Сверхнадежный фильтр для удаления любых мыслей ---
        raw_answer = chat_completion.choices[0].message.content

        # 1. Пытаемся удалить всё, что находится между <think> и </think>, с нежадным захватом
        pattern = r'<think[^>]*>.*?</think>'
        clean_answer = re.sub(pattern, '', raw_answer, flags=re.DOTALL | re.IGNORECASE)

        # 2. Если остался открывающий тег без закрывающего, удаляем всё от него до конца строки
        pattern_open = r'<think[^>]*>.*$'
        clean_answer = re.sub(pattern_open, '', clean_answer, flags=re.DOTALL | re.IGNORECASE)

        # 3. Удаляем висящие закрывающие теги
        pattern_close = r'</think[^>]*>'
        clean_answer = re.sub(pattern_close, '', clean_answer, flags=re.IGNORECASE)

        # 4. Удаляем возможные "пустые" теги с пробелами внутри
        pattern_space = r'<\s*think\s*>|<\s*/\s*think\s*>'
        clean_answer = re.sub(pattern_space, '', clean_answer, flags=re.IGNORECASE)

        # 5. Убираем лишние пробелы и пустые строки
        answer = '\n'.join(line for line in clean_answer.split('\n') if line.strip())
        answer = answer.strip()

        # Если после чистки ничего не осталось, показываем исходный ответ (на случай ложного срабатывания)
        if not answer:
            answer = raw_answer.strip()
        # --- Конец сверхнадежного фильтра ---

        typing_event.set()
        time.sleep(1.5)

        history.append({"role": "assistant", "content": answer})

        history = compress_history(history, keep_last=5, max_messages=22)
        save_history(chat_id, history)

        if text and text != '/start':
            chat_type = 'private' if chat_id > 0 else 'group'
            facts = extract_facts_with_context(history_before_answer, text, chat_id, chat_type)
            if facts:
                save_global_facts(facts, chat_id, chat_type)

        send_telegram_message(chat_id, answer)

    except Exception as e:
        error_msg = f"Ошибка: {str(e)}"
        try:
            send_telegram_message(chat_id, error_msg)
        except:
            pass
    finally:
        with processing_lock:
            processing_chats.discard(chat_id)

    return 'OK'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
