"""Lifecycle boundary for dialogs with timers and background work."""

import wx


class AsyncDialog(wx.Dialog):
    """Discard late completions after a dialog closes, even before Destroy."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._background_closed = False
        self._owned_timers = []
        self.Bind(wx.EVT_CLOSE, self._on_background_close)

    def own_timer(self):
        timer = wx.Timer(self)
        self._owned_timers.append(timer)
        return timer

    def accepts_background_results(self):
        return not self._background_closed and bool(self) and not self.IsBeingDeleted()

    def _stop_background(self):
        self._background_closed = True
        # Child preview canvases also own native timers. Cocoa can deliver
        # their callbacks during a subsequent modal loop after their owner
        # has gone away, so stop the whole dialog tree before destroying it.
        if self:
            for timer in self._owned_timers:
                timer.Stop()
            self._stop_window_timers(self)

    @classmethod
    def _stop_window_timers(cls, window):
        for value in vars(window).values():
            if isinstance(value, wx.Timer):
                value.Stop()
        for child in window.GetChildren():
            cls._stop_window_timers(child)

    def _on_background_close(self, event):
        self._stop_background()
        event.Skip()

    def EndModal(self, result):
        self._stop_background()
        return super().EndModal(result)

    def Destroy(self):
        self._stop_background()
        return super().Destroy()
