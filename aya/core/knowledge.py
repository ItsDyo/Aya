from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from aya.core.ingestion import FileIngestor
from aya.core.rag import RAGEngine
from aya.data.database import Database


class KnowledgeService:
    """Operacoes do banco de conhecimento e RAG local."""

    def __init__(
        self,
        db: Database,
        rag: RAGEngine,
        ingestor: FileIngestor,
        term_extractor: Callable[[str], list[str]],
    ):
        self.db = db
        self.rag = rag
        self.ingestor = ingestor
        self.term_extractor = term_extractor

    def salvar_conhecimento(self, topico: str, conteudo: str, tags: str = "") -> str:
        topico = (topico or "").strip()
        conteudo = (conteudo or "").strip()
        tags = (tags or "").strip()
        if not topico or not conteudo:
            return "Para salvar, use um tópico e um conteúdo. Ex: `/salvar Python | Listas guardam vários valores`."

        item_id = self.db.salvar_conhecimento(topico, conteudo, tags)
        self.rag.indexar_conhecimento(item_id)
        return f"Salvei no banco de conhecimento com ID {item_id}: {topico}."

    def buscar_conhecimento(self, termo: str) -> str:
        itens = self.db.buscar_conhecimento(termo, limite=8)
        if not itens:
            return "Não encontrei nada no banco de conhecimento para essa busca."
        linhas = ["Conhecimentos encontrados:"]
        for item in itens:
            resumo = item["conteudo"].replace("\n", " ").strip()
            if len(resumo) > 180:
                resumo = resumo[:177] + "..."
            linhas.append(f"- #{item['id']} {item['topico']}: {resumo}")
        return "\n".join(linhas)

    def contexto_relevante(self, mensagem_usuario: str) -> str:
        encontrados = []
        vistos = set()
        for termo in self.term_extractor(mensagem_usuario):
            for item in self.db.buscar_conhecimento(termo, limite=3):
                if item["id"] in vistos:
                    continue
                vistos.add(item["id"])
                encontrados.append(item)

        if not encontrados:
            return ""

        linhas = ["Conhecimentos mais relacionados à mensagem atual:"]
        for item in encontrados[:5]:
            conteudo = item["conteudo"].replace("\n", " ").strip()
            if len(conteudo) > 500:
                conteudo = conteudo[:497] + "..."
            linhas.append(f"- {item['topico']}: {conteudo}")
        return "\n".join(linhas)

    def consultar_rag(self, texto: str) -> str:
        consulta = texto.strip()
        if not consulta:
            return "Use assim: `/rag sua consulta`."
        contexto = self.rag.formatar_contexto(consulta, limite=10)
        return contexto or "Não encontrei contexto local relevante para essa consulta."

    def ingerir(self, texto: str) -> str:
        caminho = (texto or "").strip() or "."
        try:
            chunks = self.ingestor.ingest_path(caminho)
        except ValueError:
            return "Nao posso ingerir arquivos fora da raiz do projeto."
        except FileNotFoundError:
            return "Caminho nao encontrado para ingestao."

        if not chunks:
            return "Nao encontrei arquivos de texto suportados para ingerir."

        por_fonte = defaultdict(list)
        for chunk in chunks:
            por_fonte[chunk.source_path].append(
                (chunk.title, chunk.content, "arquivo,ingestao,rag", "arquivo")
            )
        paths = sorted(por_fonte)
        ids_salvos = []
        for source_path, itens in por_fonte.items():
            ids_salvos.extend(self.db.substituir_conhecimentos_de_fonte(source_path, itens))
        salvos = len(ids_salvos)

        self.db.reconstruir_fts_conhecimento()
        if self.rag.embeddings.enabled:
            self.rag.embeddings.index_all()
        self.db.registrar_evento_aprendizado(
            "ingestao_arquivos",
            f"{len(paths)} arquivo(s), {salvos} trecho(s) ingeridos de {caminho}",
            metadata=",".join(paths[:20]),
        )
        return f"Ingestao concluida: {len(paths)} arquivo(s), {salvos} trecho(s) salvos para RAG."

    def listar_fontes(self, texto: str) -> str:
        consulta = (texto or "").strip()
        if not consulta:
            return "Use assim: `/fontes termo`."
        return self.rag.formatar_fontes(consulta, limite=10)

    def reindexar_rag(self, force: bool = False) -> str:
        self.db.reconstruir_fts_conhecimento()
        semantico = self.rag.reindexar_embeddings(force=force)
        return f"Indice lexical reconstruido. {semantico}"

    def status_rag(self) -> str:
        return (
            "Status do RAG local:\n"
            f"- Conhecimentos: {self.db.contar_conhecimentos()}\n"
            f"- {self.rag.status()}"
        )
