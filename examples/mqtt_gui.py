#!/usr/bin/env python3
import sys
import json
import uuid
import base64
import random

from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *

from cryptography.fernet import Fernet

import paho.mqtt.client as mqtt

sys.path.append("..")
from mahitahi import Doc


class Main(QMainWindow):

    HOST = "mqtt.eclipse.org"

    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)

        self.patch_stack = []
        self.author = False
        self.known_authors = []
        self.patch_set = []  # Contains patch set pulled from Editor widget's Doc object

        resp, ok = QInputDialog.getText(
            self, "Portal Setup", "Paste the Portal ID you received or enter nothing to create your own:"
        )

        if not ok:
            sys.exit()

        if not resp:
            self.portal_id, self.pad_name, self.fernet_key = self.generate_portal_tuple()
            self.author = True
            print(f"Share this Portal ID with someone:\n\n  {self.portal_id}\n\n")
        else:
            self.pad_name, self.fernet_key = self.parse_portal_id(resp)

        self.fernet = Fernet(self.fernet_key)

        self.site = 0
        if not self.author:
            self.site = int(random.getrandbits(32))

        self.known_authors.append(self.site)

        self.mqtt_name = f"mahitahi/pad/{self.pad_name}"
        self.subs = {
            self.mqtt_name + "/aloha": self.on_topic_aloha,
            self.mqtt_name + "/patch": self.on_topic_patch,
            self.mqtt_name + "/authors/enter": self.on_topic_authors,
            self.mqtt_name + "/authors/set": self.on_topic_authors,
            self.mqtt_name + "/authors/leave": self.on_topic_authors
        }

        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.HOST, 1883, 60)

        self.update_title()

        self.setGeometry(400, 400, 800, 600)

        self.editor = Editor(self.site)
        self.highlighter = AuthorHighlighter(self.editor)
        self.setCentralWidget(self.editor)

        self.editor.change_evt.connect(self.on_change)
        self.editor.res_state_evt.connect(self.on_resp_state)

        self.client.loop_start()

    def update_title(self):
        self.window_title = f"MahiTahi Demo | Pad: {self.pad_name} | Site: {self.site} | Author: {self.author}"
        self.setWindowTitle(self.window_title)

    def on_connect(self, client, userdata, flags, rc):
        for topic in self.subs.keys():
            self.client.subscribe(topic, qos=2)

        self.client.publish(self.mqtt_name + "/authors/enter", str(self.site))

        if not self.author:
            self.client.publish(self.mqtt_name + "/aloha", str(self.site))

    def generate_portal_tuple(self, include_server=False):
        pad = uuid.uuid4().hex
        key = Fernet.generate_key().decode()

        temp_str = ""
        if include_server:
            temp_str += f"{self.HOST}:"

        temp_str += f"{pad}:{key}"

        return base64.b64encode(temp_str.encode()).decode(), pad, key.encode()

    def parse_portal_id(self, portal_id):
        tup = base64.b64decode(portal_id.encode()).decode().split(":")

        if len(tup) == 2:
            pad, key = tup
            return pad, key.encode()
        elif len(tup) == 3:
            server, pad, key = tup
            return server, pad, key.encode()

    @pyqtSlot(str)
    def on_change(self, patch):
        print(f"Sending patch: {patch}")
        payload = self.fernet.encrypt(patch.encode())
        self.patch_stack.append(payload)
        self.client.publish(self.mqtt_name + "/patch", payload, qos=2)

    def on_message(self, client, userdata, msg):
        self.subs[msg.topic](msg.topic, msg.payload)

    def on_topic_aloha(self, topic, payload):
        if self.author:

            set_dict = {
                "dst": int(payload),
                "authors": self.known_authors
            }

            print("Main author procedure: Sending known authors...")
            self.client.publish(self.mqtt_name + "/authors/set", json.dumps(set_dict))

            print("Main author procedure: Sending known patches...")

            for patch in self.patch_set:
                payload = self.fernet.encrypt(patch.encode())
                self.client.publish(self.mqtt_name + "/patch", payload, qos=2)

            print("Main author procedure: Done")

    def on_topic_patch(self, topic, payload):
        if payload not in self.patch_stack:
            payload_decrypted = self.fernet.decrypt(payload)
            patch = json.loads(payload_decrypted)
            if patch["src"] != self.site:
                print(f"Received patch: {payload_decrypted.decode()}")
                self.patch_stack.append(payload)
                self.editor.upd_text.emit(payload_decrypted.decode())

    def on_topic_authors(self, topic, payload):
        if topic.endswith("enter"):
            site = int(payload)
            if site != self.site:
                print(f"New client joined: {site}")
                self.known_authors.append(site)
        elif topic.endswith("set"):
            set_dict = json.loads(payload)
            if set_dict["dst"] == self.site:
                self.known_authors = set_dict["authors"]
                print(f"Received known authors from current author: {self.known_authors}")
        elif topic.endswith("leave"):
            site = int(payload)
            print(f"Client left: {site}")
            self.known_authors.remove(site)
            new_author = min(self.known_authors)
            print(f"New author should be: {new_author}")
            if self.site == new_author:
                print("Declared us as new author!")
                self.author = True
                self.update_title()

    @pyqtSlot(str)
    def on_resp_state(self, patch_set):
        self.patch_set = json.loads(patch_set)

    def closeEvent(self, event):
        self.client.publish(self.mqtt_name + "/authors/leave", self.site)
        event.accept()


class Editor(QTextEdit):
    upd_text = pyqtSignal(str)  # in
    change_evt = pyqtSignal(str)  # out
    res_state_evt = pyqtSignal(str)  # out

    def __init__(self, site):
        self.view = QPlainTextEdit.__init__(self)
        self.setFrameStyle(QFrame.NoFrame)

        self.font = QFont()
        self.font.setStyleHint(QFont.Monospace)
        self.font.setFixedPitch(True)
        self.font.setPointSize(16)
        self.setFont(self.font)

        self.doc = Doc()
        self.doc.site = site

        self.upd_text.connect(self.on_upd_text)

        shortcut_f3 = QShortcut(QKeySequence("F3"), self)
        shortcut_f3.activated.connect(self.debug_crdt)

        shortcut_f4 = QShortcut(QKeySequence("F4"), self)
        shortcut_f4.activated.connect(self.debug_widget)

        shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        shortcut_f5.activated.connect(self.reload_from_crdt)

    def keyPressEvent(self, e):
        cursor = self.textCursor()

        if e.matches(QKeySequence.Paste) and QApplication.clipboard().text():
            pos = cursor.position()
            for i, c in enumerate(QApplication.clipboard().text()):
                patch = self.doc.insert(pos + i, c)
                self.change_evt.emit(patch)

        elif e.key() == Qt.Key_Backspace:
            if not self.toPlainText():
                return

            sel_start = cursor.selectionStart()
            sel_end = cursor.selectionEnd()
            if sel_start == sel_end:
                patch = self.doc.delete(cursor.position() - 1)
                self.change_evt.emit(patch)
            else:
                for pos in range(sel_end, sel_start, -1):
                    patch = self.doc.delete(pos - 1)
                    self.change_evt.emit(patch)

        elif e.key() != Qt.Key_Backspace and e.text() and e.modifiers() != Qt.ControlModifier:
            sel_start = cursor.selectionStart()
            sel_end = cursor.selectionEnd()
            if sel_start != sel_end:
                for pos in range(sel_end, sel_start, -1):
                    patch = self.doc.delete(pos - 1)
                    self.change_evt.emit(patch)

            patch = self.doc.insert(sel_start, e.text())
            self.change_evt.emit(patch)

        self.res_state_evt.emit(json.dumps(self.doc.patch_set))

        QTextEdit.keyPressEvent(self, e)

    @pyqtSlot(str)
    def on_upd_text(self, patch):
        self.doc.apply_patch(patch)

        cursor = self.textCursor()
        old_pos = cursor.position()
        self.setPlainText(self.doc.text)
        cursor.setPosition(old_pos)
        self.setTextCursor(cursor)

    def debug_crdt(self):
        self.doc.debug()

    def debug_widget(self):
        print(self.toPlainText().encode())

    def reload_from_crdt(self):
        self.setPlainText(self.doc.text)


class AuthorHighlighter(QSyntaxHighlighter):

    COLORS = (
        (251, 222, 187),
        (187, 251, 222),
        (222, 251, 187),
        (222, 187, 251),
        (187, 222, 251)
    )

    NUM_COLORS = len(COLORS)

    def __init__(self, parent):
        QSyntaxHighlighter.__init__(self, parent)
        self.parent = parent

    def highlightBlock(self, text):
        curr_line = self.previousBlockState() + 1

        doc_line = 0
        block_pos = 0

        text_format = QTextCharFormat()

        for c, a in zip(self.parent.doc.text, self.parent.doc.authors[1:-1]):
            if c in ("\n", "\r"):
                doc_line += 1
                continue
            else:
                if doc_line == curr_line:
                    text_format.setBackground(QBrush(self.get_author_color(a), Qt.SolidPattern))

                    self.setFormat(block_pos, 1, text_format)

                    block_pos += 1
                elif doc_line > curr_line:
                    break

        self.setCurrentBlockState(self.previousBlockState() + 1)

    def get_author_color(self, author_site):
        return QColor(*self.COLORS[author_site % self.NUM_COLORS])


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    main = Main()
    main.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
