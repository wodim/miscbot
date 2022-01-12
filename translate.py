import json
import queue
import threading
import unicodedata

import emoji
import requests

from utils import _config, logger


class TranslatorException(Exception): pass
class UnrecoverableTranslatorException(Exception): pass


# https://eli.thegreenplace.net/2011/12/27/python-threads-communication-and-stopping
class TranslateWorkerThread(threading.Thread):
    def __init__(self, result_q, proxy, translation):
        super().__init__()
        self.result_q = result_q
        self.stop_request = threading.Event()
        self.text, self.languages = translation
        self.session = requests.Session()
        self.session.proxies.update(dict(http='http://' + proxy,
                                         https='http://' + proxy))
        self.session.headers.update({
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'Origin': 'https://translate.google.com',
            'Referer': 'https://translate.google.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
        })

    def run(self):
        source = self.languages.pop(0)
        text = self.text
        for language in self.languages:
            try:
                text = self.clean_up(text)
                if self.stop_request.isSet():
                    return
                text = self.translate(text, source, language)
                text = self.clean_up(text)
                if self.stop_request.isSet():
                    return
                self.result_q.put((threading.get_ident(), (text, language)))
                source = language
            except:
                # logger.info('Error translating "%s" from %s to %s', text, source, language)
                self.result_q.put((threading.get_ident(), (None, language)))

    def translate(self, text, lang_from, lang_to):
        url = ('https://translate.googleapis.com/translate_a/single?client=gtx&'
               'dt=t&ie=UTF-8&oe=UTF-8&otf=1&ssel=0&tsel=0&kc=7&dt=at&dt=bd&'
               'dt=ex&dt=ld&dt=md&dt=qca&dt=rw&dt=rm&dt=ss')
        params = {'q': text, 'sl': lang_from, 'tl': lang_to}

        response = None
        for _ in range(int(_config('translate_http_retries'))):
            try:
                response = self.session.get(url, params=params,
                                            timeout=int(_config('translate_http_timeout')))
            except:
                continue
        if response is None:
            raise TranslatorException('This proxy failed miserably')

        if response.status_code == 429:
            raise TranslatorException("I'm out of quota by now")
        if response.status_code == 400:
            raise UnrecoverableTranslatorException('You screwed up')

        translation = ' '.join([str(x[0]) for x in
                                json.loads(response.text)[0] if x[0]])

        if len(translation.strip()) == 0:
            raise TranslatorException('Empty translation received')

        return translation

    @staticmethod
    def clean_up(text):
        text = text.replace('\u200d', '').replace('\ufe0f', '')
        text = ''.join([' ' + TranslateWorkerThread.emoji_name(x) + ' '
                        if x in emoji.UNICODE_EMOJI['en'] else x
                        for x in text])
        text = TranslateWorkerThread.capitalize(text.strip())
        while '  ' in text:
            text = text.replace('  ', ' ')
        text = '\n'.join([x.strip() for x in text.split('\n')])
        return text

    @staticmethod
    def emoji_name(char):
        name = unicodedata.name(char)
        if name == 'EMOJI MODIFIER FITZPATRICK TYPE-1-2':
            return 'WHITE SKINNED'
        if name == 'EMOJI MODIFIER FITZPATRICK TYPE-3':
            return 'LIGHT BROWN SKINNED'
        if name == 'EMOJI MODIFIER FITZPATRICK TYPE-4':
            return 'MODERATE BROWN SKINNED'
        if name == 'EMOJI MODIFIER FITZPATRICK TYPE-5':
            return 'DARK BROWN SKINNED'
        if name == 'EMOJI MODIFIER FITZPATRICK TYPE-6':
            return 'BLACK SKINNED'
        if name.startswith('EMOJI COMPONENT '):
            return 'WITH ' + name.replace('EMOJI COMPONENT ', '')
        if 'VARIATION SELECTOR' in name:
            return ''
        for x in ('MARK', 'SIGN'):
            if name.endswith(' ' + x):
                return name.replace(' ' + x, '')
        return name

    @staticmethod
    def capitalize(text):
        upper = True
        output = ''
        for char in text.lower():
            if char.isalpha() and upper:
                output += char.upper()
                upper = False
            else:
                output += char
            if char.isdigit() and upper:
                upper = False
            elif char in set('\t\n.?!'):
                upper = True
        return output

    def join(self, timeout=None):
        self.stop_request.set()
        super().join(timeout)


def translate(text, languages):
    result_q = queue.Queue()

    with open('proxies.txt', 'rt', encoding='utf8') as fp:
        proxies = fp.read().strip().split('\n')
    pool = [TranslateWorkerThread(result_q, proxy, (text, languages.copy()))
            for proxy in proxies]

    for thread in pool:
        thread.start()

    results = {}
    while True:
        result = result_q.get()
        ident, args = result
        text_, _ = args

        if ident not in results:
            results[ident] = [(TranslateWorkerThread.clean_up(text), languages[0])]
        results[ident].append(args)

        if len(results[ident]) != len(languages):
            # this thread hasn't finished its job yet.
            continue

        # we have finished, so stop and remove this thread from the pool
        for thread in pool:
            if thread.ident == ident:
                thread.join(timeout=0)
                pool.remove(thread)
                break

        # check if all translations made by this thread succeeded
        if all((x for x, _ in results[ident])):
            # if that is the case, kill the rest of threads and return early.
            for thread in pool:
                thread.join(timeout=0)
            return text_, results[ident]

        if len(pool) == 0:
            # there are no more threads left, so pick the best translation
            # available. first we have to remove threads that failed to
            # translate back to the source language.
            valid = [x for x in results.values() if x[-1][0]]
            # if there are no valid translations, bail out.
            if not valid:
                logger.info('Gave up on this translation')
                raise TranslatorException("With this translator's failure, the thread of prophecy is severed. Issue the same command again to restore the weave of fate, or persist in the doomed, untranslated world you have created.")
            # then sort the results by the amount of translations done and
            # return the results of the thread that managed to perform a
            # greater amount of translations.
            best = sorted(valid, key=lambda ident: len([x for x, _ in ident if x]), reverse=True)
            return best[0][-1][0], best[0]
