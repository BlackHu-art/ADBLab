"""日志输出与文件列表一样透出宿主底色，局部策略不改变共享阅读材质。"""

from PySide6.QtWidgets import QFrame, QWidget
from qfluentwidgets import PlainTextEdit, setCustomStyleSheet
from shiboken6 import isValid

from gui.styles.reading_surface import ReadingSurfaceMaterial


class LogcatMaterial(ReadingSurfaceMaterial):
    """保留日志文字与阅读状态，在全部宿主和交互状态下使用透明底板。"""

    def __init__(self, owner: QWidget, output: PlainTextEdit):
        output.setFrameShape(QFrame.Shape.NoFrame)
        # Fluent 的焦点底线由独立子控件绘制，仅移除 QSS 边框不会隐藏它。
        output.layer.hide()
        super().__init__(owner, output)

    def _apply_surface(self, transparent: bool) -> None:
        """透明策略不依赖云母开关，主题刷新只重建文字及局部无边框规则。"""
        # 日志与文件列表共享页面底色；仅此页面始终选择透明分支，保留原生文字调色板。
        super()._apply_surface(True)
        output = self._output_ref()
        if output is None or not isValid(output):
            return
        borderless = (
            " PlainTextEdit, PlainTextEdit:hover, PlainTextEdit:focus, PlainTextEdit:disabled "
            "{ border: none; border-radius: 0px; padding: 0px; }"
        )
        setCustomStyleSheet(
            output,
            str(output.property("lightCustomQss") or "") + borderless,
            str(output.property("darkCustomQss") or "") + borderless,
        )
