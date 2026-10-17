"""Feedback de Nicolas sobre os avisos que o Zeus deu por conta própria.

Cada aviso proativo tem uma chave canônica ('hardware:cpu_celsius',
'objetivo_concluido', 'acompanhamento'). Quando Nicolas diz que foi útil, que
não precisava ou que era para mais tarde, o contador da chave sobe. `peso`
transforma os contadores num multiplicador que a política de interrupção
(#8) aplica à nota do aviso: o que ele acha inútil passa a interromper menos,
mas nunca some (o piso é 0,2), porque um aviso de disco cheio que ele dispensou
três vezes ainda pode ser o que salva o dia.

Todo feedback é um evento no histórico e pode ser desfeito: um toque errado
no botão não ensina nada de errado para sempre. A ideia dos contadores de
sim/não vem do `permission_memory` do OpenJarvis; o código é próprio.
"""

TIPOS = ("util", "nao_precisava", "mais_tarde")
PESO_MINIMO = 0.2
PESO_MAXIMO = 1.5


class Feedback:
    def __init__(self, banco):
        self.banco = banco

    def registrar(self, chave_do_aviso, tipo, canal=None) -> int:
        """Soma um feedback e devolve o id do evento (para desfazer)."""
        if tipo not in TIPOS:
            raise ValueError(f"Feedback desconhecido: {tipo}")
        if not str(chave_do_aviso).strip():
            raise ValueError("Feedback precisa da chave do aviso.")
        agora = self.banco.agora()
        with self.banco.transacao() as db:
            db.execute("INSERT INTO feedback (chave_do_aviso, atualizado) VALUES (?, ?) "
                       "ON CONFLICT(chave_do_aviso) DO NOTHING", (chave_do_aviso, agora))
            db.execute(f"UPDATE feedback SET {tipo}={tipo}+1, atualizado=? WHERE chave_do_aviso=?",
                       (agora, chave_do_aviso))
            return db.execute("INSERT INTO feedback_eventos (ts,chave_do_aviso,tipo,canal) "
                              "VALUES (?,?,?,?)", (agora, chave_do_aviso, tipo, canal)).lastrowid

    def desfazer_feedback(self, id_evento) -> bool:
        """Desconta o evento. Desfazer duas vezes não desconta duas."""
        agora = self.banco.agora()
        with self.banco.transacao() as db:
            evento = db.execute("SELECT * FROM feedback_eventos WHERE id=?", (int(id_evento),)).fetchone()
            if evento is None:
                return False
            if not db.execute("UPDATE feedback_eventos SET desfeito_em=? WHERE id=? AND desfeito_em IS NULL",
                              (agora, int(id_evento))).rowcount:
                return False
            tipo = evento["tipo"]
            db.execute(f"UPDATE feedback SET {tipo}=MAX(0, {tipo}-1), atualizado=? WHERE chave_do_aviso=?",
                       (agora, evento["chave_do_aviso"]))
            return True

    def contadores(self, chave_do_aviso) -> dict:
        linha = self.banco.ler_um("SELECT util, nao_precisava, mais_tarde FROM feedback "
                                  "WHERE chave_do_aviso=?", (chave_do_aviso,))
        return linha or {"util": 0, "nao_precisava": 0, "mais_tarde": 0}

    def historico(self, chave_do_aviso=None, limite=100) -> list:
        if chave_do_aviso:
            return self.banco.ler("SELECT * FROM feedback_eventos WHERE chave_do_aviso=? "
                                  "ORDER BY id DESC LIMIT ?", (chave_do_aviso, int(limite)))
        return self.banco.ler("SELECT * FROM feedback_eventos ORDER BY id DESC LIMIT ?", (int(limite),))

    def peso(self, chave_do_aviso) -> float:
        """Multiplicador em [0,2; 1,5]: 1 + 0,1·útil − 0,15·não precisava.

        "Mais tarde" não mexe no peso: diz que a hora era ruim, não que o
        assunto não importa. Quem usa esse contador é a escolha do momento.
        """
        c = self.contadores(chave_do_aviso)
        bruto = 1.0 + 0.1 * c["util"] - 0.15 * c["nao_precisava"]
        return round(min(PESO_MAXIMO, max(PESO_MINIMO, bruto)), 4)
