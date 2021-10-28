import html
import json
import queue
import random
import string
import threading
import time

import requests


# https://eli.thegreenplace.net/2011/12/27/python-threads-communication-and-stopping
class WorkerThread(threading.Thread):
    def __init__(self, result_q, proxy, translation):
        super().__init__()
        self.result_q = result_q
        self.stop_request = threading.Event()
        self.translation = translation
        self.s = requests.Session()
        self.s.proxies.update(dict(http='http://' + proxy,
                                   https='http://' + proxy))

    def run(self):
        try:
            text, languages = self.translation
            source = languages.pop(0)
            for language in languages:
                text = self.clean_up(text)
                text = self.translate(text, source, language)
                text = self.clean_up(text)
                if self.stop_request.isSet():
                    return
                self.result_q.put((threading.get_ident(), 'partial_result', None))
                source = language
            self.result_q.put((threading.get_ident(), 'result', text))
        except Exception:
            self.result_q.put((threading.get_ident(), 'failed', None))

    def translate(self, text, lang_from, lang_to):
        url = 'https://mymemory.translated.net/api/ajaxfetch'
        params = {'q': text, 'langpair': lang_from + '|' + lang_to, 'mtonly': '1'}

        response = None
        for _ in range(5):
            params['de'] = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
            try:
                response = self.s.get(url, params=params, timeout=5)
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
                print('JSON error, waiting 2 secs:', response.text)
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
            if not x.isalpha() and not x.isnumeric() and x not in set(' \t,":;'):
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

    while True:
        result = result_q.get()
        ident, status, args = result
        if status == 'partial_result':
            # we got a partial result, so kill every other thread.
            """for thread in pool:
                if thread.ident != ident:
                    thread.join(timeout=0)
                    pool.remove(thread)"""
            if callback and callback_args:
                callback(callback_args, 'typing')
        elif status == 'result':
            # kill everything and return
            for thread in pool:
                thread.join(timeout=0)
            return args
        elif status == 'failed':
            # this thread has reported failure, so kill it.
            for thread in pool:
                if thread.ident == ident:
                    thread.join(timeout=0)
                    pool.remove(thread)
            if len(pool) == 0:
                raise TranslatorException('All threads died and not one of them could come up with an answer. Try again.')
