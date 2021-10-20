from datetime import datetime, timedelta


class MessageHistory:
    HISTORY_MINUTES = 10
    HISTORY_COUNT = 3

    def __init__(self):
        self.history = {}
        self.pending_removals = []

    def push(self, message):
        if message.chat_id not in self.history:
            self.history[message.chat_id] = []
        self.history[message.chat_id].append(message)
        self.gc(message.chat_id)

    def add_relayed_message(self, message, relayed_message):
        try:
            self.history[message.chat_id][self.history[message.chat_id].index(message)].relayed_message = relayed_message
        except ValueError:
            pass
        self.gc(message.chat_id)

    def gc(self, chat_id):
        if len(self.history[chat_id]) > self.HISTORY_COUNT:
            self.history[chat_id] = self.history[chat_id][-self.HISTORY_COUNT:]
        for message in self.history[chat_id]:
            if datetime.utcnow() - timedelta(minutes=self.HISTORY_MINUTES) > message.date.replace(tzinfo=None):
                self.history[chat_id].remove(message)

        for pending_removal in self.pending_removals:
            if datetime.utcnow() - timedelta(minutes=self.HISTORY_MINUTES) > pending_removal.date.replace(tzinfo=None):
                self.pending_removals.remove(message)

    def get_latest(self, chat_id):
        try:
            self.gc(chat_id)
            return self.history[chat_id]
        except KeyError:
            return {}

    def remove(self, message):
        try:
            self.history[message.chat_id].remove(message)
        except:
            pass

    def add_pending_removal(self, message):
        self.pending_removals.append(message)

    def can_post(self, message):
        """checks that there are no removals pending for this upcoming message"""
        if message in self.pending_removals:
            self.pending_removals.remove(message)
            return False
        return True
