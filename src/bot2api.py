#    This file is part of DemocraticBot.
#    https://github.com/Nekit10/DemoBot
#
#    DemocraticBot is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    DemocraticBot is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with DemocraticBot.  If not, see <https://www.gnu.org/licenses/>.
#
#    Copyright (c) 2019 Nikita Serba
import inspect
import os
import json
import ctypes
import random
import typing
import re
import threading
from _queue import Empty
from threading import Thread
from multiprocessing import Queue, Manager

import requests

import src.logger


class AutoDelete(Exception):
    pass


class Bot2API:
    """
    This class works with Telegram Bot API using HTTP-requests ans `requests` python library
    This class is multithreading-safe
    """

    _config: dict
    _token: str
    _url: str

    _message_listeners: list = []
    _command_listeners: dict = {}
    _inline_listeners: dict = {}

    _updater_loop: Thread
    _updater_command_queue: Queue
    _updater_result_dict: typing.Dict

    def __init__(self, debug_mode: bool):
        config_filename = 'config.json' if not debug_mode else 'devconfig.json'
        self._load_config(config_filename)

        self._token = self._config['token']
        self._url = 'https://api.telegram.org/bot' + self._token

        self._updater_command_queue = Queue()
        self._updater_result_dict = Manager().dict()
        self._updater_loop = self._UpdaterLoopThread(self._updater_command_queue, self._updater_result_dict, self)
        self._updater_loop.setDaemon(True)
        self._updater_loop.start()

    def add_message_listener(self, listener, *args, **kwargs) -> None:
        """
        This methods adds `listener` as listener for new updates.
        UpdaterLoopThread will call listener(update: dict, *args, **kwargs) for every new update
        """

        if not callable(listener):
            raise TypeError('Message listener must be callable')

        self._message_listeners += [[listener, args, kwargs]]

    def add_command_listener(self, command: str, listener, timeout_seconds: int = 300) -> None:
        """
        This methods adds `listener` as listener for running /`command`@BotName.
        UpdaterLoopThread will call listener(chat_id: int, from_id: int) for every new command.
        Listener will be killed after timeout_seconds
        """

        if not callable(listener):
            raise TypeError('Command listener must be callable')

        if timeout_seconds > 600:
            raise OverflowError('Timeout must be smaller than 10 minutes')

        self._command_listeners[command] = listener
        self.add_message_listener(self._command_listener_def, command, timeout_seconds)

    def add_inline_listener(self, msg_id: int, chat_id: int, listener, timeout_seconds: int = 1) -> None:
        """
        This methods adds `listener` as listener for inline callback.
        UpdaterLoopThread will call listener(chat_id: int, data: str) for every new command.
        Listener will be killed after timeout_seconds
        """

        if not callable(listener):
            raise TypeError('Command listener must be callable')

        if timeout_seconds > 60:
            raise OverflowError('Timeout must be smaller than 1 minute')

        self._inline_listeners[chat_id][msg_id] = listener
        self.add_message_listener(self._inline_listener_def, msg_id, chat_id, timeout_seconds)

    def start_poll(self, chat_id: int, question: str, answers: list) -> dict:
        return self._response_prepare(self._request_prepare('sendPoll', {
            'chat_id': chat_id,
            'question': question,
            'options': answers
        }))

    def send_message(self, chat_id: int, message: str) -> dict:
        return self._response_prepare(self._request_prepare('sendMessage', {'chat_id': chat_id, 'text': message}))

    def send_inline_message(self, chat_id: int, message: str, options: list, listener, timeout_seconds: int = 1):
        inline_keyboard_items = []

        for option in options:
            inline_keyboard_items += [{
                'text': option[0],
                'callback_data': option[1]
            }]

        resp = self._response_prepare(self._request_prepare('sendMessage', {
            'chat_id': chat_id,
            'text': message,
            'reply_markup': {
                'inline_keyboard': [inline_keyboard_items]
            }
        }))

        self.add_inline_listener(resp['message_id'], resp['chat']['id'], listener, timeout_seconds)

        return resp

    def kick_chat_member(self, chat_id: int, user_id: int, until_date: int = 0) -> dict:
        return self._response_prepare(self._request_prepare('kickChatMember', {
            'chat_id': chat_id,
            'user_id': user_id,
            'until_date': until_date
        }))

    def _load_config(self, filename: str) -> None:
        path = os.path.join(os.path.dirname(__file__), os.path.join('../', filename))

        with open(path, 'r') as f:
            self._config = json.loads(f.read())

    def _request_prepare(self, command_name: str, args: dict) -> requests.Response:
        url_ = self._url + '/' + command_name

        if args:
            url_ += '?'

            for arg_name, value in args.items():
                val_ = str(value) if type(value) != dict and type(value) != list else json.dumps(value)
                url_ += '{}={}&'.format(arg_name, val_)

            url_ = url_[:-1]

        return self._run_request(url_)

    def _command_listener_def(self, update: dict, command: str, timeout_seconds: int = 300) -> None:
        try:
            text = update['message']['text']
            if text.startswith('/' + command) and re.search(r'[^a-zA-Z]', text[1:]) and self._config['bot_username'] in text:
                thread = self._MethodRunningThread(self._command_listeners[command], update['chat']['id'], update['from']['id'])
                thread.setDaemon(True)
                thread.start()
                thread.join(timeout_seconds)
                thread.exit()
        except (NameError, KeyError, IndexError):
            pass

    def _inline_listener_def(self, update: dict,  msg_id: int, chat_id: int, timeout_seconds: int = 300) -> None:
        try:
            query = update['callback_query']
            thread = self._MethodRunningThread(self._inline_listeners[chat_id][msg_id], chat_id, query['data'])
            thread.setDaemon(True)
            thread.start()
            thread.join(timeout_seconds)
            thread.exit()
        except (NameError, KeyError, IndexError):
            pass

    @staticmethod
    def _response_prepare(response: requests.Response) -> dict:
        resp_obj = response.json()

        if response.status_code != 200 or not resp_obj['ok']:
            raise ConnectionError('Error while working with Telegram Bot API (status code = ' + str(response.status_code) + '). ' + resp_obj['description'])

        return resp_obj['result']

    def _run_request(self, url: str) -> requests.Response:
        req_id_ = random.randint(0, 2 ** 16)
        while req_id_ in self._updater_result_dict.keys():
            req_id_ = random.randint(0, 2 ** 16)

        self._updater_command_queue.put([req_id_, url])

        while req_id_ not in self._updater_result_dict.keys():
            pass

        result_ = self._updater_result_dict[req_id_]
        del self._updater_result_dict[req_id_]

        return result_

    class _UpdaterLoopThread(Thread):
        _offset: int = 0

        def __init__(self, cmd_queue: Queue, result_dict: typing.Dict, api: object):
            Thread.__init__(self)
            self.cmd_queue = cmd_queue
            self.result_dict = result_dict
            self.api = api

        def run(self) -> None:
            while True:
                try:
                    id_, url = self.cmd_queue.get(timeout=0.1)
                    self.result_dict[id_] = requests.get(url)
                except Empty:
                    upd_resp = Bot2API._response_prepare(requests.get(self.api._url + '/getUpdates?offset=' + str(self._offset)))
                    if upd_resp:
                        self._offset = upd_resp[-1]['update_id'] + 1

                    for update in upd_resp:
                        del_ = []
                        for i in range(len(self.api._message_listeners)):
                            listener, args, kwargs = self.api._message_listeners[i]
                            try:
                                listener(update, *args, **kwargs)
                            except AutoDelete:
                                del_.append(i)
                            finally:
                                pass
                        for i in del_:
                            del self.api._message_listeners[i]

    class _MethodRunningThread(Thread):
        def __init__(self, method, *args, **kwargs):
            if not callable(method):
                raise TypeError('Method must be callable')

            self.method = method
            self.args = args
            self.kwargs = kwargs

        def run(self) -> None:
            try:
                self.method(*self.args, **self.kwargs)
            finally:
                pass  # end function here bro

        @staticmethod
        def _async_raise(tid: int, exctype):
            if not inspect.isclass(exctype):
                raise TypeError("Only types can be raised (not instances)")

            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), ctypes.py_object(exctype))

            if res == 0:
                raise ValueError('Invalid thread id')
            elif res != 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
                raise SystemError('PyThreadState_SetAsyncExc failed')

        def get_id(self):
            if not self.isAlive():
                raise threading.ThreadError('Thread is not active')

            if hasattr(self, "_thread_id"):
                return self._thread_id
            for tid, tobj in threading._active.items():
                if tobj is self:
                    self._thread_id = tid
                    return tid

            raise SystemError('Thread does not have id (???)')

        def exit(self):
            self._async_raise(self.get_id(), InterruptedError)
