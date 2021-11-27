import html
import json
import queue
import random
import string
import threading
import time
import unicodedata

import emoji
import requests


# https://eli.thegreenplace.net/2011/12/27/python-threads-communication-and-stopping
class WorkerThread(threading.Thread):
    def __init__(self, result_q, proxy, translation):
        super().__init__()
        self.result_q = result_q
        self.stop_request = threading.Event()
        self.text, self.languages = translation
        self.s = requests.Session()
        self.s.proxies.update(dict(http='http://' + proxy,
                                   https='http://' + proxy))

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
            except Exception:
                self.result_q.put((threading.get_ident(), (None, language)))

    def translate(self, text, lang_from, lang_to):
        url = 'https://mymemory.translated.net/api/ajaxfetch'
        params = {'q': text, 'langpair': lang_from + '|' + lang_to, 'mtonly': '1'}

        response = None
        for _ in range(5):
            params['de'] = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
            try:
                response = self.s.get(url, params=params, timeout=3)
            except:
                continue
            try:
                decoded_json = json.loads(response.text)
                translation = decoded_json['responseData']['translatedText']
                break
            except:
                if response.status == 414:
                    # uri too long: we won't recover from this by retrying
                    break
                time.sleep(2)
        if response is None:
            raise TranslatorException('Failed to decode the JSON')

        if decoded_json['responseStatus'] != 200:
            if 'IS AN INVALID TARGET LANGUAGE' in translation:
                raise TranslatorException('Incorrect language (%s)' %
                                          decoded_json['responseStatus'])
            if decoded_json['responseStatus'] == 429:
                raise TranslatorException("I'm out of quota by now")
            raise TranslatorException('Response code not ok (%s)' %
                                      decoded_json['responseStatus'])

        if len(translation.strip()) == 0:
            raise TranslatorException('Unsupported language')

        return translation

    @staticmethod
    def clean_up(text):
        text = html.unescape(text)
        text = '\n'.join([x.strip() for x in text.split('\n')])
        text = text.replace('@ ', '@')
        if text.endswith(';'):
            text = text[:-1] + '?'
        text = ''.join([unicodedata.name(x) + ' ' if x in emoji.UNICODE_EMOJI['en'] else x
                        for x in text])
        text = WorkerThread.capitalize(text.strip())
        return text

    @staticmethod
    def capitalize(text):
        upper = True
        output = ''
        for x in text.lower():
            if x.isalpha() and upper:
                output += x.upper()
                upper = False
            else:
                output += x
            if x.isdigit() and upper:
                upper = False
            elif x in set('\t\n.?!'):
                upper = True
        return output

    def join(self, timeout=None):
        self.stop_request.set()
        super().join(timeout)


class TranslatorException(Exception):
    pass


def translate(text, languages, callback=None, callback_args=None):
    result_q = queue.Queue()

    with open('proxies.txt', 'rt', encoding='utf8') as fp:
        proxies = fp.read().strip().split('\n')
    pool = [WorkerThread(result_q, proxy, (text, languages.copy()))
            for proxy in proxies]

    for thread in pool:
        thread.start()

    results = {}
    while True:
        result = result_q.get()
        ident, args = result
        text_, _ = args

        if callback and callback_args:
            # send back a typing notification
            callback(callback_args, 'typing')

        if ident not in results:
            results[ident] = [(WorkerThread.clean_up(text), languages[0])]
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
                raise TranslatorException('All threads died and not one of them could come up with an answer. Try again.')
            # then sort the results by the amount of translations done and
            # return the results of the thread that managed to perform a
            # greater amount of translations.
            best = sorted(valid, key=lambda ident: len([x for x, _ in ident if x]), reverse=True)
            return best[0][-1][0], best[0]
