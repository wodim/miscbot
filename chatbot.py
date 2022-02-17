import random
import statistics

from telegram import ChatAction, Update
from telegram.ext import CallbackContext

from utils import _config, _config_list, get_random_line, logger, remove_punctuation


def sub_get_reply(chat_id: int, input_: str, stemmer, stopwords) -> str:
    """returns an appropriate reply to a message depending on its chat_id"""
    input_keywords = []
    for keyword in remove_punctuation(input_.lower()).split(' '):
        keyword = stemmer.stem(keyword)
        if keyword not in stopwords:
            input_keywords.append(keyword)
    if len(input_keywords) == 0:
        return None

    with open(f'chat{chat_id}.txt', 'rt', encoding='utf8') as fp:
        last_line, last_score, next_line = None, 0, None
        matches = []
        for line in fp:
            try:
                tokenized_line, real_line = line.split('\t')
            except ValueError:
                logger.info('Error splitting this log line: %s', repr(line))
            if last_line and line and not next_line:
                next_line = real_line
                matches.append((last_score, last_line, next_line))
            this_score = 0
            for k in input_keywords:
                if k in tokenized_line.split(' '):
                    this_score += 1
            if this_score:
                last_score = this_score
                last_line = line
                next_line = None

    if len(matches) == 0:
        return None
    median = statistics.median([x[0] for x in matches])
    return random.choice([x[2] for x in matches if x[0] >= median and x[2]])


def command_chatbot(update: Update, context: CallbackContext) -> None:
    """sends back a chatbot response"""
    my_username = f"@{context.bot_data['me'].username}".lower()
    if update.message.chat.id in _config_list('muted_groups', int):
        return
    if not (random.random() <= float(_config('chatbot_random_chance')) / 100 or
            my_username in update.message.text or
            (update.message.reply_to_message and
             update.message.reply_to_message.from_user.id == context.bot_data['me'].id)):
        return

    if (update.message.reply_to_message and update.message.reply_to_message.text and
            update.message.reply_to_message.from_user.id != context.bot_data['me'].id):
        text = update.message.reply_to_message.text
    elif update.message.text:
        text = update.message.text
    else:
        update.message.reply_text('?')

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.TYPING)

    try:
        reply = sub_get_reply(update.message.chat_id,
                              text.replace(my_username, ''),
                              context.bot_data['stemmer'],
                              context.bot_data['stopwords']) or get_random_line('noreply.txt')
        update.message.reply_text(reply)
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.TYPING)
