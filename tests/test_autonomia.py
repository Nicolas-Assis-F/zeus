"""Autonomia (fase 2): objetivos, guarda, níveis, aprovações, trilha e feedback."""

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zeus.autonomia import (Autonomia, CATALOGO_DE_NIVEIS, Nivel, TransicaoInvalida,
                            args_hash, interpretar_resposta, nivel_efetivo)
from zeus.autonomia.trilha import segredo_do_arquivo

FUSO = timezone(timedelta(hours=-3))
SEGREDO = b"segredo-de-teste"


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def avancar(self, segundos):
        self.agora += segundos


def epoch(texto):
    return datetime.fromisoformat(texto).replace(tzinfo=FUSO).timestamp()


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.caminho = Path(self.pasta.name) / "autonomia.db"
        self.relogio = Relogio(epoch("2026-10-17T10:00:00"))
        self.abertos = []
        self.a = self.abrir()

    def abrir(self, **extra):
        autonomia = Autonomia(self.caminho, segredo=SEGREDO, relogio=self.relogio, fuso=FUSO, **extra)
        self.abertos.append(autonomia)
        return autonomia

    def tearDown(self):
        for autonomia in self.abertos:
            try:
                autonomia.fechar()
            except Exception:
                pass
        self.pasta.cleanup()

    def executar(self, objetivo_id, acao, args=None, estado="feito", custo=0.0):
        passo = self.a.objetivos.adicionar_passo(objetivo_id, acao, args)
        self.assertTrue(self.a.objetivos.iniciar_passo(passo))
        self.assertTrue(self.a.objetivos.terminar_passo(passo, estado, "ok", custo_usd=custo))
        return passo


class TestObjetivos(Base):
    def test_ciclo_completo(self):
        o = self.a.objetivos
        i = o.criar("Cobrar frete", pedido_original="vê com o Henrique o frete",
                    proxima_acao="ler conversa")
        self.assertEqual(o.obter(i)["estado"], "ativo")
        self.assertEqual(o.obter(i)["dono"], "nicolas")
        o.atualizar(i, proxima_acao="esperar resposta", estado_json={"tentou": 1},
                    acordar_por="aprovacao:7", acordar_em=None)
        o.mudar_estado(i, "aguardando_nicolas", "precisa do ok")
        self.assertEqual(o.acordar_por_evento("aprovacao:7"), [i])
        objetivo = o.obter(i)
        self.assertEqual(objetivo["estado"], "ativo")
        self.assertEqual(objetivo["estado_json"], {"tentou": 1})
        self.assertIn(i, [d["id"] for d in o.devidos()])
        with self.assertRaises(ValueError):
            o.concluir(i, "")
        with self.assertRaises(ValueError):
            o.concluir(i, None)
        with self.assertRaises(TransicaoInvalida):
            o.mudar_estado(i, "concluido")
        feito = o.concluir(i, {"mensagem": "Henrique: chegou ontem"})
        self.assertEqual(feito["estado"], "concluido")
        self.assertIn("chegou", feito["evidencia"])
        with self.assertRaises(TransicaoInvalida):
            o.mudar_estado(i, "ativo")
        self.assertEqual([x["id"] for x in o.listar("concluido")], [i])
        self.assertTrue(self.a.trilha.verificar()[0])

    def test_campos_protegidos_nao_editam_por_atualizar(self):
        i = self.a.objetivos.criar("x")
        for campo in ("estado", "evidencia", "taint", "passos_hoje"):
            with self.assertRaises(ValueError):
                self.a.objetivos.atualizar(i, **{campo: "y"})

    def test_devidos_respeita_hora_e_evento(self):
        o = self.a.objetivos
        agora = self.relogio()
        ja = o.criar("já")
        depois = o.criar("depois", acordar_em=agora + 3600)
        evento = o.criar("evento", acordar_por="aprovacao:1")
        self.assertEqual([d["id"] for d in o.devidos()], [ja])
        o.acordar_por_evento("aprovacao:1")
        self.assertEqual({d["id"] for d in o.devidos()}, {ja, evento})
        self.relogio.avancar(3601)
        self.assertEqual({d["id"] for d in o.devidos()}, {ja, evento, depois})
        self.assertTrue(o.travar(evento, "tick"))
        self.assertNotIn(evento, [d["id"] for d in o.devidos()])
        self.assertTrue(o.liberar(evento, "tick", acordar_em=None))
        self.assertNotIn(evento, [d["id"] for d in o.devidos()])

    def test_retomada_apos_reinicio(self):
        o = self.a.objetivos
        i = o.criar("Persistir", estado_json={"etapa": 2}, taint=["externo:whatsapp:Henrique"])
        passo = o.adicionar_passo(i, "pesquisar", {"consulta": "frete"})
        o.iniciar_passo(passo)
        pedido = self.a.aprovacoes.pedir("enviar_whatsapp", "Henrique", {"contato": "Henrique"},
                                         porque="cobrar", objetivo_id=i)
        self.a.feedback.registrar("acompanhamento", "util")
        self.a.fechar()

        b = self.abrir()
        self.assertEqual(b.objetivos.recuperar_passos_interrompidos(), 1)
        objetivo = b.objetivos.obter(i)
        self.assertEqual(objetivo["estado_json"], {"etapa": 2})
        self.assertEqual(objetivo["taint"], ["externo:whatsapp:Henrique"])
        self.assertEqual(objetivo["passos"][0]["estado"], "aguardando")
        self.assertIn("incerto", objetivo["passos"][0]["verificacao"])
        self.assertEqual(objetivo["passos_hoje"], 1)
        self.assertEqual([p["codigo"] for p in b.aprovacoes.pendentes()], [pedido["codigo"]])
        self.assertEqual(b.feedback.contadores("acompanhamento")["util"], 1)
        self.assertEqual(b.trilha.verificar(), (True, None))

    def test_trava_atomica_entre_threads(self):
        i = self.a.objetivos.criar("disputado")
        outro = self.abrir()  # outra conexão no mesmo arquivo, como outro processo
        barreira = threading.Barrier(2)
        resultados = {}

        def tentar(nome, autonomia):
            barreira.wait()
            resultados[nome] = autonomia.objetivos.travar(i, nome)

        threads = [threading.Thread(target=tentar, args=("a", self.a)),
                   threading.Thread(target=tentar, args=("b", outro))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(resultados.values()), [False, True])

    def test_trava_mesma_conexao_em_muitas_threads(self):
        i = self.a.objetivos.criar("disputado")
        ganhos = []
        barreira = threading.Barrier(8)

        def tentar(n):
            barreira.wait()
            if self.a.objetivos.travar(i, f"t{n}"):
                ganhos.append(n)

        threads = [threading.Thread(target=tentar, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(ganhos), 1)

    def test_lock_zumbi_expira(self):
        o = self.a.objetivos
        i = o.criar("zumbi")
        self.assertTrue(o.travar(i, "processo-morto"))
        self.relogio.avancar(599)
        self.assertFalse(o.travar(i, "novo"))
        self.relogio.avancar(2)
        self.assertTrue(o.travar(i, "novo"))
        self.assertFalse(o.liberar(i, "processo-morto"))
        self.assertTrue(o.liberar(i, "novo"))

    def test_taint_so_cresce_e_vai_para_trilha(self):
        o = self.a.objetivos
        i = o.criar("x")
        o.adicionar_taint(i, "externo:email:fornecedor")
        o.adicionar_taint(i, "externo:email:fornecedor")
        self.assertEqual(o.obter(i)["taint"], ["externo:email:fornecedor"])
        self.assertEqual(len(self.a.trilha.listar(tipos=["taint"])), 1)


class TestGuarda(Base):
    def test_teto_de_passos_por_dia(self):
        i = self.a.objetivos.criar("x", teto_passos_dia=3)
        for n in range(3):
            self.assertTrue(self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": n}))
            self.executar(i, "pesquisar", {"q": n})
        veredito = self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 99})
        self.assertEqual(veredito.decisao, "bloquear")
        self.assertIn("passos", veredito.motivo)

    def test_teto_de_custo(self):
        i = self.a.objetivos.criar("x", teto_usd_dia=0.5)
        self.executar(i, "pesquisar", {"q": 1}, custo=0.3)
        self.assertTrue(self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 2}))
        self.executar(i, "pesquisar", {"q": 2}, custo=0.25)
        veredito = self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 3})
        self.assertFalse(veredito)
        self.assertIn("US$", veredito.motivo)
        self.assertAlmostEqual(self.a.objetivos.obter(i)["custo_usd_total"], 0.55)

    def test_mesma_acao_repetida(self):
        i = self.a.objetivos.criar("x")
        self.executar(i, "ler_pagina", {"url": "a"})
        self.assertTrue(self.a.objetivos.avaliar_passo(i, "ler_pagina", {"url": "a"}))
        self.executar(i, "ler_pagina", {"url": "a"}, estado="falhou")
        veredito = self.a.objetivos.avaliar_passo(i, "ler_pagina", {"url": "a"})
        self.assertFalse(veredito)
        self.assertIn("mesmos argumentos", veredito.motivo)
        # A ordem das chaves não muda a identidade.
        self.assertFalse(self.a.objetivos.avaliar_passo(i, "ler_pagina", {"url": "a"}))
        self.assertEqual(args_hash("x", {"a": 1, "b": 2}), args_hash("x", {"b": 2, "a": 1}))

    def test_ping_pong_bloqueia(self):
        i = self.a.objetivos.criar("x")
        o = self.a.objetivos
        sequencia = [("pesquisar", {"q": "A"}), ("ler_pagina", {"url": "B"})] * 3
        for acao, args in sequencia[:5]:
            self.assertTrue(o.avaliar_passo(i, acao, args))
            o.adicionar_passo(i, acao, args)  # pendente: a regra de repetição não pega
        veredito = o.avaliar_passo(i, *sequencia[5])
        self.assertFalse(veredito)
        self.assertIn("período 2", veredito.motivo)

    def test_periodo_tres_bloqueia(self):
        i = self.a.objetivos.criar("x")
        o = self.a.objetivos
        ciclo = [("pesquisar", {"q": 1}), ("ler_pagina", {"url": 2}), ("consultar_base", {"busca": 3})]
        for acao, args in (ciclo * 2)[:5]:
            o.adicionar_passo(i, acao, args)
        veredito = o.avaliar_passo(i, *ciclo[2])
        self.assertIn("período 3", veredito.motivo)

    def test_mesma_ferramenta_com_args_diferentes_nao_e_laco(self):
        i = self.a.objetivos.criar("x")
        for n in range(1, 7):
            self.assertTrue(self.a.objetivos.avaliar_passo(i, "pesquisar", {"consulta": f"args{n}"}))
            self.executar(i, "pesquisar", {"consulta": f"args{n}"})

    def test_virada_do_dia_local_zera(self):
        self.relogio.agora = epoch("2026-10-17T23:50:00")
        i = self.a.objetivos.criar("x", teto_passos_dia=1, teto_usd_dia=0.1)
        self.executar(i, "pesquisar", {"q": 1}, custo=0.2)
        self.assertFalse(self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 2}))
        # 02:55 UTC do dia 18 ainda é dia 17 em Brasília.
        self.relogio.agora = epoch("2026-10-17T23:55:00")
        self.assertFalse(self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 2}))
        self.relogio.agora = epoch("2026-10-18T00:01:00")
        self.assertTrue(self.a.objetivos.avaliar_passo(i, "pesquisar", {"q": 2}))
        objetivo = self.a.objetivos.obter(i)
        self.assertEqual((objetivo["passos_hoje"], objetivo["custo_usd_hoje"]), (0, 0))
        self.assertEqual(objetivo["dia_dos_passos"], "2026-10-18")
        self.assertAlmostEqual(objetivo["custo_usd_total"], 0.2)

    def test_sem_progresso_bloqueia_na_terceira(self):
        i = self.a.objetivos.criar("x")
        o = self.a.objetivos
        self.assertEqual(o.registrar_progresso(i, False), "ativo")
        self.assertEqual(o.registrar_progresso(i, True), "ativo")
        o.registrar_progresso(i, False)
        o.registrar_progresso(i, False)
        self.assertEqual(o.registrar_progresso(i, False), "bloqueado")
        self.assertIn("sem progresso", o.obter(i)["motivo"])
        self.assertEqual(len(self.a.trilha.listar(tipos=["laco"])), 1)
        self.assertFalse(o.avaliar_passo(i, "pesquisar", {}))
        o.mudar_estado(i, "ativo", "Nicolas destravou")
        self.assertEqual(o.obter(i)["sem_progresso"], 0)

    def test_helper_bloquear(self):
        i = self.a.objetivos.criar("x")
        self.assertEqual(self.a.objetivos.bloquear(i, "laço detectado")["estado"], "bloqueado")
        self.assertEqual(self.a.trilha.listar(tipos=["laco"])[0]["resultado"], "laço detectado")


class TestNiveis(Base):
    def test_catalogo_cobre_as_ferramentas_reais(self):
        from zeus.ferramentas import NOMES
        self.assertEqual(NOMES - set(CATALOGO_DE_NIVEIS), set())
        for nome in ("reiniciar_servico", "mudar_volume", "mudo", "criar_evento_agenda", "escrever_nota"):
            self.assertIn(nome, CATALOGO_DE_NIVEIS)

    def test_pisos(self):
        self.assertEqual(nivel_efetivo("pesquisar")[0], Nivel.LIVRE)
        self.assertEqual(nivel_efetivo("ler_arquivo", {"caminho": "x"})[0], Nivel.LIVRE)
        self.assertEqual(nivel_efetivo("esquecer_fato", {"chave": "x"})[0], Nivel.FAZ_E_AVISA)
        self.assertIsNotNone(CATALOGO_DE_NIVEIS["esquecer_fato"].reversivel_com)
        self.assertEqual(nivel_efetivo("iniciar_tarefa", {"numero": 3})[0], Nivel.FAZ_E_AVISA)
        self.assertEqual(nivel_efetivo("gerar_orcamento", {"numero": "ZT1"})[0], Nivel.FAZ_E_AVISA)
        nivel, motivo = nivel_efetivo("gerar_orcamento", {"numero": "ZT1", "destinatario": "Cliente X"})
        self.assertEqual(nivel, Nivel.PEDE_ANTES)
        self.assertIn("terceiro", motivo)
        self.assertEqual(nivel_efetivo("enviar_whatsapp", {"contato": "Henrique"})[0], Nivel.PEDE_ANTES)
        for acao in ("apagar_arquivo", "fazer_merge", "fazer_push", "fazer_deploy", "gastar_dinheiro"):
            self.assertEqual(nivel_efetivo(acao)[0], Nivel.PEDE_ANTES)
            self.assertTrue(CATALOGO_DE_NIVEIS[acao].irreversivel)

    def test_acao_desconhecida_pede_antes(self):
        nivel, motivo = nivel_efetivo("rm_rf", {}, autonomia="ousada")
        self.assertEqual(nivel, Nivel.PEDE_ANTES)
        self.assertIn("fora do catálogo", motivo)
        self.assertEqual(nivel_efetivo("reiniciar_servico", {"servico": "sshd"}, autonomia="ousada")[0],
                         Nivel.PEDE_ANTES)

    def test_conservadora_e_ousada(self):
        self.assertEqual(nivel_efetivo("lembrar_fato", {}, autonomia="conservadora")[0], Nivel.PEDE_ANTES)
        self.assertEqual(nivel_efetivo("pesquisar", {}, autonomia="conservadora")[0], Nivel.LIVRE)
        self.assertEqual(nivel_efetivo("reiniciar_servico", {"servico": "zeus"})[0], Nivel.PEDE_ANTES)
        self.assertEqual(nivel_efetivo("reiniciar_servico", {"servico": "zeus"}, autonomia="ousada")[0],
                         Nivel.FAZ_E_AVISA)
        self.assertEqual(nivel_efetivo("lembrar_fato", {}, autonomia="invalida")[0], Nivel.PEDE_ANTES)

    def test_irreversivel_e_terceiro_nunca_descem(self):
        for acao, args in (("enviar_whatsapp", {"contato": "Henrique"}), ("fazer_push", {}),
                           ("apagar_arquivo", {"caminho": "/x"}),
                           ("gerar_documento", {"titulo": "t", "para": "Cliente"}),
                           ("criar_evento_agenda", {"convidados": ["a@b"]})):
            self.assertEqual(nivel_efetivo(acao, args, autonomia="ousada")[0], Nivel.PEDE_ANTES, acao)

    def test_taint_externo_sobe_com_motivo(self):
        taint = {"externo:whatsapp:Henrique"}
        nivel, motivo = nivel_efetivo("lembrar_fato", {"chave": "x"}, taint, "ousada")
        self.assertEqual(nivel, Nivel.PEDE_ANTES)
        self.assertEqual(motivo, "veio de conteúdo externo: whatsapp:Henrique")
        self.assertEqual(nivel_efetivo("reiniciar_servico", {"servico": "zeus"}, taint, "ousada")[0],
                         Nivel.PEDE_ANTES)
        # Leitura continua livre; taint de origem interna não conta.
        self.assertEqual(nivel_efetivo("pesquisar", {}, taint)[0], Nivel.LIVRE)
        self.assertEqual(nivel_efetivo("lembrar_fato", {}, {"nicolas"})[0], Nivel.FAZ_E_AVISA)


class TestAprovacoes(Base):
    def pedir(self, **extra):
        dados = dict(acao="enviar_whatsapp", alvo="Henrique (+55 11 9...)",
                     args={"contato": "Henrique", "mensagem": "Chegou o frete?"}, porque="cobrar frete")
        dados.update(extra)
        return self.a.aprovacoes.pedir(**dados)

    def test_codigo_de_quatro_digitos_unico(self):
        codigos = {self.pedir(args={"n": n})["codigo"] for n in range(50)}
        self.assertEqual(len(codigos), 50)
        self.assertTrue(all(len(c) == 4 and c.isdigit() for c in codigos))

    def test_mesmo_pedido_pendente_nao_duplica(self):
        primeiro, segundo = self.pedir(), self.pedir()
        self.assertEqual(primeiro["id"], segundo["id"])
        self.assertFalse(segundo["novo"])

    def test_uso_unico_amarrado_ao_payload(self):
        p = self.pedir()
        hash_ok = args_hash("enviar_whatsapp", {"contato": "Henrique", "mensagem": "Chegou o frete?"})
        self.assertFalse(self.a.aprovacoes.consumir(p["id"], hash_ok))  # ainda pendente
        self.assertTrue(self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")["ok"])
        outro = args_hash("enviar_whatsapp", {"contato": "Outro", "mensagem": "Chegou o frete?"})
        self.assertFalse(self.a.aprovacoes.consumir(p["id"], outro))
        self.assertTrue(self.a.aprovacoes.consumir(p["id"], hash_ok))
        self.assertFalse(self.a.aprovacoes.consumir(p["id"], hash_ok))
        self.assertEqual(self.a.aprovacoes.obter(p["id"])["estado"], "consumida")
        # Aprovar de novo depois de consumida não reabre.
        repetida = self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "sala")
        self.assertTrue(repetida["repetida"])
        self.assertFalse(self.a.aprovacoes.consumir(p["id"], hash_ok))

    def test_expiracao(self):
        a = self.abrir(validade_aprovacao_s=3600)
        p = a.aprovacoes.pedir("fazer_push", "origin/main", {"ref": "main"})
        self.relogio.avancar(3601)
        self.assertEqual(a.aprovacoes.pendentes(), [])
        self.assertEqual(a.aprovacoes.obter(p["id"])["estado"], "expirada")
        self.assertFalse(a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")["ok"])
        self.assertEqual(len(a.trilha.listar(tipos=["expiracao"])), 1)

    def test_decidir_vencida_sem_passar_por_pendentes(self):
        p = self.pedir(validade_s=60)
        self.relogio.avancar(61)
        resultado = self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")
        self.assertFalse(resultado["ok"])
        self.assertIn("expirou", resultado["motivo"])

    def test_terceiro_nao_decide(self):
        p = self.pedir()
        resultado = self.a.aprovacoes.decidir(p["codigo"], True, "Henrique", "whatsapp")
        self.assertFalse(resultado["ok"])
        self.assertEqual(self.a.aprovacoes.obter(p["id"])["estado"], "pendente")
        self.assertEqual(len(self.a.trilha.listar(tipos=["aviso"])), 1)

    def test_negada_nao_consome(self):
        p = self.pedir()
        self.assertTrue(self.a.aprovacoes.decidir(p["id"], False, "nicolas", "sala")["ok"])
        hash_ok = args_hash("enviar_whatsapp", {"contato": "Henrique", "mensagem": "Chegou o frete?"})
        self.assertFalse(self.a.aprovacoes.consumir(p["id"], hash_ok))
        mudar = self.a.aprovacoes.decidir(p["id"], True, "nicolas", "sala")
        self.assertFalse(mudar["ok"])
        self.assertEqual(self.a.aprovacoes.obter(p["id"])["estado"], "negada")

    def test_idempotencia(self):
        p = self.pedir()
        primeira = self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")
        segunda = self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "sala")
        self.assertTrue(primeira["ok"] and segunda["ok"])
        self.assertFalse(primeira["repetida"])
        self.assertTrue(segunda["repetida"])
        self.assertEqual(segunda["aprovacao"]["canal_da_decisao"], "grupo")
        self.assertEqual(len(self.a.trilha.listar(tipos=["aprovacao"])), 1)

    def test_aprovacao_acorda_objetivo(self):
        i = self.a.objetivos.criar("x")
        p = self.pedir(objetivo_id=i)
        self.a.objetivos.atualizar(i, acordar_por=f"aprovacao:{p['id']}", acordar_em=None)
        self.a.objetivos.mudar_estado(i, "aguardando_nicolas", "esperando ok")
        self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")
        objetivo = self.a.objetivos.obter(i)
        self.assertEqual(objetivo["estado"], "ativo")
        self.assertEqual(objetivo["evento_recebido"], f"aprovacao:{p['id']}")

    def test_callback_ao_mudar(self):
        vistos = []
        cancelar = self.a.aprovacoes.ao_mudar(lambda ap: vistos.append(ap["estado"]))
        self.a.aprovacoes.ao_mudar(lambda ap: 1 / 0)  # assinante quebrado não atrapalha
        p = self.pedir()
        self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")
        self.a.aprovacoes.decidir(p["codigo"], True, "nicolas", "grupo")  # repetida: sem aviso
        self.a.aprovacoes.consumir(p["id"], args_hash(
            "enviar_whatsapp", {"contato": "Henrique", "mensagem": "Chegou o frete?"}))
        self.assertEqual(vistos, ["pendente", "aprovada", "consumida"])
        cancelar()
        self.pedir(args={"outro": 1})
        self.assertEqual(len(vistos), 3)


class TestInterpretarResposta(unittest.TestCase):
    def test_positivos(self):
        for texto in ("ok 4821", "sim 4821", "aprovo 4821", "4821 ok", "OK, 4821", "Sim: 4821!"):
            self.assertEqual(interpretar_resposta(texto), [("4821", True)], texto)

    def test_negativos(self):
        for texto in ("não 4821", "nao 4821", "nega 4821", "negar 4821", "4821 não",
                      "não aprovo 4821"):
            self.assertEqual(interpretar_resposta(texto), [("4821", False)], texto)

    def test_varios_codigos_cada_um_com_sua_palavra(self):
        self.assertEqual(interpretar_resposta("ok 4821 e não 1234"), [("4821", True), ("1234", False)])
        self.assertEqual(interpretar_resposta("4821 ok, 1234 não"), [("4821", True), ("1234", False)])

    def test_recusas(self):
        for texto in ("ok", "sim", "sim para todos", "ok all", "aprovo todos 4821", "pode tudo",
                      "4821", "ok 4821 1234", "obrigado", "", "ok 48210", "ok 482"):
            self.assertEqual(interpretar_resposta(texto), [], texto)
        # O mesmo código com sim e não se anula.
        self.assertEqual(interpretar_resposta("ok 4821 não 4821"), [])


class TestTrilha(Base):
    def test_encadeamento_e_adulteracao(self):
        t = self.a.trilha
        ids = [t.registrar("execucao", acao="pesquisar", resultado=f"r{n}", custo_usd=0.01) for n in range(5)]
        self.assertEqual(t.verificar(), (True, None))
        db = sqlite3.connect(self.caminho)
        db.execute("UPDATE trilha SET resultado='mentira' WHERE id=?", (ids[2],))
        db.commit()
        db.close()
        self.assertEqual(t.verificar(), (False, ids[2]))

    def test_hash_vazio_e_falha(self):
        t = self.a.trilha
        ids = [t.registrar("aviso", resultado=str(n)) for n in range(3)]
        db = sqlite3.connect(self.caminho)
        db.execute("UPDATE trilha SET row_hash='' WHERE id=?", (ids[1],))
        db.commit()
        db.close()
        self.assertEqual(t.verificar(), (False, ids[1]))

    def test_segredo_errado_nao_confere(self):
        self.a.trilha.registrar("aviso", resultado="x")
        outro = Autonomia(self.caminho, segredo=b"outro", relogio=self.relogio, fuso=FUSO)
        self.abertos.append(outro)
        self.assertFalse(outro.trilha.verificar()[0])
        with self.assertRaises(ValueError):
            Autonomia(self.caminho, segredo=b"", relogio=self.relogio, fuso=FUSO)

    def test_listar_filtros_e_resultado_cortado(self):
        t = self.a.trilha
        t.registrar("execucao", objetivo_id=None, resultado="x" * 900)
        self.relogio.avancar(10)
        t.registrar("falha", resultado="y")
        linhas = t.listar()
        self.assertEqual(len(linhas[0]["resultado"]), 500)
        self.assertEqual([l["tipo"] for l in t.listar(tipos=["falha"])], ["falha"])
        self.assertEqual(len(t.listar(desde=self.relogio() - 1)), 1)
        self.assertEqual(len(t.listar(limite=1)), 1)

    def test_marcar_desfeito(self):
        t = self.a.trilha
        i = t.registrar("execucao", acao="esquecer_fato", alvo="tratamento",
                        desfazer={"acao": "lembrar_fato", "args": {"chave": "tratamento", "valor": "senhor"}})
        self.assertEqual(t.listar()[0]["desfazer"]["acao"], "lembrar_fato")
        self.assertTrue(t.marcar_desfeito(i))
        self.assertFalse(t.marcar_desfeito(i))
        self.assertIsNotNone(t.listar()[0]["desfeito_em"])
        self.assertEqual(t.listar(tipos=["desfazer"])[0]["acao"], "esquecer_fato")
        self.assertEqual(t.verificar(), (True, None))

    def test_resumo_do_dia(self):
        i = self.a.objetivos.criar("Frete")
        self.executar(i, "pesquisar", {"q": 1}, custo=0.02)
        self.executar(i, "ler_pagina", {"url": "x"}, estado="falhou")
        self.a.aprovacoes.pedir("enviar_whatsapp", "Henrique", {"contato": "Henrique"})
        self.relogio.agora = epoch("2026-10-18T09:00:00")
        self.a.trilha.registrar("aviso", resultado="outro dia")
        resumo = self.a.trilha.resumo_do_dia("2026-10-17")
        self.assertEqual(resumo["contagens"]["execucao"], 1)
        self.assertEqual(resumo["contagens"]["falha"], 1)
        self.assertEqual(resumo["contagens"]["pedido"], 1)
        self.assertEqual(resumo["contagens"]["aviso"], 0)
        self.assertEqual(resumo["feito"][0]["acao"], "pesquisar")
        self.assertAlmostEqual(resumo["custo_usd"], 0.02)
        self.assertEqual(self.a.trilha.resumo_do_dia()["contagens"]["aviso"], 1)

    def test_segredo_do_arquivo(self):
        caminho = Path(self.pasta.name) / "cfg" / "autonomia.segredo"
        primeiro = segredo_do_arquivo(caminho)
        self.assertEqual(segredo_do_arquivo(caminho), primeiro)
        self.assertEqual(caminho.stat().st_mode & 0o777, 0o600)


class TestFeedback(Base):
    def test_peso_e_desfazer(self):
        f = self.a.feedback
        self.assertEqual(f.peso("hardware:cpu_celsius"), 1.0)
        eventos = [f.registrar("hardware:cpu_celsius", "nao_precisava") for _ in range(3)]
        self.assertAlmostEqual(f.peso("hardware:cpu_celsius"), 0.55)
        for _ in range(10):
            f.registrar("hardware:cpu_celsius", "nao_precisava")
        self.assertEqual(f.peso("hardware:cpu_celsius"), 0.2)
        for _ in range(20):
            f.registrar("objetivo_concluido", "util")
        self.assertEqual(f.peso("objetivo_concluido"), 1.5)
        f.registrar("acompanhamento", "mais_tarde")
        self.assertEqual(f.peso("acompanhamento"), 1.0)
        self.assertTrue(f.desfazer_feedback(eventos[0]))
        self.assertFalse(f.desfazer_feedback(eventos[0]))
        self.assertFalse(f.desfazer_feedback(99999))
        self.assertEqual(f.contadores("hardware:cpu_celsius")["nao_precisava"], 12)
        self.assertIsNotNone(f.historico("hardware:cpu_celsius")[-1]["desfeito_em"])
        with self.assertRaises(ValueError):
            f.registrar("x", "talvez")


if __name__ == "__main__":
    unittest.main()
