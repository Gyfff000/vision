import importlib.util
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("installer",ROOT/"examples/k230_install_autostart.py")
installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_preserves_original_startup_and_writes_verified_application(self):
        with tempfile.TemporaryDirectory(dir=ROOT,prefix="vision-install-") as temp:
            root=Path(temp)
            (root/"main.py").write_text("# original factory GUI",encoding="utf-8")
            installer.install(root.as_posix())
            self.assertEqual((root/"vision_backup/main.py.001.bak").read_text(encoding="utf-8"),"# original factory GUI")
            self.assertEqual((root/"main.py").read_text(encoding="utf-8"),installer.LAUNCHER)
            self.assertEqual((root/"k230_silver_rgb.py").read_text(encoding="utf-8"),installer.PAYLOAD)
            compile(installer.PAYLOAD,"board_application","exec")

    def test_reinstall_does_not_overwrite_existing_backups(self):
        with tempfile.TemporaryDirectory(dir=ROOT,prefix="vision-install-") as temp:
            root=Path(temp); (root/"main.py").write_text("# factory",encoding="utf-8")
            installer.install(root.as_posix()); installer.install(root.as_posix())
            self.assertEqual((root/"vision_backup/main.py.001.bak").read_text(encoding="utf-8"),"# factory")
            self.assertTrue((root/"vision_backup/main.py.002.bak").exists())
            self.assertTrue((root/"vision_backup/k230_silver_rgb.py.001.bak").exists())

if __name__=="__main__": unittest.main()
