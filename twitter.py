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
    for screen_name, chat_ids in _get_twitter_feeds():
        # feedparse allows you to specify the url directly, but it doesn't seem to ever
        # time out. also, get_url uses the same http session to perform all requests, so
        # we get better performance.
        feed = feedparser.parse(get_url(f'https://{_config("twitter_nitter_instance")}/{screen_name}/with_replies/rss'))

        if feed['bozo'] == 1:
            # failed to parse the feed
            logger.info('Error retrieving %s: %s', screen_name, repr(feed.get('bozo_exception', '???')))
        elif not feed.entries:
            logger.info('%s has no tweets', screen_name)
        else:
            last_id = context.bot_data['last_tweet_ids'].get(screen_name)

            # extract the tweet ids from all tweets and sort the tweets by id
            # they could be out of order because of retweets bringing up old ids
            for entry in feed.entries:
                entry.id = get_id_from_guid(entry.guid)
            feed.entries.sort(key=lambda entry: entry.id)

            # feed.entries[-1] won't crash here because we already checked for feed.entries earlier
            context.bot_data['last_tweet_ids'][screen_name] = get_id_from_guid(feed.entries[-1].guid)

            # we didn't have anything saved, so this feed was just added. don't post anything
            if not last_id:
                continue

            for entry in feed.entries:
                if entry.id > last_id and entry.author.lower() == f'@{screen_name}':
                    url = _create_link(screen_name, entry.id)
                    for chat_id in chat_ids:
                        logger.info('Posting %s -> %d', url, chat_id)
                        context.bot.send_message(chat_id, url)


def command_twitter(update: Update, context: CallbackContext) -> None:
    """shows latest saved tweets for each account we're watching"""
    if is_admin(update.message.from_user.id):
        if context.bot_data['last_tweet_ids']:
            update.message.reply_text('\n'.join([f'{screen_name}: {_create_link(screen_name, id_)}'
                                                for screen_name, id_
                                                in context.bot_data['last_tweet_ids'].items()]),
                                    disable_web_page_preview=True)
        else:
            update.message.reply_text('Nothing saved (yet).')
    else:
        update.message.reply_animation(_config('error_animation'))
