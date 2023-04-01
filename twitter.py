import re

import feedparser
from telegram.ext import CallbackContext

from utils import _config, logger


RX_ID = re.compile(r'(\d+)#m$')


# TODO this should be a dict "username -> [channels]" to deduplicate feeds
def get_twitter_feeds() -> dict:
    if feeds := _config('twitter_feeds'):
        return [(x, int(y)) for x, y in [x.strip().split('|') for x in feeds.split(',')]]
    return []


get_id_from_guid = lambda x: int(RX_ID.search(x)[1])


def cron_twitter(context: CallbackContext) -> None:
    for username, chat_id in get_twitter_feeds():
        feed = feedparser.parse(f'https://{_config("twitter_nitter_instance")}/{username}/with_replies/rss')

        if feed['status'] != 200 or not feed.entries:
            logger.info('%s does not exist', username)
            continue

        last_id = context.bot_data['last_tweet_ids'].get(username)

        # feed.entries[0] won't crash here because we already checked for feed.entries earlier
        context.bot_data['last_tweet_ids'][username] = get_id_from_guid(feed.entries[0].guid)

        if last_id:
            for entry in feed.entries[::-1]:
                id_ = get_id_from_guid(entry.guid)
                if id_ > last_id:
                    url = f'https://fxtwitter.com/{username}/status/{id_}'
                    logger.info('Posting %s', url)
                    context.bot.send_message(chat_id, url)
