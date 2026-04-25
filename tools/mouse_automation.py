from PyQt5 import QtWidgets

class MouseAutomationPage(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Mouse Automation")
        title.setObjectName("PageTitle")
        msg = QtWidgets.QLabel("Coming soon…")
        msg.setObjectName("ComingSoon")
        lay.addWidget(title)
        lay.addWidget(msg)
        lay.addStretch(1)
