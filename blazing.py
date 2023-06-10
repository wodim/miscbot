import threading
import time
import sys

import telegram

from craiyon import get_craiyon
from translate import get_scramble_languages, sub_translate
from utils import _config, logger


BLAZING_CRAIYON_SEMAPHORE = threading.Semaphore()
def blazing_craiyon(i) -> None:
    delay = 60 / int(_config('blazing_craiyon_threads')) * (int(_config('blazing_craiyon_threads')) - i - 1)
    logger.info('launching thread %d, which will wait %d seconds to begin', i, delay)
    time.sleep(delay)
    while True:
        # it's a bit lame to write and read from a file constantly but we don't know when the bot may crash
        with BLAZING_CRAIYON_SEMAPHORE:
            try:
                with open('blazing_craiyon_prompt.txt', 'rt', encoding='utf8') as fp:
                    prompt = fp.read().strip()
            except Exception as exc:
                logger.info("can't launch blazing craiyon: %s", exc)
                sys.exit(1)

        logger.info('blazing craiyon: scrambling "%s"', prompt)
        scramble_languages = get_scramble_languages(int(_config('blazing_craiyon_scrambler_count'))) + ['en']
        try:
            prompt, _ = sub_translate(prompt, scramble_languages)
            prompt = prompt.strip('.,?! ')
        except Exception as exc:
            logger.exception("couldn't scramble, so keeping the prompt as it is")

        logger.info('requesting "%s"', prompt)
        try:
            gallery, next_prompt = get_craiyon(prompt)
        except Exception as exc:
            logger.exception("couldn't request images or generate a gallery with them, trying something else")
            continue

        while True:
            try:
                bot.send_photo(int(_config('blazing_craiyon_chat_id')), gallery, caption=prompt)
                break
            except telegram.error.RetryAfter as exc:
                logger.info(str(exc))
                time.sleep(exc.retry_after + 1)
            except Exception as exc:
                logger.exception("couldn't post, continuing anyway")
                break

        # only save the next prompt if we are the control thread
        if next_prompt and i == 0:
            # ignore suggestions that are in the blacklist
            blacklist = _config('blazing_craiyon_next_prompt_blacklist').split(' ')
            words = next_prompt.lower().split(' ')
            if [x for x in blacklist if x in words]:
                continue

            with BLAZING_CRAIYON_SEMAPHORE:
                logger.info('storing next prompt "%s"', next_prompt)
                try:
                    with open('blazing_craiyon_prompt.txt', 'wt', encoding='utf8') as fp:
                        fp.write(next_prompt)
                except Exception as exc:
                    logger.exception("couldn't save current prompt")


if __name__ == '__main__':
    bot = telegram.Bot(_config('token'))

    for i in range(int(_config('blazing_craiyon_threads'))):
        thread = threading.Thread(target=blazing_craiyon, args=(i,))
        thread.start()
