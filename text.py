import random

from telegram import Update
from telegram.constants import MAX_MESSAGE_LENGTH
from telegram.ext import CallbackContext

from utils import _config, ellipsis, get_random_line


def clean_fortune(fortune: str) -> str:
    """fixes the odd whitespace that fortunes have"""
    return fortune.replace(' \n', ' ').replace('  ', '\n').strip()


def get_fortune() -> str:
    """gets a fortune at random and cleans it"""
    with open('trolldb.txt', 'rt', encoding='utf8') as fp:
        fortunes = fp.read().split('%')[:-1]
    fortune = clean_fortune(random.choice(fortunes))
    return fortune


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
        if results >= int(_config('fortune_max_results')):
            yield None
            return


def command_fortune(update: Update, context: CallbackContext) -> None:
    """handles the /fortune command, which prints a random fortune or a list of
    a max of fortune_max_results that match the parameter"""
    def msg(text):
        update.message.reply_text(ellipsis(text, MAX_MESSAGE_LENGTH),
                                  disable_web_page_preview=True, quote=False)
    if context.args:
        if fortunes := list(search_fortunes(' '.join(context.args))):
            for fortune in fortunes:
                msg(fortune if fortune else 'Too many results. I only showed the first %d.' % int(_config('fortune_max_results')))
        else:
            msg('No results.')
    else:
        msg(get_fortune())


def command_tip(update: Update, context: CallbackContext) -> None:
    """handles the /tip command"""
    update.message.reply_text(get_random_line('tips.txt'),
                              disable_web_page_preview=True, quote=False)


def command_oiga(update: Update, context: CallbackContext) -> None:
    """handles the /oiga command"""
    update.message.reply_text(get_random_line('oiga.txt'),
                              disable_web_page_preview=True, quote=False)


def command_haiku(update: Update, _: CallbackContext) -> None:
    """sends a haiku"""
    update.message.reply_text(get_random_line('haiku5.txt') +
                              get_random_line('haiku7.txt') +
                              get_random_line('haiku5.txt'), quote=False)
