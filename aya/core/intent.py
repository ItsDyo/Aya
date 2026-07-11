from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Intent:
    name: str
    slots: dict[str, str | int]


class IntentRouter:
    """Detecta acoes comuns em linguagem natural sem depender do LLM."""

    def detect(self, message: str) -> Intent | None:
        text = (message or "").strip()
        lower = self._norm(text)
        if not text:
            return None

        return (
            self._painel(lower)
            or self._status(lower)
            or self._roadmap(lower)
            or self._release(lower)
            or self._continuidade(lower)
            or self._diagnostico(lower)
            or self._modelos(lower)
            or self._backup(lower)
            or self._autonomia(lower)
            or self._privacidade(lower)
            or self._auditar_projeto(lower)
            or self._projeto(lower)
            or self._plano_alteracao(text, lower)
            or self._revisar_arquivo(text, lower)
            or self._arquivo(text, lower)
            or self._codigo(text, lower)
            or self._refletir(lower)
            or self._aprendizados(lower)
            or self._higiene(lower)
            or self._confirmar_rascunho(lower)
            or self._aprovar_rejeitar(lower)
            or self._exercicio(text, lower)
            or self._responder_exercicio(text, lower)
            or self._revisoes(lower)
            or self._companhia(text, lower)
            or self._encerrar_sessao(text, lower)
            or self._iniciar_sessao(text, lower)
            or self._metas(lower)
            or self._dificuldade(text, lower)
            or self._meta(text, lower)
            or self._memoria(lower)
            or self._lembrar(text, lower)
            or self._salvar_conhecimento(text, lower)
            or self._ingerir(text, lower)
            or self._fontes(text, lower)
            or self._rag(text, lower)
            or self._buscar(text, lower)
        )

    def _norm(self, value: str) -> str:
        value = unicodedata.normalize("NFKD", value or "")
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return value.lower().strip()

    def _status(self, lower: str) -> Intent | None:
        if lower in {"status", "meu status", "como estou", "como esta meu progresso"}:
            return Intent("status", {})
        if "como estou indo" in lower or "meu progresso" in lower:
            return Intent("status", {})
        return None

    def _roadmap(self, lower: str) -> Intent | None:
        if lower in {"roadmap", "roadmap aya", "roadmap da aya", "plano da aya", "aya 1.0"}:
            return Intent("roadmap", {})
        if "versao 1.0" in lower or "aya 1.0" in lower:
            return Intent("roadmap", {})
        return None

    def _release(self, lower: str) -> Intent | None:
        if lower in {"release", "relatorio de release", "release da aya", "relatorio tecnico"}:
            return Intent("release", {"salvar": ""})
        if lower in {"executar release", "validar release", "rodar release", "release executar"}:
            return Intent("release", {"salvar": "executar"})
        if lower in {"listar releases", "historico de releases", "historico tecnico", "releases"}:
            return Intent("release", {"salvar": "listar"})
        if lower in {"ultimo release", "ultima release", "ultimo relatorio de release"}:
            return Intent("release", {"salvar": "ultimo"})
        if lower in {"comparar releases", "comparar release", "comparar relatorios de release"}:
            return Intent("release", {"salvar": "comparar"})
        if lower in {"salvar release", "gerar release", "salvar relatorio de release"}:
            return Intent("release", {"salvar": "salvar"})
        return None

    def _painel(self, lower: str) -> Intent | None:
        if lower in {"painel", "abrir painel", "painel da aya", "visao geral", "central da aya"}:
            return Intent("painel", {})
        if "mostre meu painel" in lower or "resumo rapido" in lower:
            return Intent("painel", {})
        return None

    def _continuidade(self, lower: str) -> Intent | None:
        if lower in {"continuidade", "resumo", "onde paramos", "onde parei", "o que esta pendente"}:
            return Intent("continuidade", {})
        if "resumo da aya" in lower or "o que fizemos" in lower or "proximos passos" in lower:
            return Intent("continuidade", {})
        return None

    def _diagnostico(self, lower: str) -> Intent | None:
        if lower in {"diagnostico", "rode diagnostico", "ver diagnostico", "status tecnico"}:
            return Intent("diagnostico", {})
        return None

    def _modelos(self, lower: str) -> Intent | None:
        if lower in {"modelos", "ver modelos", "quais modelos", "quais modelos voce usa"}:
            return Intent("modelos", {})
        return None

    def _backup(self, lower: str) -> Intent | None:
        if lower in {"backup", "backups", "ver backups", "listar backups"}:
            return Intent("backup", {"acao": "listar"})
        if lower in {"fazer backup", "criar backup", "gerar backup", "backup da aya", "faca backup da aya"}:
            return Intent("backup", {"acao": "criar"})
        if lower in {"verificar backup", "validar backup", "checar backup"}:
            return Intent("backup", {"acao": "verificar"})
        if lower in {"extrair backup", "restaurar backup", "recuperar backup"}:
            return Intent("backup", {"acao": "extrair"})
        return None

    def _autonomia(self, lower: str) -> Intent | None:
        if lower in {"autonomia", "ver autonomia", "estado da autonomia"}:
            return Intent("autonomia", {"acao": ""})
        if lower in {"ligar autonomia", "ative autonomia", "ativar autonomia"}:
            return Intent("autonomia", {"acao": "on"})
        if lower in {"desligar autonomia", "pausar autonomia", "desative autonomia"}:
            return Intent("autonomia", {"acao": "off"})
        if "refletir agora" in lower or "faca uma reflexao" in lower:
            return Intent("autonomia", {"acao": "refletir"})
        return None

    def _privacidade(self, lower: str) -> Intent | None:
        if lower in {"privacidade", "ver privacidade", "estado da privacidade"}:
            return Intent("privacidade", {"modo": ""})
        match = re.search(r"(?:privacidade|modo privacidade)\s+(leve|estrita|livre|normal|padrao|rigida|restrita)", lower)
        if match:
            return Intent("privacidade", {"modo": match.group(1)})
        return None

    def _projeto(self, lower: str) -> Intent | None:
        if "resuma o projeto" in lower or "analise o projeto" in lower or "mostre o projeto" in lower:
            return Intent("projeto", {})
        return None

    def _auditar_projeto(self, lower: str) -> Intent | None:
        patterns = (
            "audite o projeto",
            "auditar projeto",
            "diagnostico do projeto",
            "encontre problemas no projeto",
            "verifique o projeto",
            "analise riscos do projeto",
        )
        if any(pattern in lower for pattern in patterns):
            return Intent("auditar_projeto", {})
        return None

    def _arquivo(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:leia|abra|abre|mostre|analise)\s+(?:o\s+arquivo\s+)?([\w./\\ -]+\.(?:py|md|txt|json|toml|yaml|yml))", lower)
        if match:
            return Intent("arquivo", {"path": match.group(1).strip().replace("\\", "/")})
        return None

    def _revisar_arquivo(self, text: str, lower: str) -> Intent | None:
        match = re.search(
            r"(?:revise|revisa|faça review|faca review|analise com cuidado)\s+"
            r"(?:o\s+)?(?:arquivo\s+)?([\w./\\ -]+\.(?:py|md|txt|json|toml|yaml|yml))",
            lower,
        )
        if match:
            return Intent("revisar_arquivo", {"path": match.group(1).strip().replace("\\", "/")})
        return None

    def _plano_alteracao(self, text: str, lower: str) -> Intent | None:
        match = re.search(
            r"(?:crie um plano|planeje|plano de alteracao|planejar alteracao)\s+"
            r"(?:para\s+)?(?:alterar|mudar|refatorar|melhorar)?\s*"
            r"(?:o\s+)?(?:arquivo\s+)?([\w./\\ -]+\.(?:py|md|txt|json|toml|yaml|yml))"
            r"(?:\s+(?:para|sobre|com objetivo de|:|-)\s*(.*))?",
            lower,
        )
        if match:
            return Intent(
                "plano_alteracao",
                {
                    "path": match.group(1).strip().replace("\\", "/"),
                    "objetivo": (match.group(2) or "").strip(),
                },
            )
        return None

    def _codigo(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:me ajude com codigo|ajude com codigo|corrija esse codigo|analise esse codigo)\s*[:\-]?\s*(.*)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            payload = match.group(1).strip() or text
            return Intent("codigo", {"conteudo": payload})
        return None

    def _refletir(self, lower: str) -> Intent | None:
        if "reflita" in lower or "gere uma reflexao" in lower or "atualize sua memoria" in lower:
            return Intent("refletir", {})
        return None

    def _aprendizados(self, lower: str) -> Intent | None:
        if lower in {"aprendizados", "aprendizados pendentes", "ver aprendizados", "o que voce aprendeu"}:
            return Intent("aprendizados", {})
        if "aprendizados pendentes" in lower:
            return Intent("aprendizados", {})
        return None

    def _higiene(self, lower: str) -> Intent | None:
        patterns = {
            "higiene",
            "higiene da memoria",
            "limpeza da memoria",
            "auditar memoria",
            "audite a memoria",
            "verificar memoria",
            "verifique a memoria",
        }
        if lower in patterns:
            return Intent("higiene", {})
        if "memorias duplicadas" in lower or "memorias conflitantes" in lower:
            return Intent("higiene", {})
        return None

    def _confirmar_rascunho(self, lower: str) -> Intent | None:
        rejeitar = {
            "nao salva",
            "nao guarde",
            "nao guarda",
            "descarta isso",
            "pode descartar",
            "rejeita isso",
            "esquece isso",
        }
        if lower in rejeitar:
            return Intent("rejeitar_rascunho", {})

        match = re.search(r"(?:pode\s+)?(?:guarda|guardar|salva|salvar|memoriza|memorizar)(?:\s+isso)?(?:\s+como\s+(\w+))?$", lower)
        if match:
            return Intent("confirmar_rascunho", {"dominio": match.group(1) or ""})
        if lower in {"pode guardar", "pode salvar", "guarda isso", "salva isso", "sim pode guardar"}:
            return Intent("confirmar_rascunho", {"dominio": ""})
        return None

    def _aprovar_rejeitar(self, lower: str) -> Intent | None:
        match = re.search(r"\b(aprovar|aprove|rejeitar|rejeite)\s+(?:aprendizado\s+)?#?(\d+)\b", lower)
        if not match:
            return None
        name = "aprovar_aprendizado" if match.group(1) in {"aprovar", "aprove"} else "rejeitar_aprendizado"
        return Intent(name, {"id": int(match.group(2))})

    def _exercicio(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:crie|gere|faca|me passe)\s+(?:um\s+)?exercicio\s+(?:sobre|de|para)\s+(.+)", lower)
        if match:
            topico = match.group(1).strip(" .")
            nivel = "medio"
            nivel_match = re.search(r"\b(facil|medio|dificil)\b", topico)
            if nivel_match:
                nivel = nivel_match.group(1)
                topico = re.sub(r"\b(facil|medio|dificil)\b", "", topico).strip(" .")
            return Intent("exercicio", {"topico": topico, "nivel": nivel})
        return None

    def _responder_exercicio(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:responder|corrigir)\s+(?:exercicio\s+)?#?(\d+)\s*(?:[:|-]|\|)\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return Intent("responder_exercicio", {"id": int(match.group(1)), "resposta": match.group(2).strip()})
        return None

    def _revisoes(self, lower: str) -> Intent | None:
        if lower in {"revisoes", "minhas revisoes", "o que revisar", "quero revisar", "ver revisoes"}:
            return Intent("revisoes", {})
        if "tenho revisoes" in lower:
            return Intent("revisoes", {})
        return None

    def _companhia(self, text: str, lower: str) -> Intent | None:
        if lower in {"preciso conversar", "quero conversar", "fica comigo", "modo companhia"}:
            return Intent("companhia", {"mensagem": text})
        patterns = [
            r"(?:preciso|quero)\s+(?:desabafar|conversar)\s*(.*)",
            r"(?:me da|quero)\s+(?:um\s+)?(?:conselho|incentivo)\s*(.*)",
            r"(?:estou|to)\s+(?:triste|frustrado|frustrada|cansado|cansada|desanimado|desanimada|sozinho|sozinha).+",
        ]
        for pattern in patterns:
            if re.search(pattern, lower):
                return Intent("companhia", {"mensagem": text})
        return None

    def _iniciar_sessao(self, text: str, lower: str) -> Intent | None:
        patterns = [
            r"(?:vou estudar|quero estudar|comecar estudar|iniciar estudo de)\s+(.+?)\s+(?:por|durante)\s+(\d{1,3})\s*(?:min|minutos)?",
            r"(?:estudar)\s+(.+?)\s+(\d{1,3})\s*(?:min|minutos)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                return Intent("iniciar_sessao", {"materia": match.group(1).strip(" ."), "minutos": int(match.group(2))})

        match = re.search(r"(?:vou estudar|quero estudar|comecar estudar|iniciar estudo de)\s+(.+)", lower)
        if match:
            return Intent("iniciar_sessao", {"materia": match.group(1).strip(" ."), "minutos": 25})
        return None

    def _encerrar_sessao(self, text: str, lower: str) -> Intent | None:
        if any(x in lower for x in ["terminei de estudar", "encerrar sessao", "finalizar sessao", "parei de estudar"]):
            notas = re.sub(r"^(terminei de estudar|encerrar sessao|finalizar sessao|parei de estudar)", "", lower).strip(" .:-")
            return Intent("encerrar_sessao", {"notas": notas})
        return None

    def _metas(self, lower: str) -> Intent | None:
        if lower in {"metas", "minhas metas", "ver metas", "listar metas"}:
            return Intent("metas", {})
        return None

    def _meta(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:crie|criar|adicione|defina)\s+(?:uma\s+)?meta\s+(?:(diaria|semanal|mensal|geral)\s+)?(?:de\s+|para\s+)?(.+)", lower)
        if match:
            return Intent("meta", {"tipo": match.group(1) or "geral", "descricao": match.group(2).strip(" .")})
        return None

    def _dificuldade(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:tenho dificuldade|estou com dificuldade|estou travado|travei)\s+(?:em|com|no|na)?\s*(.+)", lower)
        if match:
            topico = match.group(1).strip(" .")
            return Intent("dificuldade", {"materia": "geral", "topico": topico, "descricao": text})
        return None

    def _memoria(self, lower: str) -> Intent | None:
        if lower in {"memoria", "minha memoria", "ver memoria", "o que voce lembra"}:
            return Intent("memoria", {})
        return None

    def _lembrar(self, text: str, lower: str) -> Intent | None:
        patterns = [
            r"(?:lembre que|guarde que|memorize que)\s+(.+)",
            r"(?:quero que voce lembre que)\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                valor = match.group(1).strip(" .")
                return Intent("lembrar", {"tipo": "memoria", "chave": self._infer_key(valor), "valor": valor})
        return None

    def _salvar_conhecimento(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:salve|guardar|guarde|registre)\s+(?:no banco de conhecimento\s+)?(.+?)\s*(?:[:|-]| como )\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match and len(match.group(2).strip()) > 8:
            return Intent("salvar_conhecimento", {
                "topico": match.group(1).strip(),
                "conteudo": match.group(2).strip(),
                "tags": "auto",
            })
        return None

    def _ingerir(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:ingira|ingerir|indexe|aprenda com)\s+(?:o\s+)?(?:arquivo|pasta|diretorio)?\s*([\w./\\-]+)?", lower)
        if match and match.group(1):
            return Intent("ingerir", {"path": match.group(1).strip()})
        if lower in {"ingira o projeto", "indexe o projeto", "aprenda com o projeto"}:
            return Intent("ingerir", {"path": "."})
        return None

    def _fontes(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:mostre|quais|ver)\s+(?:as\s+)?fontes\s+(?:sobre|de|para)?\s*(.+)", lower)
        if match:
            return Intent("fontes", {"termo": match.group(1).strip(" .")})
        return None

    def _rag(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:use|consulte|buscar contexto|contexto)\s+(?:o\s+)?rag\s*(?:sobre|de|para)?\s*(.+)", lower)
        if match:
            return Intent("rag", {"termo": match.group(1).strip(" .")})
        return None

    def _buscar(self, text: str, lower: str) -> Intent | None:
        match = re.search(r"(?:busque|procure|pesquise)\s+(?:na memoria|no conhecimento|no banco)?\s*(.+)", lower)
        if match:
            return Intent("buscar", {"termo": match.group(1).strip(" .")})
        return None

    def _infer_key(self, value: str) -> str:
        if "nome" in value or "chamo" in value:
            return "nome"
        if "objetivo" in value or "quero" in value:
            return "objetivo"
        if "prefiro" in value:
            return "preferencia"
        if "dificuldade" in value:
            return "dificuldade"
        words = re.findall(r"\b\w{4,}\b", value.lower())
        return "_".join(words[:3]) if words else "memoria"
