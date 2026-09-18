import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from zeus.store import Store


class MemoryTests(unittest.TestCase):
    def test_restart_correction_and_forgetting(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            store.remember("tratamento", "senhor")
            store.close()
            store = Store(Path(temp))
            self.assertEqual(store.recall("tratamento")["value"], "senhor")
            store.remember("tratamento", "Nicolas", "user_correction")
            self.assertEqual(store.recall("tratamento")["source"], "user_correction")
            self.assertTrue(store.forget("tratamento"))
            store.close()
            store = Store(Path(temp))
            self.assertIsNone(store.recall("tratamento"))
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            store.close()

    def test_untrusted_text_remains_data_and_missing_fact_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            key = "'; DROP TABLE facts; --"
            store.remember(key, "texto literal")
            self.assertEqual(store.recall(key)["value"], "texto literal")
            self.assertIsNone(store.recall("rotina_nao_informada"))
            with self.assertRaises(ValueError):
                store.remember("rotina", "  ")
            store.close()

    def test_service_starts_stops_and_retains_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            store.remember("teste", "persistente")
            store.close()
            process = subprocess.Popen(
                [sys.executable, "-m", "zeus", "--state-dir", temp, "run"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=os.environ.copy(),
            )
            try:
                import selectors
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=10), "Processo não iniciou")
                self.assertEqual(json.loads(process.stdout.readline())["event"], "started")
                process.terminate()
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, err)
                self.assertIn('"stopped"', out)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            store = Store(Path(temp))
            self.assertEqual(store.recall("teste")["value"], "persistente")
            store.close()


if __name__ == "__main__":
    unittest.main()
