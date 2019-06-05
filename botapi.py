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


class TelegramBotAPI:
    """A set if function that communicate with official Telegram bot api"""
    token: str
    url: str

    def __init__(self, token: str):
        """
        Create instance of TelegramBotAPI

        Params:
        token - your's bot token. You can get it from @BotFather in Telegram
        """

        self.token = token
        self.url = 'https://api.telegram.org/bot' + token + '/'


