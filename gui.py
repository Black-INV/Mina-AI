from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QListView
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QTextDocument
from PySide6.QtCore import Qt, QTimer, QAbstractListModel, QModelIndex, QSize, QRect, Signal
from PySide6.QtWidgets import QStyledItemDelegate, QTextEdit

MAX_MESSAGES = 2000


# ---------- Model ----------

class ChatModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.messages = []  # [text, is_user, is_typing, anim]

        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.animate)

    def rowCount(self, parent=None):
        return len(self.messages)

    def data(self, index, role):
        if role == Qt.DisplayRole:
            return self.messages[index.row()]

    def add_message(self, text, is_user=False, is_typing=False):
        self.beginInsertRows(QModelIndex(), len(self.messages), len(self.messages))
        self.messages.append([text, is_user, is_typing, 0.0])  # anim starts at 0
        self.endInsertRows()

        if len(self.messages) > MAX_MESSAGES:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self.messages.pop(0)
            self.endRemoveRows()

        self.anim_timer.start(16)  # ~60fps

    def remove_last(self):
        if not self.messages:
            return
        self.beginRemoveRows(QModelIndex(), len(self.messages)-1, len(self.messages)-1)
        self.messages.pop()
        self.endRemoveRows()

    def animate(self):
        running = False

        for row, msg in enumerate(self.messages):
            if msg[3] < 1.0:
                # smooth easing
                msg[3] += 0.08
                if msg[3] > 1.0:
                    msg[3] = 1.0

                idx = self.index(row)
                self.dataChanged.emit(idx, idx)
                running = True

        if not running:
            self.anim_timer.stop()
            
# ---------- Delegate (fast painting) ----------

class BubbleDelegate(QStyledItemDelegate):
    PADDING_X = 20
    PADDING_Y = 16
    MAX_WIDTH_RATIO = 0.7
    SHADOW_OFFSET = 3
    SHADOW_ALPHA = 80
    AVATAR_SIZE = 70
    AVATAR_MARGIN = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.avatar = QPixmap("avatar.png")

    def _doc(self, text, font, width=None):
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        if width is not None:
            doc.setTextWidth(width)
        doc.setPlainText(text)
        return doc

    def _measure(self, text, option):
        view_width = option.widget.width()
        max_width = int(view_width * self.MAX_WIDTH_RATIO)

        doc = self._doc(text, option.font)
        natural_width = doc.idealWidth()

        # guard against negative width
        final_width = max(40, min(natural_width, max_width - self.PADDING_X))

        doc = self._doc(text, option.font, final_width)

        text_height = doc.size().height()

        bubble_w = final_width + self.PADDING_X
        bubble_h = text_height + self.PADDING_Y

        return doc, bubble_w, bubble_h, text_height

    def paint(self, painter, option, index):
        text, is_user, is_typing, anim = index.data()
        painter.save()

        if is_typing:
            painter.setPen(QColor("#f5d6b4"))
            margin = 12
            text_rect = option.rect.adjusted(margin, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.restore()
            return

        doc, bubble_w, bubble_h, text_h = self._measure(text, option)

        row_rect = option.rect
        content_h = max(bubble_h, self.AVATAR_SIZE)

        y = row_rect.top() + (row_rect.height() - content_h) / 2

        if is_user:
            x = row_rect.right() - bubble_w - 10
        else:
            x = row_rect.left() + 10 + self.AVATAR_SIZE + self.AVATAR_MARGIN

        bubble_rect = QRect(int(x), int(y), int(bubble_w), int(bubble_h))

        # animation easing
        anim = anim * anim * (3 - 2 * anim)
        painter.setOpacity(anim)
        slide = int((1.0 - anim) * 12)
        bubble_rect.translate(0, slide)

        color = QColor("#704976") if is_user else QColor("#54e4c61")

        # shadow
        shadow_rect = bubble_rect.adjusted(
            self.SHADOW_OFFSET,
            self.SHADOW_OFFSET,
            self.SHADOW_OFFSET,
            self.SHADOW_OFFSET
        )
        painter.setBrush(QColor(0, 0, 0, self.SHADOW_ALPHA))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(shadow_rect, 14, 14)

        # avatar
        if not is_user:
            avatar_x = row_rect.left() + 10
            # anchor avatar near top of bubble
            avatar_y = int(y + 4)


            avatar_rect = QRect(
                avatar_x,
                avatar_y,
                self.AVATAR_SIZE,
                self.AVATAR_SIZE
            )

            painter.setBrush(QColor("#680524"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(avatar_rect.adjusted(-2, -2, 2, 2))

            path = QPainterPath()
            path.addEllipse(avatar_rect)
            painter.setClipPath(path)
            painter.drawPixmap(avatar_rect, self.avatar)
            painter.setClipping(False)

        # bubble
        painter.setBrush(color)
        painter.drawRoundedRect(bubble_rect, 14, 14)

        # centered text
        inner_x = bubble_rect.left() + self.PADDING_X / 2
        inner_y = bubble_rect.top() + (bubble_h - text_h) / 2

        painter.translate(inner_x, inner_y)
        painter.setPen(QColor("#f5d6b4"))
        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option, index):
        text, _, is_typing, _ = index.data()

        if is_typing:
            metrics = option.fontMetrics
            rect = metrics.boundingRect(text)
            return QSize(rect.width(), rect.height() + 20)

        _, _, bubble_h, _ = self._measure(text, option)

        h = max(bubble_h, self.AVATAR_SIZE)
        return QSize(0, int(h + 12))
        
# ---------- Typing animation ----------

class TypingController:
    def __init__(self, model):
        self.model = model
        self.dots = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.animate)

    def start(self):
        self.model.add_message("Mina is typing", is_typing=True)
        self.timer.start(400)

    def stop(self):
        self.timer.stop()
        self.model.remove_last()

    def animate(self):
        self.dots = (self.dots + 1) % 4
        text = "Mina is typing" + "." * self.dots

        row = len(self.model.messages) - 1
        if row >= 0:
            self.model.messages[row][0] = text
            idx = self.model.index(row)
            self.model.dataChanged.emit(idx, idx)


# ---------- Chat window ----------

class ExpandingTextEdit(QTextEdit):
    sendPressed = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.setPlaceholderText("Type a message...")
        self.textChanged.connect(self.adjust_height)

        self.max_height = 140

    def adjust_height(self):
        doc_height = self.document().size().height() + 10
        new_height = min(max(40, int(doc_height)), self.max_height)
        self.setFixedHeight(new_height)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
            self.sendPressed.emit()
        else:
            super().keyPressEvent(event)

class ChatWindow(QWidget):
    def __init__(self, brain):
        super().__init__()
        self.setObjectName("root")
        self.setStyleSheet("""
        QWidget#root {
        background-color: #505050;
        }
        """)

        self.brain = brain
        self.setWindowTitle("Mina's Chat")

        main_layout = QVBoxLayout(self)

        self.model = ChatModel()
        self.view = BackgroundListView("bg.jpg")
        self.view.setModel(self.model)
        self.view.setItemDelegate(BubbleDelegate())
        self.view.setWordWrap(True)
        self.view.setUniformItemSizes(False)

        main_layout.addWidget(self.view)

        input_layout = QHBoxLayout()

        self.entry = ExpandingTextEdit()
        self.entry.sendPressed.connect(self.send_message)


        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)

        input_layout.addWidget(self.entry)
        input_layout.addWidget(send_btn)
        main_layout.addLayout(input_layout)

        self.typing = TypingController(self.model)

        self.add_ai_message("Hi.")

    def scroll_bottom(self):
        QTimer.singleShot(10, self.view.scrollToBottom)

    def add_user_message(self, text):
        self.model.add_message(text, is_user=True)
        self.scroll_bottom()

    def add_ai_message(self, text):
        self.model.add_message(text, is_user=False)
        self.scroll_bottom()

    def send_message(self):
        user_input = self.entry.toPlainText().strip()
        if not user_input:
            return

        self.entry.clear()
        self.entry.adjust_height()

        self.add_user_message(user_input)
        self.typing.start()

        QTimer.singleShot(100, lambda: self.process_ai(user_input))
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.doItemsLayout()
    
    def process_ai(self, user_input):
        self.typing.stop()

        replies = self.brain.process_user_message(user_input)

        for r in replies:
            self.add_ai_message(r)

class BackgroundListView(QListView):
    def __init__(self, img_path):
        super().__init__()
        self.bg = QPixmap(img_path)

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.drawPixmap(self.viewport().rect(), self.bg)
        super().paintEvent(event)
