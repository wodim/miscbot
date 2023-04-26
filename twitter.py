from telegram import Update
from telegram.ext import CallbackContext
from tweepy import API, OAuthHandler

from utils import _config, is_admin, logger


# TODO this should be a dict "username -> [channels]" to deduplicate feeds
def _get_twitter_feeds() -> dict:
    if feeds := _config('twitter_feeds'):
        return [(x, int(y)) for x, y in [x.strip().split('|') for x in feeds.split(',')]]
    return []


def _create_link(username: str, id_: int) -> str:
    return f'https://vxtwitter.com/{username}/status/{id_}'


auth = OAuthHandler(_config('twitter_consumer_key'), _config('twitter_consumer_secret'))
auth.set_access_token(_config('twitter_access_token'), _config('twitter_access_token_secret'))
api = API(auth)


def cron_twitter(context: CallbackContext) -> None:
    for username, chat_id in _get_twitter_feeds():
        try:
            last_tweets = api.user_timeline(screen_name=username)
        except Exception as exc:
            logger.info('Error retrieving tweets from "%s": %s', username, exc)
            continue
        if not last_tweets:
            continue

        last_id = context.bot_data['last_tweet_ids'].get(username)
        # last_tweets[0] won't crash here because we already checked for last_tweets earlier
        context.bot_data['last_tweet_ids'][username] = last_tweets[0].id

        if last_id:  # will be False the first time this is run so we don't post anything
            for tweet in last_tweets[::-1]:
                if tweet.id > last_id and (
                    # don't show self-retweets
                    not hasattr(tweet, 'retweeted_status') or
                    tweet.retweeted_status.user.screen_name != tweet.user.screen_name
                ):
                    url = _create_link(username, tweet.id)
                    logger.info('Posting %s', url)
                    context.bot.send_message(chat_id, url)


def command_twitter(update: Update, context: CallbackContext) -> None:
    """shows latest saved tweets for each account we're watching"""
    if is_admin(update.message.from_user.id):
        if context.bot_data['last_tweet_ids']:
            update.message.reply_text('\n'.join([f'{username}: {_create_link(username, id_)}'
                                                for username, id_
                                                in context.bot_data['last_tweet_ids'].items()]),
                                    disable_web_page_preview=True)
        else:
            update.message.reply_text('Nothing saved (yet).')
    else:
        update.message.reply_animation(_config('error_animation'))
