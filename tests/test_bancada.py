"""A bancada mede a rota real contra um servidor, em estado isolado.

Aqui o servidor é um Ollama falso em loopback: prova o encanamento do
comando, não o desempenho do X99."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


class OllamaFalso(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        corpo = json.dumps({"models": [{"name": "modelo-falso"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        pedido = json.loads(self.rfile.read(tamanho))
        pacotes = [{"model": "modelo-falso", "message": {"content": "Certo."}, "done": False},
                   {"model": "modelo-falso", "message": {"content": ""}, "done": True,
                    "prompt_eval_count": 1234, "prompt_eval_duration": 900_000_000,
                    "eval_count": 3, "eval_duration": 300_000_000,
                    "load_duration": 1_000_000, "total_duration": 1_300_000_000}]
        if not pedido.get("stream"):
            pacotes = [dict(pacotes[1], message={"content": "Certo."})]
        corpo = b"".join(json.dumps(p).encode() + b"\n" for p in pacotes)
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class Bancada(unittest.TestCase):
    def setUp(self):
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), OllamaFalso)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({
            "modelo": "modelo-falso",
            "ollama_url": f"http://127.0.0.1:{self.servidor.server_address[1]}",
            "pesquisa_provedor": "nenhum", "mapa_ativo": False}))
        self.roteiro = Path(self.temp.name) / "roteiro.json"
        self.roteiro.write_text(json.dumps({"id": "teste", "turnos": ["oi", "tudo bem?"]}))

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.temp.cleanup()

    def rodar(self, *argumentos, estado):
        ambiente = {**os.environ, "PYTHONPATH": str(RAIZ / "src")}
        ambiente = {k: v for k, v in ambiente.items() if not k.startswith("ZEUS_")}
        return subprocess.run([sys.executable, "-m", "zeus", "--state-dir", str(estado),
                               "--config", str(self.config), *argumentos],
                              capture_output=True, text=True, timeout=60, env=ambiente)

    def test_mede_cada_turno_com_estatisticas_do_servidor(self):
        estado = Path(self.temp.name) / "bancada"
        saida = self.rodar("bancada", "--roteiro", str(self.roteiro), "--repeticoes", "2",
                           estado=estado)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        linhas = [json.loads(l) for arquivo in (estado / "medidas").glob("*.jsonl")
                  for l in arquivo.read_text().splitlines()]
        turnos = [l for l in linhas if l["tipo"] == "turno"]
        self.assertEqual(len(turnos), 4)
        self.assertEqual(linhas[0]["tipo"], "sessao")
        servidor = turnos[0]["rodadas"][0]["servidor"][0]
        self.assertEqual(servidor["prompt_eval_count"], 1234)
        self.assertEqual(servidor["prompt_eval_ms"], 900.0)
        self.assertIsNotNone(turnos[0]["primeiro_fragmento_final_ms"])
        resumo = self.rodar("medidas", "--pasta", str(estado / "medidas"),
                            estado=Path(self.temp.name) / "outro")
        dados = json.loads(resumo.stdout.strip().splitlines()[-1])
        self.assertEqual(dados["turnos"], 4)
        self.assertEqual(dados["campos"]["servidor.prompt_eval_count"]["n"], 4)

    def test_recusa_pasta_com_dados(self):
        estado = Path(self.temp.name) / "ocupada"
        estado.mkdir()
        (estado / "zeus.sqlite3").write_text("x")
        saida = self.rodar("bancada", "--roteiro", str(self.roteiro), estado=estado)
        self.assertEqual(saida.returncode, 2)
        self.assertIn("não está vazio", saida.stderr)


if __name__ == "__main__":
    unittest.main()
