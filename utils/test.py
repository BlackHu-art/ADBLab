#!/usr/bin/env python
# -*- coding: utf-8 -*-
import wx
import wx.py.images


class ToolbarFrame(wx.Frame):
    def __init__(self, parent, id):
        wx.Frame.__init__(self, parent, id, 'Toolbars', size=(600, 400))
        # self.SetWindowStyle(wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR | wx.FRAME_TOOL_WINDOW | wx.BORDER_NONE)

        panel = wx.Panel(self)
        panel.SetBackgroundColour('White')

        # 绑定鼠标事件
        panel.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        panel.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        panel.Bind(wx.EVT_MOTION, self.on_mouse_move)
        panel.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_capture_lost)  # 新增捕获丢失处理

        # 创建状态栏
        statusBar = self.CreateStatusBar()

        # 创建工具栏
        toolbar = self.CreateToolBar()
        toolbar.AddSimpleTool(wx.ID_ANY, wx.py.images.getPyBitmap(), "New", "Long help for 'New'")
        toolbar.AddSimpleTool(wx.ID_ANY, wx.py.images.getPyBitmap(), "Edit", "Long help for 'Edit'")
        toolbar.Realize()

        # 创建菜单
        menuBar = wx.MenuBar()
        menu1 = wx.Menu()
        menuBar.Append(menu1, u"&文件")
        self.close = menu1.Append(wx.ID_EXIT, u"退出(&X)", "")
        menu2 = wx.Menu()
        self.Copy = menu2.Append(wx.ID_ANY, "&Copy", "Copy in status bar")
        self.Cut = menu2.Append(wx.ID_ANY, "C&ut", "")
        self.Paste = menu2.Append(wx.ID_ANY, "Paste", "")
        menu2.AppendSeparator()
        self.Options = menu2.Append(wx.ID_ANY, "&Options...", "Display Options")
        self.Edit = menuBar.Append(menu2, "&Edit")
        self.SetMenuBar(menuBar)
        self.Bind(wx.EVT_MENU, self.OnClose, id=wx.ID_EXIT)

    def OnClose(self, event):
        self.Close()

    def on_left_down(self, event):
        """处理鼠标按下事件"""
        if not self.HasCapture():
            self.CaptureMouse()
            self._start_pos = event.GetEventObject().ClientToScreen(event.GetPosition())
            self._window_pos = self.GetPosition()
        event.Skip()

    def on_mouse_move(self, event):
        """处理鼠标移动事件"""
        if event.Dragging() and event.LeftIsDown() and self.HasCapture():
            current_pos = event.GetEventObject().ClientToScreen(event.GetPosition())
            delta = current_pos - self._start_pos
            self.Move(self._window_pos + delta)
        event.Skip()

    def on_left_up(self, event):
        """处理鼠标释放事件"""
        if self.HasCapture():
            self.ReleaseMouse()
        if hasattr(self, '_start_pos'):
            del self._start_pos
        event.Skip()

    def on_capture_lost(self, event):
        """处理鼠标捕获丢失事件"""
        if hasattr(self, '_start_pos'):
            del self._start_pos
        event.Skip()


if __name__ == '__main__':
    app = wx.App()
    frame = ToolbarFrame(parent=None, id=wx.ID_ANY)
    frame.Show()
    app.MainLoop()