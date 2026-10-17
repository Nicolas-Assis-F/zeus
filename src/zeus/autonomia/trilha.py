"""Trilha de ações: o registro de tudo o que a autonomia pediu, fez ou deixou de fazer.

É daqui que sai o "o que eu fiz hoje" e é aqui que Nicolas confere, depois,
se o Zeus agiu sozinho onde não devia. Por isso a trilha é encadeada: cada
linha guarda o hash da anterior e o próprio, calculado com HMAC-SHA256 e um
segredo que mora fora do banco. Quem editar uma linha direto no SQLite não
consegue refazer a cadeia sem o segredo, e `verificar` aponta a primeira
linha quebrada.

Diferenças em relação ao `security/audit.py` do OpenJarvis, de onde veio a
ideia da cadeia: lá a linha com hash vazio era pulada na verificação (bastava
zerar o hash para esconder a edição) e o hash era SHA-256 puro, que qualquer
um recalcula. Aqui hash vazio é falha e o hash exige o segredo.

`desfeito_em` fica fora do hash de propósito: é o único campo que muda depois
de gravado. Para não virar porta de adulteração, `marcar_desfeito` também
acrescenta uma linha `desfazer` encadeada; a verdade sobre o desfazer é essa
linha, a coluna é atalho de consulta.

Limite conhecido: apagar as últimas linhas não quebra a cadeia que sobra.
Quem precisar disso guarda o último `row_hash` em outro lugar e compara.

Partes adaptadas de OpenJarvis, commit 091068cb, arquivos
src/openjarvis/security/audit.py, Apache-2.0; modificado.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path

from .banco import cortar, json_canonico, limites_do_dia

TIPOS = ("pedido", "aprovacao", "negacao", "expiracao", "execucao", "falha",
         "desfazer", "taint", "laco", "objetivo", "aviso")

# Ordem fixa dos campos que entram no hash. Mudar esta lista invalida a
# verificação de todas as trilhas gravadas antes.
CAMPOS_DO_HASH = ("ts", "tipo", "objetivo_id", "acao", "alvo", "resultado",
                  "custo_usd", "nivel", "desfazer_json")

ARQUIVO_DO_SEGREDO = Path("~/.config/zeus/autonomia.segredo")


def segredo_do_arquivo(caminho=None) -> bytes:
    """Lê o segredo da trilha; cria um de 32 bytes, com permissão 600, se faltar."""
    caminho = Path(caminho or ARQUIVO_DO_SEGREDO).expanduser()
    try:
        dado = caminho.read_bytes().strip()
        if dado:
            return dado
    except FileNotFoundError:
        pass
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dado = os.urandom(32).hex().encode("ascii")
    descritor = os.open(str(caminho), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descritor, "wb") as saida:
        saida.write(dado)
    return dado


class Trilha:
    def __init__(self, banco, segredo):
        if isinstance(segredo, str):
            segredo = segredo.encode("utf-8")
        if not segredo:
            # Sem segredo, o HMAC vira hash público e a cadeia não protege nada.
            raise ValueError("A trilha precisa de um segredo não vazio.")
        self.banco = banco
        self._segredo = bytes(segredo)

    def _hash(self, prev_hash, campos) -> str:
        carga = prev_hash + "|" + json_canonico([campos[c] for c in CAMPOS_DO_HASH])
        return hmac.new(self._segredo, carga.encode("utf-8"), hashlib.sha256).hexdigest()

    def registrar(self, tipo, objetivo_id=None, acao=None, alvo=None, resultado=None,
                  custo_usd=0.0, nivel=None, desfazer=None, ts=None) -> int:
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de trilha desconhecido: {tipo}")
        campos = {
            "ts": float(self.banco.agora() if ts is None else ts),
            "tipo": tipo,
            "objetivo_id": int(objetivo_id) if objetivo_id is not None else None,
            "acao": acao,
            "alvo": cortar(alvo),
            "resultado": cortar(resultado),
            "custo_usd": float(custo_usd or 0.0),
            "nivel": int(nivel) if nivel is not None else None,
            "desfazer_json": json_canonico(desfazer) if desfazer is not None else None,
        }
        with self.banco.transacao() as db:
            ultima = db.execute("SELECT row_hash FROM trilha ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = ultima[0] if ultima else ""
            row_hash = self._hash(prev_hash, campos)
            return db.execute(
                "INSERT INTO trilha (ts,tipo,objetivo_id,acao,alvo,resultado,custo_usd,nivel,"
                "desfazer_json,prev_hash,row_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*[campos[c] for c in CAMPOS_DO_HASH], prev_hash, row_hash)).lastrowid

    def listar(self, desde=None, ate=None, objetivo_id=None, tipos=None, limite=200) -> list:
        condicoes, parametros = [], []
        if desde is not None:
            condicoes.append("ts >= ?")
            parametros.append(float(desde))
        if ate is not None:
            condicoes.append("ts < ?")
            parametros.append(float(ate))
        if objetivo_id is not None:
            condicoes.append("objetivo_id = ?")
            parametros.append(int(objetivo_id))
        if tipos:
            tipos = list(tipos)
            condicoes.append(f"tipo IN ({','.join('?' for _ in tipos)})")
            parametros.extend(tipos)
        onde = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
        linhas = self.banco.ler(f"SELECT * FROM trilha {onde} ORDER BY id LIMIT ?",
                                (*parametros, int(limite)))
        for linha in linhas:
            linha["desfazer"] = json.loads(linha["desfazer_json"]) if linha["desfazer_json"] else None
        return linhas

    def verificar(self) -> tuple:
        """(True, None) se a cadeia inteira confere; senão (False, id da primeira quebra)."""
        esperado = ""
        with self.banco._trava:
            cursor = self.banco.conexao.execute(
                "SELECT id,prev_hash,row_hash," + ",".join(CAMPOS_DO_HASH) + " FROM trilha ORDER BY id")
            for linha in cursor:
                linha = dict(linha)
                if not linha["row_hash"] or linha["prev_hash"] != esperado:
                    return False, linha["id"]
                calculado = self._hash(linha["prev_hash"], linha)
                if not hmac.compare_digest(calculado, linha["row_hash"]):
                    return False, linha["id"]
                esperado = linha["row_hash"]
        return True, None

    def marcar_desfeito(self, id_trilha, resultado="desfeito") -> bool:
        """Marca a ação como desfeita e registra o desfazer como linha nova da cadeia."""
        with self.banco.transacao() as db:
            linha = db.execute("SELECT * FROM trilha WHERE id=?", (int(id_trilha),)).fetchone()
            if not linha or linha["desfeito_em"] is not None:
                return False
            agora = self.banco.agora()
            db.execute("UPDATE trilha SET desfeito_em=? WHERE id=? AND desfeito_em IS NULL",
                       (agora, int(id_trilha)))
            self.registrar("desfazer", objetivo_id=linha["objetivo_id"], acao=linha["acao"],
                           alvo=linha["alvo"], resultado=f"linha {id_trilha}: {resultado}",
                           ts=agora)
            return True

    def resumo_do_dia(self, dia=None) -> dict:
        """Contagens e listas para "o que eu fiz hoje". `dia` é data local (ISO ou date)."""
        dia = dia or self.banco.dia()
        inicio, fim = limites_do_dia(dia, self.banco.fuso)
        linhas = self.listar(desde=inicio, ate=fim, limite=100000)
        contagens = {tipo: 0 for tipo in TIPOS}
        for linha in linhas:
            contagens[linha["tipo"]] = contagens.get(linha["tipo"], 0) + 1

        def de(*tipos):
            return [{"id": l["id"], "ts": l["ts"], "objetivo_id": l["objetivo_id"],
                     "acao": l["acao"], "alvo": l["alvo"], "resultado": l["resultado"],
                     "desfeito": l["desfeito_em"] is not None}
                    for l in linhas if l["tipo"] in tipos]

        return {
            "dia": str(dia),
            "contagens": contagens,
            "feito": de("execucao"),
            "falhas": de("falha"),
            "pedidos": de("pedido"),
            "decisoes": de("aprovacao", "negacao", "expiracao"),
            "bloqueios": de("laco"),
            "objetivos": de("objetivo"),
            "custo_usd": round(sum(l["custo_usd"] for l in linhas), 6),
        }
