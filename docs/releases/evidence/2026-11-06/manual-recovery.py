"""Launch real source editor against disposable data; all interactions are manual."""
import sys, json, hashlib, zipfile
from pathlib import Path
sys.path[:0] = ['/Users/coreybusuttil/dev/github/kobeestudio', '/private/tmp/kobeestudio-acceptance-deps']
import wx
from kobeestudio.core.library_archive import restore_library
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.ui.editor_v2 import StudioEditorDialog
base = Path('/private/tmp/kobeestudio-resume-KuvFEd')
root = base / 'manual-recovery-data'
backup = base / 'kobee-studio-data-backup.zip'
if not root.exists():
    restore_library(backup, root)
with zipfile.ZipFile(base / 'invalid-backup.zip', 'w') as z:
    z.writestr('../escape.txt', 'this must not be extracted')

def snapshot(stage):
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file()}
    with (base / 'manual-recovery-stages.jsonl').open('a') as out:
        out.write(json.dumps({'stage':stage, 'root':str(root), 'files':files})+'\n')

app=wx.App(False)
app.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
resume=None
count=0
while True:
    snapshot('before editor '+str(count))
    dialog=StudioEditorDialog(None, str(root / 'config.json'), TextGeometry().buzzard,
                              lambda *_: None, build_label='isolated recovery test')
    if resume:
        dialog.restore_session_state(resume)
    dialog.ShowModal()
    restart=bool(getattr(dialog, 'restart_requested', False))
    resume=getattr(dialog, 'restart_state', None)
    dialog.Destroy()
    wx.Yield()
    snapshot('after editor '+str(count))
    count+=1
    if not restart: break
