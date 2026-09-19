"""首次显示前同步落实页面布局，避免首帧沿用构造期的旧几何。"""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget


def settle_widget_layout(widget: QWidget | None, *, rounds: int = 2) -> None:
    """把宿主已交付的最终宽度落实为页面几何。

    调用点必须在“页面已成为当前页、但尚未绘制首帧”的窗口内。只激活页面自身的布局
    不够：页面此时往往还是创建期的尺寸，必须自顶向下逐级激活祖先布局，先让宿主把
    最终 rect 交付下来，再激活页面布局；顺序反了只会把旧宽度上的计划重算一遍。
    轮次上限避免异常情况下反复激活布局。
    """

    app = QApplication.instance()
    if widget is None or app is None:
        return
    chain: list[QWidget] = []
    current: QWidget | None = widget
    while current is not None:
        chain.append(current)
        current = current.parentWidget()
    chain.reverse()
    for _ in range(max(1, rounds)):
        app.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        for item in chain:
            layout = item.layout()
            if layout is not None:
                layout.activate()


def settle_responsive_layout(
    widget: QWidget | None,
    coordinator,
    *,
    rounds: int = 1,
) -> None:
    """页面刚成为当前页时同步收敛：先落实宿主几何，再同步落实响应式计划。

    响应式计划的宽度取自控件真实几何，而计划落实又会改变行高，因此必须交替进行：
    只落实布局会让首帧继续使用隐藏期算出的旧计划，只落实计划则会用尚未更新的宽度
    重新规划。调用点同样必须在首帧绘制之前的窗口内，且协调器必须与页面共享。

    rounds 是同步落实计划的代次上限。每次落实都是一代完整重规划并触发一次宿主约束
    同步，因此默认只跑一代：几何在落实后仍有变化时，由协调器既有的有界轮次继续收敛，
    不必在切页路径上把重排成本翻倍。
    """

    settle_widget_layout(widget)
    if widget is None or coordinator is None:
        return
    for _ in range(max(1, rounds)):
        if not coordinator.settle_now():
            return
        settle_widget_layout(widget)


__all__ = ["settle_responsive_layout", "settle_widget_layout"]
