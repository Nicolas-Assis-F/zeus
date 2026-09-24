"""Trabalho de rede e síntese fora da thread que possui a memória do Zeus."""

import queue
import time
from threading import Event, Lock, Thread


class CaixaDeEntrada(queue.Queue):
    """Enfileirar também acorda o laço, sem esperar o intervalo da agenda."""
    def __init__(self, maxsize=32):
        super().__init__(maxsize=maxsize)
        self.acordar = Event()

    def put(self, item, block=True, timeout=None):
        # O carimbo de chegada é o começo da espera em fila. Relógio
        # monotônico: a hora de parede pode andar para trás, a espera não.
        if isinstance(item, dict):
            item.setdefault("recebido_em", time.monotonic())
        super().put(item, block, timeout)
        self.acordar.set()

    def aguardar(self, timeout):
        self.acordar.clear()
        if self.empty():
            self.acordar.wait(timeout)


class RecepcaoTelegram:
    """Uma conexão SQLite própria na thread de polling, confirmação no núcleo.

    Só busca o lote seguinte depois que o núcleo terminou o anterior. Assim
    uma consulta rápida não repete mensagens que ainda aguardam resposta.
    """
    def __init__(self, criar_canal, entrada, parado):
        self.criar_canal, self.entrada, self.parado = criar_canal, entrada, parado
        self.thread = Thread(target=self._rodar, daemon=True, name="zeus-telegram")

    def iniciar(self):
        self.thread.start()

    def _entregar(self, pacote):
        while not self.parado.is_set():
            try:
                self.entrada.put(pacote, timeout=0.25)
                return True
            except queue.Full:
                continue
        return False

    def _rodar(self):
        canal = None
        try:
            canal = self.criar_canal()
            while not self.parado.is_set():
                try:
                    mensagens = canal.receber()
                    if not mensagens:
                        self.parado.wait(0.1)
                        continue
                    terminado = Event()
                    if not self._entregar({"tipo": "telegram", "mensagens": mensagens,
                                           "terminado": terminado}):
                        break
                    while not self.parado.is_set() and not terminado.wait(0.25):
                        pass
                except Exception:
                    self.parado.wait(2)
        finally:
            if canal is not None and canal.store is not None:
                canal.store.close()


class FalaEmSegundoPlano:
    """Publica WAV depois do texto; descarta fala ultrapassada por novo turno.

    `ao_medir` recebe quanto a síntese levou, por turno, sem o texto falado."""
    def __init__(self, voz, publicar, ao_medir=None):
        self.voz, self.publicar = voz, publicar
        self.ao_medir = ao_medir
        self._trava = Lock()
        self._acordar = Event()
        self._parado = Event()
        self._geracao = 0
        self._pendente = None
        self.thread = Thread(target=self._rodar, daemon=True, name="zeus-voz")
        self.thread.start()

    def invalidar(self):
        with self._trava:
            self._geracao += 1
            self._pendente = None
            return self._geracao

    def falar(self, texto, geracao, turno=None):
        with self._trava:
            if geracao == self._geracao and not self._parado.is_set():
                self._pendente = (texto, geracao, turno)
                self._acordar.set()

    def _medir(self, turno, geracao, inicio, caracteres, resultado):
        if self.ao_medir is None:
            return
        try:
            self.ao_medir({"tipo": "voz", "v": 1, "turno": turno, "geracao": geracao,
                           "sintese_ms": round((time.monotonic() - inicio) * 1000, 1),
                           "caracteres": caracteres, "resultado": resultado})
        except Exception:
            pass

    def _rodar(self):
        while not self._parado.is_set():
            self._acordar.wait(0.25)
            with self._trava:
                self._acordar.clear()
                pedido, self._pendente = self._pendente, None
            if pedido is None:
                continue
            texto, geracao, turno = pedido
            inicio = time.monotonic()
            try:
                arquivo = self.voz.falar(texto)
                with self._trava:
                    atual = geracao == self._geracao and not self._parado.is_set()
                    if arquivo and atual:
                        self.publicar("audio", audio=f"/audio/{arquivo.name}", geracao=geracao,
                                      turno=turno)
                self._medir(turno, geracao, inicio, len(texto),
                            "sem_audio" if not arquivo else ("ok" if atual else "descartada"))
            except Exception:
                # Texto já foi entregue; falha opcional não mata o próximo áudio.
                self._medir(turno, geracao, inicio, len(texto), "erro")
                continue

    def parar(self):
        self._parado.set()
        self.invalidar()
        self._acordar.set()
        self.thread.join(timeout=0.5)


class InstanciaUnica:
    """Uma instância de run por diretório de estado; libera após crash pelo SO."""
    def __init__(self, diretorio):
        from pathlib import Path
        self.arquivo = Path(diretorio) / 'zeus.lock'
        self.fd = None

    def __enter__(self):
        import fcntl
        import os
        self.arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.arquivo, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise ValueError('Já existe uma instância do Zeus usando este estado.') from None
        return self

    def __exit__(self, *_):
        import os
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class EstadoOperacao:
    def __init__(self):
        self.trava = Lock()
        self.dados = {}

    def atualizar(self, capacidade, **campos):
        from datetime import datetime, timezone
        with self.trava:
            self.dados[capacidade] = {**self.dados.get(capacidade, {}), **campos,
                                      'atualizado_em': datetime.now(timezone.utc).isoformat()}

    def retrato(self):
        with self.trava:
            return {k: dict(v) for k, v in self.dados.items()}


class SupervisorPresenca:
    """Agenda e percepção funcionam mesmo enquanto o núcleo gera uma resposta."""
    def __init__(self, diretorio, config, parado, hud=None, operacao=None,
                 criar_canal=None, verificar=None):
        self.diretorio, self.config, self.parado = diretorio, config, parado
        self.hud, self.operacao = hud, operacao or EstadoOperacao()
        self.criar_canal, self.verificar = criar_canal, verificar
        self.thread = Thread(target=self._rodar, daemon=True, name='zeus-presenca')
        self.pronto = Event()

    def iniciar(self):
        self.thread.start()

    def _rodar(self):
        import time
        from .store import Store, agora_utc
        from .entregas import Entregas
        from .percepcao import MonitorModelo
        store = None
        try:
            store = Store(self.diretorio)
            fila = Entregas(store)
            fila.recuperar()
            canais = {}
            if self.criar_canal:
                canal = self.criar_canal(store)
                canais[canal.nome] = canal
            elif self.config.canal_configurado:
                from .canais import CanalTelegram
                canal = CanalTelegram(self.config.telegram_token, self.config.telegram_chat_id, store)
                canais['telegram'] = canal
            if self.hud is not None:
                # Entrega local significa disponível no histórico, não leitura humana.
                class CanalHUD:
                    nome = 'hud'
                    def enviar(self, texto):
                        return {'destino': 'historico_local'}
                canais['hud'] = CanalHUD()
            preferido = 'telegram' if 'telegram' in canais else next(iter(canais), 'hud')
            def sonda():
                from .llm import transporte_http, _mesmo_modelo
                dados = transporte_http('GET', self.config.ollama_url.rstrip('/') + '/api/tags', timeout=2)
                return any(_mesmo_modelo(self.config.modelo, m.get('name', '')) for m in dados.get('models', []))
            monitor = MonitorModelo(store, self.verificar or sonda, preferido)
            proxima_sonda = 0.0
            ciclos = 0
            self.pronto.set()
            while not self.parado.is_set():
                inicio = time.monotonic()
                try:
                    fila.registrar_agenda(preferido, agora_utc(), self.config.atraso_maximo_lembrete)
                    enviados = fila.enviar_pendentes(canais)
                    for item in enviados:
                        if self.hud is not None:
                            self.hud.publicar('aviso', texto=item['texto'], chave=item['chave'],
                                             canal=item['canal'], tipo_saida=item['tipo'])
                    if self.config.monitorar_modelo and self.config.provedor in ('ollama', 'hibrido') and inicio >= proxima_sonda:
                        estado = monitor.observar()
                        self.operacao.atualizar('monitor_modelo', estado=estado)
                        proxima_sonda = time.monotonic() + max(5, self.config.intervalo_monitor)
                    ciclos += 1
                    self.operacao.atualizar('agenda', estado='pronta', ciclos=ciclos,
                                            ultimo_ciclo_s=round(time.monotonic()-inicio, 3))
                    if self.hud is not None:
                        self.hud.atualizar({**self.hud.estado(), 'entregas': fila.listar(20),
                            'entradas': fila.entradas(), 'operacao': self.operacao.retrato(),
                            'perguntas': store.perguntas_abertas(), 'lembretes': store.agenda_pendente(),
                            'turnos': store.turnos(20)}, difundir=False)
                        self.hud.publicar('operacao', capacidades=self.operacao.retrato(),
                                          entregas=fila.listar(20), entradas=fila.entradas(),
                                          perguntas=store.perguntas_abertas(), lembretes=store.agenda_pendente())
                except Exception:
                    self.operacao.atualizar('agenda', estado='degradada')
                self.parado.wait(min(max(self.config.intervalo_agenda, 0.1), 1))
        except Exception:
            self.operacao.atualizar('agenda', estado='indisponivel')
            self.pronto.set()
        finally:
            if store is not None:
                store.close()

    def parar(self):
        self.parado.set()
        self.thread.join(timeout=3)
