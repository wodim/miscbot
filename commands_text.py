import random

from telegram import Update
from telegram.ext import CallbackContext

from utils import get_random_line, ellipsis


def clean_fortune(fortune: str) -> str:
    """fixes the odd whitespace that fortunes have"""
    return fortune.replace(' \n', ' ').replace('  ', '\n').strip()


def get_fortune() -> str:
    """gets a fortune at random and cleans it"""
    with open('trolldb.txt', 'rt', encoding='utf8') as fp:
        fortunes = fp.read().split('%')[:-1]
    fortune = clean_fortune(random.choice(fortunes))
    return fortune


MAX_FORTUNE_RESULTS = 5
def search_fortunes(criteria: str) -> str:
    """searches the fortune database for fortunes that match the criteria and
    returns them and then None if there are more results"""
    with open('trolldb.txt', 'rt', encoding='utf8') as fp:
        fortunes = fp.read().split('%')[:-1]
    results = 0
    for fortune in fortunes:
        clean = clean_fortune(fortune)
        if criteria.lower() in clean.lower():
            results += 1
            yield clean
        if results >= MAX_FORTUNE_RESULTS:
            yield None
            return


def command_fortune(update: Update, context: CallbackContext) -> None:
    """handles the /fortune command, which prints a random fortune or a list of
    a max of MAX_FORTUNE_RESULTS that match the parameter"""
    def msg(text):
        context.bot.send_message(update.message.chat_id, ellipsis(text, 4000),
                                 disable_web_page_preview=True)
    if context.args:
        if fortunes := list(search_fortunes(' '.join(context.args))):
            for fortune in fortunes:
                msg(fortune if fortune else 'Too many results. I only showed the first %d.' % MAX_FORTUNE_RESULTS)
        else:
            msg('No results.')
    else:
        msg(get_fortune())


def command_tip(update: Update, context: CallbackContext) -> None:
    """handles the /tip command"""
    context.bot.send_message(update.message.chat_id,
                             get_random_line('tips.txt'),
                             disable_web_page_preview=True)


def command_oiga(update: Update, context: CallbackContext) -> None:
    """handles the /oiga command"""
    context.bot.send_message(update.message.chat_id,
                             get_random_line('oiga.txt'),
                             disable_web_page_preview=True)