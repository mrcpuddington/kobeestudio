"""Small, explicit compatibility surface for KiCad's legacy pcbnew API."""

from __future__ import annotations

import pcbnew


class KiCadCompatibility:
    """Board operations kept out of the geometry and UI layers."""

    def version(self) -> str:
        return pcbnew.GetBuildVersion()

    def parse_footprint(self, data: str):
        # PCB_PLUGIN was removed from the KiCad 10 Python surface.  The sexpr
        # reader is present in KiCad 10.0.x and avoids the removed API.
        return pcbnew.Cast_to_FOOTPRINT(pcbnew.PCB_IO_KICAD_SEXPR().Parse(data))

    def default_position(self, board):
        box = board.GetBoardEdgesBoundingBox()
        if box.GetWidth() > 0 and box.GetHeight() > 0:
            return box.GetCenter()
        return pcbnew.VECTOR2I(pcbnew.FromMM(100), pcbnew.FromMM(100))

    def place(self, footprint, old_footprint=None):
        board = pcbnew.GetBoard()
        if board is None:
            raise RuntimeError("No PCB is open. Open a board in PCB Editor before placing a label.")

        if old_footprint is not None:
            position = old_footprint.GetPosition()
            orientation = old_footprint.GetOrientationDegrees()
            board.Add(footprint)
            footprint.SetPosition(position)
            footprint.SetOrientationDegrees(orientation)
            board.Remove(old_footprint)
        else:
            board.Add(footprint)
            footprint.SetPosition(self.default_position(board))

        pcbnew.Refresh()
        return footprint
