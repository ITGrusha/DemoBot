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

import json
import os
import time

from src import logger
from src.syslang import langapi
from src.bot2api import Bot2API, AutoDelete
from src.sysbugs.bugtrackerapi import report_custom_message

polls: dict = {}
config: dict = {}
chats: list = []
api: Bot2API

POLLS_FILENAME: str = 'pollsinfo.json'


def init_bot(debug: bool = False):
    global api, config
    logger.logger.info('Begging init of bot')

    logger.logger.debug('Loading config file (debug = ' + 'True)' if debug else 'False)')
    config = load_config(debug)
    logger.logger.debug('Crating instance of TelegramBotAPI in bot init')
    api = Bot2API(debug)
    logger.logger.debug('Adding report command listener')
    api.add_command_listener('report', report_command_processor)
    logger.logger.debug('Adding lang command listener')
    api.add_command_listener('lang', send_lang_inline)
    logger.logger.debug('Adding update listener that checks kick candidates and starts poll')
    api.add_message_listener(process_update_and_start_poll)
    logger.logger.debug('Adding update listener that updates options of all polls')
    api.add_message_listener(update_poll_options)
    logger.logger.debug('Adding update listener that save chats')
    api.add_message_listener(get_new_chat_from_update)


def load_chats():
    global chats

    path = os.path.join(os.path.dirname(__file__), '../', 'chats.json')
    chats = []

    if os.path.exists(path):
        with open(path, 'r') as f:
            chats = json.loads(f.read())


def save_new_chat(chat: int):
    global chats

    path = os.path.join(os.path.dirname(__file__), '../', 'chats.json')
    if chat not in chats:
        chats.append(chat)

        with open(path, 'w') as f:
            f.write(json.dumps(chats))


def get_new_chat_from_update(update: dict):
    for key, data in update.items():
        try:
            if type(data) == dict:
                save_new_chat(data['chat']['id'])
        except (KeyError, NameError, IndexError):
            pass


def load_config(debug: bool = False) -> dict:
    config_filename = 'config.json' if not debug else 'devconfig.json'
    logger.logger.debug('Using ' + config_filename + ' as config file')
    with open(config_filename, 'r') as f:
        return json.loads(f.read())


def process_update_and_start_poll(update: dict) -> None:
    try:
        logger.logger.trace('Checking new update! (is mention? ' + str(
            config['bot_username'] in update['message']['text']) + '; is reply? ' + str(
            'reply_to_message' in update['message'].keys()) + ')\n' + str(update))
        if config['bot_username'] in update['message']['text'] and 'reply_to_message' in update['message'].keys():
            chat_id = update['message']['reply_to_message']['chat']['id']
            name = update['message']['reply_to_message']['from']['first_name']
            if 'last_name' in update['message']['reply_to_message']['from'].keys():
                name += ' ' + update['message']['reply_to_message']['from']['last_name']
            user_id = update['message']['reply_to_message']['from']['id']

            logger.logger.info('Found kick candidate in chat #' + str(chat_id) + ', with name ' + name + '(' + str(user_id) + ')')

            start_poll(chat_id, name, user_id)
    except (NameError, IndexError, KeyError) as e:
        logger.logger.trace('Ignored name exception in checking poll candidates: ' + str(e))


def start_poll(chat_id: int, name: str, user_id: int) -> None:
    global polls, api

    response = api.start_poll(chat_id, langapi.msg_kick(chat_id).replace('%NAME%', name), [langapi.msg_kick_yes(chat_id), langapi.msg_kick_no(chat_id)])

    poll_id = int(response['poll']['id'])

    poll_info = dict()
    poll_info['chat_id'] = chat_id
    poll_info['date'] = response['date']
    poll_info['user_id'] = user_id
    poll_info['name'] = name
    poll_info['options'] = response['poll']['options']

    polls[poll_id] = poll_info


def load_polls_info():
    global polls

    path = os.path.join(os.path.dirname(__file__), '../', POLLS_FILENAME)

    if os.path.exists(path):
        with open(path, 'r') as f:
            dict_ = json.loads(f.read())
            polls = {}
            for key, value in dict_:
                polls[int(key)] = value


def save_polls():
    path = os.path.join(os.path.dirname(__file__), '../', POLLS_FILENAME)

    if os.path.exists(path):
        with open(path, 'w') as f:
            f.write(json.dumps(polls))


def update_poll_options(update: dict):
    global polls

    try:
        id_ = int(update['poll']['id'])
        if id_ in polls.keys():
            polls[id_]['options'] = update['poll']['options']
        save_polls()
    except (NameError, KeyError, IndexError):
        pass


def kick_candidate(poll_id: int):
    global polls

    logger.logger.info('Kicking ' + polls[poll_id]['name'] + '(' + str(polls[poll_id]['user_id']) + ') in chat #' + str(polls[poll_id]['chat_id']))

    api.send_message(polls[poll_id]['chat_id'],
                     langapi.msg_kick_res(polls[poll_id]['chat_id']).replace('%NAME%', polls[poll_id]['name']))
    logger.logger.debug('Kick message already sent')
    api.kick_chat_member(polls[poll_id]['chat_id'], polls[poll_id]['user_id'])


def check_old_polls():
    global polls
    remove = []

    for poll_id in polls.keys():
        logger.logger.trace('Checking poll with id ' + str(poll_id))
        poll_options = polls[poll_id]['options']
        if (time.time() - polls[poll_id]['date']) >= 12 * 3600 and poll_options[0]['voter_count'] > poll_options[1]['voter_count']:
            kick_candidate(poll_id)
            remove += [poll_id]
        elif (time.time() - polls[poll_id]['date']) >= 24 * 3600:
            logger.logger.info('Closing poll with id ' + str(poll_id) + ' after 24 hours')
            remove += [poll_id]

    for i in remove:
        del polls[i]


value_ = None


def respond_checking_processor(update: dict, chat_id: int, user_id: int):
    global value_

    try:
        msg = update['message']
        if msg['from']['id'] == user_id and msg['chat']['id'] == chat_id:
            value_ = msg['text']
            raise AutoDelete()
    except (NameError, KeyError, IndexError):
        pass


def wait_for_user_response(chat_id: int, user_id: int) -> str:
    api.add_message_listener(report_custom_message, chat_id, user_id)
    while value_ is None:
        pass
    return value_


def report_command_processor(chat_id: int, from_id: int):
    logger.logger.info('Starting processor for report command')
    api.send_message(chat_id, langapi.msg_descrb_problem(chat_id))

    bug_report_msg = wait_for_user_response(chat_id, from_id)

    logger.logger.debug('Asking for contact info')

    api.send_message(chat_id, langapi.msg_give_contact_info(chat_id))

    from_msg = wait_for_user_response(chat_id, from_id)

    logger.logger.debug('Sending bug report')

    report_custom_message(bug_report_msg, from_msg)
    api.send_message(chat_id, langapi.msg_bug_report_send(chat_id))

    logger.logger.info('Successfully sent bug report')


def change_lang_in_chat(chat_id: int, lang: str):
    langapi.set_lang_for_chat(chat_id, lang)
    api.send_message(chat_id, langapi.msg_lang_notify(chat_id))


def send_lang_inline(chat_id: int, from_id: int):
    logger.logger.info('Sending inline lang chooser in chat #' + str(chat_id))
    api.send_inline_message(chat_id, langapi.msg_lang_choose(chat_id), langapi.get_all_langs(), change_lang_in_chat)


def main_loop() -> None:
    global polls
    logger.logger.info('Started main loop')
    load_polls_info()
    load_chats()

    while True:
        check_old_polls()
