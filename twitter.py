import re

import feedparser
from telegram import Update
from telegram.ext import CallbackContext

from utils import _config, is_admin, get_url, logger


def _get_twitter_feeds() -> dict:
    """retrieves a {screen_name: [chat_id, chat_id, ...], ...} dict of all watched feeds"""
    if feeds := _config('twitter_feeds'):
        ret = {}
        for feed in feeds.split(','):
            screen_name, chat_id = feed.strip().split('|')
            try:
                ret[screen_name.lower()].append(int(chat_id))
            except KeyError:
                ret[screen_name.lower()] = [int(chat_id)]
        return ret.items()
    return {}


RX_ID = re.compile(r'(\d+)#m$')
def get_id_from_guid(permalink: str) -> int:
    """retrieves the tweet id from a tweet permalink from nitter (hence the #m)"""
    return int(RX_ID.search(permalink)[1])
def _create_link(screen_name: str, id_: int) -> str:
    """creates a tweet permalink from a screen name and a tweet id"""
    return f'https://vxtwitter.com/{screen_name}/status/{id_}'


def cron_twitter(context: CallbackContext) -> None:
    """this is the twitter cron job that looks for new tweets and posts them"""
    entries = {}

    for screen_name, chat_ids in _get_twitter_feeds():  # these are already deduplicated
        # feedparse allows you to specify the url directly, but it doesn't seem to ever
        # time out. also, get_url uses the same http session to perform all requests, so
        # we get better performance.
        for term in [screen_name, screen_name[1:]] if screen_name.startswith('@') else [screen_name]:
            feed_url = (f'https://{_config("twitter_nitter_instance")}/search/rss?f=tweets&q={term[1:]}' if term.startswith('@')
                        else f'https://{_config("twitter_nitter_instance")}/{term}/with_replies/rss')
            feed = feedparser.parse(get_url(feed_url))

            if feed['bozo'] == 1:
                # failed to parse the feed
                logger.info('Error retrieving %s: %s', term, repr(feed.get('bozo_exception', '???')))
            elif not feed.entries:
                logger.info('%s has no tweets', term)
            else:
                for entry in feed.entries:
                    entry.id = get_id_from_guid(entry.guid)
                    recipients = set(chat_ids)
                    if entry.id in entries:
                        entries[entry.id].recipients.union(recipients)
                    else:
                        entry.recipients = recipients
                        entries[entry.id] = entry

    if sorted_entries := dict(sorted(entries.items())):
        first_run = context.bot_data['seen_twitter_ids'] is None
        if first_run:
            context.bot_data['seen_twitter_ids'] = []

        for entry in sorted_entries.values():
            if entry.id in context.bot_data['seen_twitter_ids']:
                continue
            context.bot_data['seen_twitter_ids'].append(entry.id)
            if not first_run:
                url = _create_link(entry.author[1:], entry.id)
                for chat_id in entry.recipients:
                    logger.info('Posting %s -> %d', url, chat_id)
                    try:
                        context.bot.send_message(chat_id, url)
                    except:
                        logger.exception("Couldn't post")
    else:
        logger.info('Nothing to work with.')


def command_twitter(update: Update, context: CallbackContext) -> None:
    """shows latest saved tweets for each account we're watching"""
    if is_admin(update.message.from_user.id):
        if context.bot_data['seen_twitter_ids'] is not None and len(context.bot_data['seen_twitter_ids']) > 0:
            update.message.reply_text(f'Last tweet saved: {_create_link("someone", context.bot_data["seen_twitter_ids"][-1])}\n'
                                      f'{len(context.bot_data["seen_twitter_ids"])} entries saved.')
        else:
            update.message.reply_text('Nothing saved (yet).')
    else:
        update.message.reply_animation(_config('error_animation'))
