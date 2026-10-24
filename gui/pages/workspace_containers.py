"""工作区与独立功能页面容器，保留布局归属及现有路由投影。

源自原 PyQt-Fluent-Widgets Gallery 示例（GPL-3.0）移植页面；
来源与许可说明见仓库根目录 ``THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import SmoothScrollArea

from gui.i18n import tr
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute
from gui.styles.fluent import use_smooth_scroll


class GalleryPage(QWidget):
    """参考 GalleryInterface 的独立功能页，内容直接占满页面承载区。"""

    def __init__(
        self,
        route_key: str,
        title: str,
        subtitle: str,
        content: QWidget,
        *,
        scroll_area: SmoothScrollArea | None = None,
        scroll: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if scroll:
            body = use_smooth_scroll(scroll_area or SmoothScrollArea(self))
            body.setObjectName(f"{route_key}ScrollArea")
            body.setWidgetResizable(True)
            body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body.setFrameShape(SmoothScrollArea.Shape.NoFrame)
            body.setStyleSheet("QScrollArea { border: none; background: transparent; }")

            wrapper = QWidget(body)
            wrapper.setObjectName(f"{route_key}View")
            content_layout = QVBoxLayout(wrapper)
            content_layout.setContentsMargins(32, 16, 32, 28)
            content_layout.setSpacing(20)
            content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            content.setParent(wrapper)
            content_layout.addWidget(content)
            # QScrollArea.takeWidget() 会保留旧页面的 hidden 状态；参考项目在把
            # 示例控件移入卡片后同样显式 show，确保迁移后的内容立即可见。
            content.show()
            body.setWidget(wrapper)
            self.body = body
        else:
            body_wrapper = QWidget(self)
            body_layout = QVBoxLayout(body_wrapper)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.addWidget(content)
            self.body = body_wrapper

        layout.addWidget(self.body, 1)
        # 从旧宿主转移出的滚动容器本身也可能保留 hidden 状态。
        self.body.show()


class WorkspaceSectionPage(QWidget):
    """工作台内的一个可滚动任务分区。"""

    def __init__(
        self,
        route_key: str,
        content: QWidget,
        *,
        scroll_area: SmoothScrollArea | None = None,
        scroll: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not scroll:
            content.setParent(self)
            layout.addWidget(content)
            content.show()
            self.body = content
            return
        body = use_smooth_scroll(scroll_area or SmoothScrollArea(self))
        body.setWidgetResizable(True)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        body.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        body.viewport().setAutoFillBackground(False)

        wrapper = QWidget(body)
        wrapper.setObjectName(f"{route_key}View")
        wrapper_layout = QVBoxLayout(wrapper)
        # 正文留白随页面滚动，外层滚动容器始终占满内容区。
        wrapper_layout.setContentsMargins(32, 8, 32, 44)
        wrapper_layout.setSpacing(18)
        wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content.setParent(wrapper)
        wrapper_layout.addWidget(content)
        content.show()
        body.setWidget(wrapper)
        # setWidget 会自动开启实色填充，普通留白容器必须继续透出宿主材质。
        wrapper.setAutoFillBackground(False)

        layout.addWidget(body)
        self.body = body

    def reset_scroll_position(self) -> None:
        """分类路由变化后从内容起点展示，避免继承上一分类的中段位置。"""

        horizontal = getattr(self.body, "horizontalScrollBar", None)
        vertical = getattr(self.body, "verticalScrollBar", None)
        if callable(horizontal):
            set_horizontal = getattr(horizontal(), "setValue", None)
            if callable(set_horizontal):
                set_horizontal(0)
        if callable(vertical):
            set_vertical = getattr(vertical(), "setValue", None)
            if callable(set_vertical):
                set_vertical(0)


class WorkspaceAreaPage(QWidget):
    """主导航中的独立设备任务页，并承载该领域的设备功能会话。"""

    routeChanged = Signal(object)

    def __init__(
        self,
        route_key: str,
        section_key: str,
        title: str,
        subtitle: str,
        content: QWidget,
        *,
        feature_host: WorkspaceFeatureHost | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        self.section_key = section_key.strip()
        if not self.section_key:
            raise ValueError("section_key must not be empty")
        self._base_title = title
        self._base_subtitle = subtitle
        self._route_presentations: dict[str, tuple[str, str]] = {}
        self._feature_host = feature_host
        self._current_route = WorkspaceRoute(self.section_key)
        self._queued_route: WorkspaceRoute | None = None
        self._active = False
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        content.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(content, 1)
        content.show()
        self.body = content

        if feature_host is not None:
            if feature_host.section_key != self.section_key:
                raise ValueError("feature_host section does not match page section")
            self._current_route = WorkspaceRoute(
                self.section_key,
                feature_host.current_feature,
                feature_host.current_device_id,
            )
            feature_host.route_changed.connect(self._on_feature_route_changed)
            feature_host.deactivate("page_hidden")

    @property
    def current_route(self) -> WorkspaceRoute:
        return self._current_route

    def set_route_presentation(self, feature: str, title: str, subtitle: str) -> None:
        """为一级导航保留具体功能的可访问名称，物理宿主仅作为内部资源容器。"""

        self._route_presentations[feature] = (title, subtitle)
        if self._current_route.feature == feature:
            self._set_route_presentation(self._current_route)

    def supports_route(self, route: WorkspaceRoute) -> bool:
        """只读判断路由是否属于当前领域及其已登记功能。"""

        if route.section != self.section_key:
            return False
        if self._feature_host is None:
            return route.feature == "overview"
        return self._feature_host.has_feature(route.feature)

    def open_route(self, route: WorkspaceRoute) -> bool:
        """选择目标路由；页面在后台时延迟到进入前台后再激活会话。"""

        if not self.supports_route(route):
            return False
        if self._feature_host is not None:
            route = WorkspaceRoute(
                route.section, self._feature_host.canonical_feature(route.feature),
                route.device_id, route.payload,
            )
            if not self._active:
                queued_route = route
                pending_route = self._feature_host.pending_route
                if (
                    route.payload is None
                    and pending_route is not None
                    and self._stable_route(pending_route) == self._stable_route(route)
                ):
                    # 历史返回只携带稳定位置；同一路由仍在等待设备时，不能用
                    # 这个无 payload 的恢复请求覆盖尚未实际消费的一次性参数。
                    queued_route = pending_route
                self._queued_route = queued_route
                self._set_route_presentation(route)
                return True
            self._queued_route = None
            return self._feature_host.open_route(route)
        stable_route = self._stable_route(route)
        self._current_route = stable_route
        self._set_route_presentation(stable_route)
        self.routeChanged.emit(stable_route)
        return True

    def activate(self) -> None:
        """页面进入前台时恢复当前功能的前台生命周期。"""

        if self._active:
            return
        self._active = True
        host = self._feature_host
        if host is None:
            return

        route = self._queued_route or host.pending_route or self._current_route
        self._queued_route = None
        host.activate_route(route)

    def deactivate(self, reason: str = "top_level_navigation") -> None:
        """页面离开前台时暂停瞬态工作，但保留设备会话。"""

        if not self._active:
            return
        self._active = False
        if self._feature_host is not None:
            self._feature_host.deactivate(reason)

    def set_device_context(
        self,
        selected_devices: list[str],
        connected_devices: list[str],
        _discovery_state: str,
    ) -> None:
        if self._feature_host is not None:
            self._feature_host.set_device_context(selected_devices, connected_devices)

    def _on_feature_route_changed(self, route: WorkspaceRoute) -> None:
        stable_route = self._stable_route(route)
        self._set_route_presentation(stable_route)
        self.routeChanged.emit(stable_route)

    def _set_route_presentation(self, route: WorkspaceRoute) -> None:
        """同步已选路由和可访问名称，不触发功能会话生命周期。"""

        self._current_route = self._stable_route(route)
        host = self._feature_host
        presentation = self._route_presentations.get(route.feature)
        if presentation is not None:
            self.setAccessibleName(presentation[0])
            self.setAccessibleDescription(presentation[1])
            return
        title = self._base_title
        if route.feature == "overview":
            subtitle = self._base_subtitle
        elif host is not None and host.is_overview_feature(route.feature):
            label = host.feature_label(route.feature) or route.feature
            if host.feature_requires_device(route.feature):
                context = tr("会话设备已选择") if route.device_id else tr("请选择会话设备")
            else:
                context = tr("使用顶部设备栏中勾选的操作目标")
            subtitle = f"{label} · {context}"
        else:
            label = (
                host.feature_label(route.feature) if host is not None else ""
            ) or route.feature
            if host is not None and host.feature_requires_device(route.feature):
                context = tr("会话设备已选择") if route.device_id else tr("请选择会话设备")
                subtitle = f"{label} · {context}"
            else:
                subtitle = label
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

    @staticmethod
    def _stable_route(route: WorkspaceRoute) -> WorkspaceRoute:
        """移除一次性激活参数，只保留可恢复的工作区位置。"""

        return WorkspaceRoute(route.section, route.feature, route.device_id)


__all__ = ["GalleryPage", "WorkspaceSectionPage", "WorkspaceAreaPage"]
