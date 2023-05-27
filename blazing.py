import threading
import time

from telegram import Bot

from craiyon import get_craiyon
from translate import get_scramble_languages, sub_translate
from utils import _config, logger


BLAZING_CRAIYON_SEMAPHORE = threading.Semaphore()
def blazing_craiyon(i) -> None:
    delay = 60 / int(_config('blazing_craiyon_threads')) * (int(_config('blazing_craiyon_threads')) - i - 1)
    logger.info('launching thread %d, which will wait %d seconds to begin', i, delay)
    time.sleep(delay)
    while True:
        logger.info('running thread %d', i)
        # it's a bit lame to write and read from a file constantly but we don't know when the bot may crash
        with BLAZING_CRAIYON_SEMAPHORE:
            try:
                with open('blazing_craiyon_prompt.txt', 'rt', encoding='utf8') as fp:
                    prompt = fp.read().strip()
            except Exception as exc:
                logger.info("can't launch blazing craiyon: %s", exc)
                return

        logger.info('blazing craiyon: scrambling "%s"', prompt)
        scramble_languages = get_scramble_languages(int(_config('blazing_scrambler_count'))) + ['en']
        prompt, _ = sub_translate(prompt, scramble_languages)
        prompt = prompt.strip('.,?! ')

        logger.info('blazing craiyon: requesting "%s"', prompt)
        gallery, next_prompt = get_craiyon(prompt)
        bot.send_photo(int(_config('blazing_craiyon_chat_id')), gallery, caption=prompt)

        if next_prompt and i == 0:
            # only worry aobut the next prompt if we are the control thread
            with BLAZING_CRAIYON_SEMAPHORE:
                logger.info('blazing craiyon: storing next prompt "%s"', next_prompt)
                with open('blazing_craiyon_prompt.txt', 'wt', encoding='utf8') as fp:
                    fp.write(next_prompt)


if __name__ == '__main__':
    bot = Bot(_config('token'))

    for i in range(int(_config('blazing_craiyon_threads'))):
        thread = threading.Thread(target=blazing_craiyon, args=(i,))
        thread.start()
