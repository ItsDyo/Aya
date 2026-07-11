from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from aya.data.database import Database


class CurationService:
    """Cuida da revisao manual de memorias e aprendizados pendentes."""

    DEFAULT_ADIAR_DIAS = 7

    def __init__(self, db: Database):
        self.db = db

    def listar_aprendizados(self, texto: str) -> str:
        limite = self._extrair_limite(texto, padrao=20)
        itens = self.db.listar_aprendizados_pendentes(limite=limite)
        if not itens:
            return "Nao ha aprendizados pendentes agora."

        linhas = ["Aprendizados pendentes:"]
        for item in itens:
            valor = self._resumir(item["valor"])
            linhas.append(
                f"- #{item['id']} [{item['categoria']}/{item['tipo'] or 'geral'}] "
                f"{item['chave']} = {valor} (confianca {item['confianca']:.2f})"
            )
        linhas.append("\nUse `/aprovar id` ou `/rejeitar id`.")
        return "\n".join(linhas)

    def listar_curadoria(self, texto: str) -> str:
        limite = self._extrair_limite(texto, padrao=10)
        resumo = self.resumo_higiene(limite=max(limite, 50))
        memorias = resumo["memorias_fracas"][:limite]
        aprendizados = self.db.listar_aprendizados_pendentes(limite=limite)
        conflitos = self.db.listar_conflitos_memoria(limite=limite)
        if not memorias and not aprendizados and not conflitos:
            return "Curadoria limpa: nao ha memorias fracas nem aprendizados pendentes agora."

        linhas = ["Curadoria da memoria da Aya:"]
        if memorias:
            linhas.append("")
            linhas.append("Memorias para revisar:")
            for item in memorias:
                linhas.extend(self._formatar_memoria_curadoria(item, conflitos_pendentes=conflitos))

        if aprendizados:
            linhas.append("")
            linhas.append("Aprendizados pendentes:")
            for item in aprendizados:
                valor = self._resumir(item["valor"])
                linhas.append(
                    f"- Aprendizado #{item['id']} [{item['categoria']}/{item['tipo'] or 'geral'}] "
                    f"{item['chave']} = {valor} (confianca {item['confianca']:.2f})"
                )

        if conflitos:
            linhas.append("")
            linhas.extend(self._formatar_conflitos_pendentes(conflitos))

        linhas.append("")
        linhas.append(
            "Use `/confirmar memoria id`, `/editar memoria id | novo valor`, "
            "`/dominio memoria id | dominio`, `/arquivar memoria id`, `/restaurar memoria id`, "
            "`/adiar memoria id`, `/ignorar memoria id`, `/aprovar id`, `/rejeitar id` "
            "ou `/resolver conflito id aceitar|rejeitar`."
        )
        return "\n".join(linhas)

    def higiene_memoria(self, texto: str) -> str:
        limite = self._extrair_limite(texto, padrao=200)
        resumo = self.resumo_higiene(limite=limite)
        if resumo["total"] == 0 and resumo["conflitos_pendentes"] == 0:
            return "Higiene da memoria: nao ha memorias ativas para analisar."

        linhas = [
            "Higiene da memoria da Aya:",
            f"- Memorias analisadas: {resumo['total']}",
            f"- Possiveis duplicatas: {resumo['duplicatas']}",
            f"- Memorias semelhantes: {resumo['semelhantes']}",
            f"- Possiveis conflitos: {resumo['conflitos']}",
            f"- Conflitos pendentes de decisao: {resumo['conflitos_pendentes']}",
            f"- Memorias fracas/temporarias: {resumo['fracas']}",
            "",
        ]

        linhas.extend(self._formatar_grupos("Possiveis duplicatas", resumo["grupos_duplicados"]))
        linhas.extend(self._formatar_grupos("Memorias semelhantes - revisar antes de fundir", resumo["grupos_semelhantes"]))
        linhas.extend(self._formatar_grupos("Possiveis conflitos", resumo["grupos_conflitantes"]))
        linhas.extend(self._formatar_conflitos_pendentes(resumo["itens_conflitantes"]))
        linhas.extend(self._formatar_memorias_fracas(resumo["memorias_fracas"][:10]))

        linhas.append("Acoes seguras:")
        linhas.append("- Confirme memorias confiaveis com `/confirmar memoria id`.")
        linhas.append("- Arquive memorias ruins com `/esquecer memoria id`.")
        linhas.append("- Restaure memorias arquivadas com `/restaurar memoria id`.")
        linhas.append("- Altere dominio com `/dominio memoria id | estudo|trabalho|pessoal|programacao|aya|geral`.")
        linhas.append("- Resolva mudancas de valor com `/resolver conflito id aceitar|rejeitar`.")
        linhas.append("- Una duplicatas identicas com `/fundir memoria id_principal id_duplicada`.")
        linhas.append("- Use `/curadoria` para ver aprendizados pendentes junto com memorias fracas.")
        return "\n".join(linhas).strip()

    def resumo_higiene(self, limite: int = 200) -> dict:
        memorias = list(self.db.buscar_memorias(limite=limite))
        duplicatas = self._encontrar_duplicatas(memorias)
        semelhantes = self._encontrar_semelhantes(memorias, duplicatas)
        conflitos_detectados = self._encontrar_conflitos(memorias)
        conflitos_pendentes = list(self.db.listar_conflitos_memoria(limite=limite))
        fracas = []
        adiadas = []
        ignoradas = []
        for item in memorias:
            motivos = self._motivos_memoria_fraca(item, semelhantes, conflitos_detectados, conflitos_pendentes)
            if not motivos:
                continue
            estado = self._estado_revisao(item, motivos)
            if estado["status"] == "adiada":
                adiadas.append((item, motivos, estado))
                continue
            if estado["status"] == "ignorada":
                ignoradas.append((item, motivos, estado))
                continue
            fracas.append(item)
        total_conflitos = len(conflitos_detectados) + len(conflitos_pendentes)
        score = max(0, 100 - (len(duplicatas) * 15) - (total_conflitos * 20) - (len(fracas) * 5))
        precisa_revisao = bool(duplicatas or conflitos_detectados or conflitos_pendentes or fracas)
        return {
            "total": len(memorias),
            "duplicatas": len(duplicatas),
            "semelhantes": len(semelhantes),
            "conflitos": total_conflitos,
            "conflitos_pendentes": len(conflitos_pendentes),
            "fracas": len(fracas),
            "adiadas": len(adiadas),
            "ignoradas": len(ignoradas),
            "score": score,
            "precisa_revisao": precisa_revisao,
            "grupos_duplicados": duplicatas,
            "grupos_semelhantes": semelhantes,
            "grupos_conflitantes": conflitos_detectados,
            "itens_conflitantes": conflitos_pendentes,
            "memorias_fracas": fracas,
            "memorias_adiadas": adiadas,
            "memorias_ignoradas": ignoradas,
        }

    def confirmar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/confirmar memoria 3`."
        if not self.db.confirmar_memoria(memoria_id):
            return f"Nao encontrei memoria com ID {memoria_id}."
        self.db.registrar_evento_aprendizado("memoria_confirmada", f"memoria_id={memoria_id}")
        return f"Memoria #{memoria_id} confirmada. Vou tratar isso como informacao confiavel."

    def esquecer_memoria(self, texto: str) -> str:
        return self.arquivar_memoria(texto)

    def arquivar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/arquivar memoria 3`."
        if not self.db.arquivar_memoria(memoria_id):
            return f"Nao encontrei memoria com ID {memoria_id}."
        self.db.registrar_evento_aprendizado("memoria_arquivada", f"memoria_id={memoria_id}")
        return f"Memoria #{memoria_id} arquivada. Ela nao entra mais no contexto ativo da Aya."

    def restaurar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/restaurar memoria 3`."
        if not self.db.restaurar_memoria(memoria_id):
            return f"Nao encontrei memoria restauravel com ID {memoria_id}."
        self.db.registrar_evento_aprendizado("memoria_restaurada", f"memoria_id={memoria_id}")
        return f"Memoria #{memoria_id} restaurada como ativa."

    def editar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        _, _, novo_valor = (texto or "").partition("|")
        novo_valor = novo_valor.strip()
        if memoria_id is None or not novo_valor:
            return "Use assim: `/editar memoria 3 | novo valor`."
        if not self.db.atualizar_memoria_controlada(memoria_id, novo_valor):
            return f"Nao encontrei memoria editavel com ID {memoria_id}."
        self.db.registrar_evento_aprendizado("memoria_editada", f"memoria_id={memoria_id}")
        return f"Memoria #{memoria_id} editada com historico preservado."

    def alterar_dominio_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        _, _, dominio = (texto or "").partition("|")
        dominio = self._normalizar_dominio(dominio)
        if memoria_id is None:
            return "Use assim: `/dominio memoria 3 | estudo`."
        if not self.db.alterar_dominio_memoria(memoria_id, dominio):
            return f"Nao encontrei memoria com ID {memoria_id}."
        self.db.registrar_evento_aprendizado("memoria_dominio_alterado", f"memoria_id={memoria_id};dominio={dominio}")
        return f"Memoria #{memoria_id} movida para o dominio `{dominio}`."

    def adiar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/adiar memoria 3 | 7 dias`."
        dias = self._extrair_dias(texto, self.DEFAULT_ADIAR_DIAS)
        motivo = self._extrair_motivo_revisao(texto)
        agora = datetime.now()
        ate = agora + timedelta(days=dias)
        metadata = (
            "estado_anterior=pendente;estado_novo=adiada;"
            f"adiado_em={agora.isoformat()};adiado_ate={ate.isoformat()};"
            f"prazo_dias={dias};motivo={self._metadata_safe(motivo)}"
        )
        if not self.db.registrar_revisao_memoria(memoria_id, "revisao_adiada", metadata=metadata):
            return f"Nao encontrei memoria com ID {memoria_id}."
        return f"Revisao da memoria #{memoria_id} adiada ate {ate.date()}. Nenhum conteudo foi alterado."

    def ignorar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/ignorar memoria 3`."
        memoria = self.db.buscar_memoria_por_id(memoria_id)
        if not memoria:
            return f"Nao encontrei memoria com ID {memoria_id}."
        motivos = self._motivos_memoria_fraca(memoria)
        metadata = (
            "estado_anterior=pendente;estado_novo=ignorada;"
            f"ignorado_em={datetime.now().isoformat()};"
            f"memoria_atualizada_em={memoria['atualizado_em'] or ''};"
            f"motivos_hash={self._motivos_hash(motivos)};"
            f"motivos={self._metadata_safe('|'.join(motivos) or 'sem_motivo_atual')}"
        )
        if not self.db.registrar_revisao_memoria(memoria_id, "sugestao_ignorada", metadata=metadata):
            return f"Nao encontrei memoria com ID {memoria_id}."
        return f"Sugestao sobre a memoria #{memoria_id} ignorada por enquanto. Nenhum conteudo foi alterado."

    def retomar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/retomar memoria 3`."
        metadata = (
            "estado_anterior=adiada_ou_ignorada;estado_novo=pendente;"
            f"retomado_em={datetime.now().isoformat()}"
        )
        if not self.db.registrar_revisao_memoria(memoria_id, "revisao_retomada", metadata=metadata):
            return f"Nao encontrei memoria com ID {memoria_id}."
        return f"Memoria #{memoria_id} retomada para a curadoria normal."

    def revisar_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/revisar memoria 3`."
        memoria = self.db.buscar_memoria_por_id(memoria_id)
        if not memoria:
            return f"Nao encontrei memoria com ID {memoria_id}."
        motivos = self._motivos_memoria_fraca(memoria)
        estado = self._estado_revisao(memoria, motivos)
        linhas = self._formatar_memoria_curadoria(memoria)
        linhas.append(f"  estado de revisao: {estado['status']}")
        if estado.get("adiado_ate"):
            linhas.append(f"  adiada ate: {estado['adiado_ate']}")
        return "\n".join(linhas)

    def listar_memorias(self, texto: str) -> str:
        normalizado = self._normalizar(texto)
        dominios = {"pessoal", "estudo", "trabalho", "programacao", "aya", "geral"}
        dominio = next((item for item in dominios if item in normalizado), "")
        if "fraca" in normalizado:
            memorias = self.resumo_higiene()["memorias_fracas"]
            titulo = "Memorias fracas:"
        elif "adiada" in normalizado:
            return self.listar_memorias_adiadas()
        elif "ignorada" in normalizado:
            return self.listar_memorias_ignoradas()
        elif dominio:
            memorias = self.db.buscar_memorias_por_dominio(dominio, limite=50)
            titulo = f"Memorias do dominio {dominio}:"
        else:
            memorias = self.db.buscar_memorias(limite=50)
            titulo = "Memorias ativas:"
        if not memorias:
            return f"{titulo}\n- nada encontrado"
        linhas = [titulo]
        for item in memorias[:50]:
            linhas.append(self._linha_memoria_resumida(item))
        return "\n".join(linhas)

    def listar_memorias_adiadas(self) -> str:
        itens = self.resumo_higiene()["memorias_adiadas"]
        if not itens:
            return "Memorias adiadas:\n- nada encontrado"
        linhas = ["Memorias adiadas:"]
        for item, _motivos, estado in itens:
            linhas.append(
                f"- #{item['id']} [{self._dominio(item)}/{item['tipo']}] "
                f"adiada_em={estado.get('adiado_em', 'indisponivel')} "
                f"volta_em={estado.get('adiado_ate', 'indisponivel')} "
                f"motivo={estado.get('motivo', 'indisponivel')} "
                f"valor={self._resumir_seguro(item, 90)}"
            )
        return "\n".join(linhas)

    def listar_memorias_ignoradas(self) -> str:
        itens = self.resumo_higiene()["memorias_ignoradas"]
        if not itens:
            return "Memorias ignoradas:\n- nada encontrado"
        linhas = ["Memorias ignoradas:"]
        for item, motivos, estado in itens:
            linhas.append(
                f"- #{item['id']} [{self._dominio(item)}/{item['tipo']}] "
                f"ignorada_em={estado.get('ignorado_em', 'indisponivel')} "
                f"motivos={'; '.join(motivos) or 'indisponivel'} "
                f"valor={self._resumir_seguro(item, 90)}"
            )
        return "\n".join(linhas)

    def listar_conflitos(self, texto: str = "") -> str:
        limite = self._extrair_limite(texto, padrao=20)
        conflitos = self.db.listar_conflitos_memoria(limite=limite)
        if not conflitos:
            return "Nao ha conflitos de memoria pendentes."
        return "\n".join(self._formatar_conflitos_pendentes(conflitos)).strip()

    def resolver_conflito(self, texto: str) -> str:
        conflito_id = self._extrair_id(texto)
        if conflito_id is None:
            return "Use assim: `/resolver conflito 3 aceitar` ou `/resolver conflito 3 rejeitar`."
        normalizado = self._normalizar(texto)
        if any(palavra in normalizado for palavra in ("aceitar", "aplicar", "novo", "proposto")):
            aceitar = True
        elif any(palavra in normalizado for palavra in ("rejeitar", "manter", "atual", "recusar")):
            aceitar = False
        else:
            return "Escolha `aceitar` para usar o valor proposto ou `rejeitar` para manter o atual."
        if not self.db.resolver_conflito_memoria(conflito_id, aceitar):
            return f"Nao encontrei conflito pendente com ID {conflito_id}."
        acao = "Valor proposto aplicado" if aceitar else "Valor atual mantido"
        self.db.registrar_evento_aprendizado(
            "conflito_memoria_resolvido",
            f"conflito_id={conflito_id};aceitar={str(aceitar).lower()}",
        )
        return f"Conflito #{conflito_id} resolvido. {acao}. O historico foi preservado."

    def fundir_memorias(self, texto: str) -> str:
        ids = [int(value) for value in re.findall(r"\d+", texto or "")]
        if len(ids) < 2:
            return "Use assim: `/fundir memoria 2 5` (primeiro ID sera mantido)."
        sucesso, mensagem = self.db.fundir_memorias(ids[0], ids[1])
        if not sucesso:
            return mensagem
        self.db.registrar_evento_aprendizado(
            "memorias_fundidas",
            f"principal={ids[0]};fundida={ids[1]}",
        )
        return f"Memoria #{ids[1]} fundida na memoria #{ids[0]}. O registro antigo foi preservado."

    def historico_memoria(self, texto: str) -> str:
        memoria_id = self._extrair_id(texto)
        if memoria_id is None:
            return "Use assim: `/historico memoria 3`."
        memoria = self.db.buscar_memoria_por_id(memoria_id)
        if not memoria:
            return f"Nao encontrei memoria com ID {memoria_id}."
        historico = self.db.buscar_historico_memoria(memoria_id, limite=20)
        linhas = [
            f"Historico da memoria #{memoria_id} [{memoria['dominio']}/{memoria['tipo']}] {memoria['chave']}:",
            f"- Estado atual: {memoria['status']} | {self._resumir_seguro(memoria)}",
        ]
        for item in historico:
            linhas.append(
                f"- {item['criado_em']} [{item['acao']}] "
                f"{self._resumir_valor_seguro(item['valor_novo'], memoria['chave'], 100)} "
                f"(confianca {item['confianca']:.2f})"
            )
        return "\n".join(linhas)

    def aprovar_aprendizado(self, texto: str) -> str:
        aprendizado_id = self._extrair_id(texto)
        if aprendizado_id is None:
            return "Use assim: `/aprovar 3`."

        item = self.db.buscar_aprendizado_pendente(aprendizado_id)
        if not item or item["status"] != "pendente":
            return f"Nao encontrei aprendizado pendente com ID {aprendizado_id}."

        if item["categoria"] == "memoria":
            dominio = self._extrair_dominio_metadata(item["metadata"])
            resultado_memoria = self.db.salvar_memoria_avancada(
                item["tipo"] or "geral",
                item["chave"],
                item["valor"],
                origem=f"aprovado:{item['origem']}",
                confianca=max(float(item["confianca"]), 0.9),
                dominio=dominio,
            )
            destino_id = resultado_memoria.memory_id
            metadata = (
                f"aprendizado_id={aprendizado_id};memoria_id={destino_id};"
                f"acao={resultado_memoria.action};conflito_id={resultado_memoria.conflict_id or 0}"
            )
        else:
            destino_id = self.db.salvar_conhecimento(
                item["chave"],
                item["valor"],
                tags=item["tipo"] or "aprovado",
                fonte=item["origem"] or "curadoria",
            )
            metadata = f"aprendizado_id={aprendizado_id};conhecimento_id={destino_id}"

        self.db.atualizar_status_aprendizado(aprendizado_id, "aprovado")
        self.db.registrar_evento_aprendizado(
            "aprendizado_aprovado",
            f"{item['categoria']}:{item['chave']}",
            metadata=metadata,
        )
        if item["categoria"] == "memoria" and resultado_memoria.action == "conflict":
            return (
                f"Aprendizado #{aprendizado_id} aprovado, mas nao substitui a memoria atual. "
                f"Criei o conflito #{resultado_memoria.conflict_id} para sua decisao."
            )
        return f"Aprendizado #{aprendizado_id} aprovado e salvo em {item['categoria']}."

    def rejeitar_aprendizado(self, texto: str) -> str:
        aprendizado_id = self._extrair_id(texto)
        if aprendizado_id is None:
            return "Use assim: `/rejeitar 3`."
        if not self.db.atualizar_status_aprendizado(aprendizado_id, "rejeitado"):
            return f"Nao encontrei aprendizado pendente com ID {aprendizado_id}."
        self.db.registrar_evento_aprendizado("aprendizado_rejeitado", f"aprendizado_id={aprendizado_id}")
        return f"Aprendizado #{aprendizado_id} rejeitado."

    def confirmar_ultimo_rascunho(self, dominio: str = "") -> str:
        item = self._ultimo_aprendizado_pendente()
        if not item:
            return "Nao encontrei nenhum rascunho de memoria pendente para guardar."

        if dominio:
            metadata = self._trocar_dominio_metadata(item["metadata"], dominio)
            self.db.atualizar_metadata_aprendizado(item["id"], metadata)

        return self.aprovar_aprendizado(str(item["id"]))

    def rejeitar_ultimo_rascunho(self) -> str:
        item = self._ultimo_aprendizado_pendente()
        if not item:
            return "Nao encontrei nenhum rascunho de memoria pendente para rejeitar."
        return self.rejeitar_aprendizado(str(item["id"]))

    def _ultimo_aprendizado_pendente(self):
        itens = self.db.listar_aprendizados_pendentes(limite=1)
        return itens[0] if itens else None

    def _encontrar_duplicatas(self, memorias) -> list[list]:
        por_valor = defaultdict(list)
        for item in memorias:
            valor = self._normalizar(item["valor"])
            if len(valor) >= 6:
                por_valor[valor].append(item)
        return [grupo for grupo in por_valor.values() if len(grupo) > 1]

    def _encontrar_semelhantes(self, memorias, duplicatas=None) -> list[list]:
        duplicados_ids = {item["id"] for grupo in (duplicatas or []) for item in grupo}
        grupos = []
        usados = set()
        for i, item_a in enumerate(memorias):
            if item_a["id"] in duplicados_ids or item_a["id"] in usados:
                continue
            texto_a = self._normalizar(f"{item_a['tipo']} {item_a['chave']} {item_a['valor']}")
            for item_b in memorias[i + 1:]:
                if item_b["id"] in duplicados_ids or item_b["id"] in usados:
                    continue
                texto_b = self._normalizar(f"{item_b['tipo']} {item_b['chave']} {item_b['valor']}")
                if len(texto_a) < 12 or len(texto_b) < 12:
                    continue
                ratio = SequenceMatcher(None, texto_a, texto_b).ratio()
                same_key = self._normalizar(item_a["chave"]) == self._normalizar(item_b["chave"])
                if ratio >= 0.72 or (same_key and ratio >= 0.55):
                    grupos.append([item_a, item_b])
                    usados.update({item_a["id"], item_b["id"]})
                    break
        return grupos

    def _encontrar_conflitos(self, memorias) -> list[list]:
        por_chave = defaultdict(list)
        for item in memorias:
            chave = self._normalizar(item["chave"])
            if chave:
                por_chave[chave].append(item)

        conflitos = []
        for grupo in por_chave.values():
            valores = {self._normalizar(item["valor"]) for item in grupo}
            if len(grupo) < 2 or len(valores) < 2:
                continue
            if self._grupo_tem_valores_distantes(list(valores)):
                conflitos.append(grupo)
        return conflitos

    @staticmethod
    def _grupo_tem_valores_distantes(valores: list[str]) -> bool:
        for i, valor_a in enumerate(valores):
            for valor_b in valores[i + 1:]:
                if SequenceMatcher(None, valor_a, valor_b).ratio() < 0.75:
                    return True
        return False

    def _formatar_grupos(self, titulo: str, grupos: list[list]) -> list[str]:
        linhas = [f"{titulo}:"]
        if not grupos:
            linhas.append("- nada encontrado")
            linhas.append("")
            return linhas

        for grupo in grupos[:8]:
            partes = []
            for item in grupo[:4]:
                partes.append(
                    f"#{item['id']} [{self._dominio(item)}/{item['tipo']}] "
                    f"{item['chave']} = {self._resumir_seguro(item, 70)}"
                )
            linhas.append("- " + " | ".join(partes))
            if "semelhantes" in titulo.lower():
                linhas.append("  sugestao: revisar; use `/fundir` apenas se os valores forem identicos ou arquive uma delas.")
        linhas.append("")
        return linhas

    def _formatar_memorias_fracas(self, memorias) -> list[str]:
        linhas = ["Memorias fracas/temporarias:"]
        if not memorias:
            linhas.append("- nada encontrado")
            linhas.append("")
            return linhas

        for item in memorias:
            motivos = "; ".join(self._motivos_memoria_fraca(item)) or "motivo indisponivel"
            linhas.append(
                f"- #{item['id']} [{self._dominio(item)}/{item['tipo']}] {item['chave']} "
                f"(confianca {item['confianca']:.2f}) = {self._resumir_seguro(item, 90)} | motivo: {motivos}"
            )
        linhas.append("")
        return linhas

    def _formatar_conflitos_pendentes(self, conflitos) -> list[str]:
        linhas = ["Conflitos pendentes:"]
        if not conflitos:
            linhas.append("- nada encontrado")
            linhas.append("")
            return linhas
        for item in conflitos[:10]:
            linhas.append(
                f"- Conflito #{item['id']} na memoria #{item['memoria_id']} "
                f"[{item['dominio_proposto']}/{item['tipo']}] {item['chave']}: "
                f"atual = {self._resumir_valor_seguro(item['valor_atual'], item['chave'], 70)} | "
                f"proposto = {self._resumir_valor_seguro(item['valor_proposto'], item['chave'], 70)} "
                f"(confianca {item['confianca_proposta']:.2f}, repeticoes {item['reforco_count']})"
            )
        linhas.append("")
        return linhas

    @staticmethod
    def _normalizar(valor: str) -> str:
        normalized = unicodedata.normalize("NFKD", valor or "")
        sem_acento = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", sem_acento.lower()).strip()

    def _motivos_memoria_fraca(self, item, semelhantes=None, conflitos=None, conflitos_pendentes=None) -> list[str]:
        motivos = []
        confianca = float(item["confianca"] or 0)
        uso_count = int(item["uso_count"] or 0)
        tipo = str(item["tipo"] or "")
        valor = str(item["valor"] or "").strip()
        origem = str(item["origem"] or "")
        ultima_confirmacao = item["ultima_confirmacao"] if "ultima_confirmacao" in item.keys() else None
        criado_em = item["criado_em"] if "criado_em" in item.keys() else ""
        atualizado_em = item["atualizado_em"] if "atualizado_em" in item.keys() else ""

        if confianca < 0.7:
            motivos.append("baixa confianca")
        if tipo in {"assunto_atual", "reflexao"} and confianca < 0.9:
            motivos.append("conteudo temporario")
        if self._valor_vago(valor):
            motivos.append("conteudo vago ou incompleto")
        if origem.startswith("auto") and confianca < 0.85:
            motivos.append("origem automatica com confianca limitada")
        if not ultima_confirmacao and confianca < 0.85 and not self._memoria_nova(criado_em):
            motivos.append("falta confirmacao")
        if uso_count == 0 and confianca < 0.75 and not self._memoria_nova(criado_em):
            motivos.append("sem uso e baixa confianca")
        if self._memoria_antiga(atualizado_em) and not ultima_confirmacao and confianca < 0.9:
            motivos.append("memoria antiga sem confirmacao")
        if self._em_grupo(item, semelhantes or []):
            motivos.append("possivel semelhanca com outra memoria")
        if self._em_grupo(item, conflitos or []):
            motivos.append("possivel conflito com outra memoria")
        if any(int(conf["memoria_id"]) == int(item["id"]) for conf in (conflitos_pendentes or [])):
            motivos.append("conflito pendente")
        return motivos

    def _estado_revisao(self, item, motivos: list[str]) -> dict:
        historico = self.db.buscar_historico_memoria(int(item["id"]), limite=20)
        retomada = self._ultima_acao(historico, "revisao_retomada")
        adiada = self._ultima_acao(historico, "revisao_adiada")
        ignorada = self._ultima_acao(historico, "sugestao_ignorada")
        retomada_em = self._parse_data(retomada["criado_em"]) if retomada else None

        if adiada and self._acao_mais_recente_que_retomada(adiada, retomada_em):
            meta = self._parse_metadata(adiada["metadata"])
            ate = self._parse_data(meta.get("adiado_ate", ""))
            if ate and ate > datetime.now():
                return {"status": "adiada", **meta}

        if ignorada and self._acao_mais_recente_que_retomada(ignorada, retomada_em):
            meta = self._parse_metadata(ignorada["metadata"])
            mesma_memoria = meta.get("memoria_atualizada_em", "") == str(item["atualizado_em"] or "")
            mesmo_motivo = meta.get("motivos_hash", "") == self._motivos_hash(motivos)
            if mesma_memoria and mesmo_motivo:
                return {"status": "ignorada", **meta}
        return {"status": "pendente"}

    @staticmethod
    def _ultima_acao(historico, acao: str):
        return next((item for item in historico if item["acao"] == acao), None)

    def _acao_mais_recente_que_retomada(self, item, retomada_em) -> bool:
        if not retomada_em:
            return True
        data = self._parse_data(item["criado_em"])
        return bool(data and data > retomada_em)

    @staticmethod
    def _parse_metadata(metadata: str) -> dict[str, str]:
        dados = {}
        for parte in (metadata or "").split(";"):
            if "=" in parte:
                chave, valor = parte.split("=", 1)
                dados[chave.strip()] = valor.strip()
        return dados

    def _motivos_hash(self, motivos: list[str]) -> str:
        return "|".join(sorted(self._normalizar(motivo) for motivo in motivos if motivo))

    def _extrair_dias(self, texto: str, padrao: int) -> int:
        _, separador, resto = (texto or "").partition("|")
        if not separador:
            return padrao
        match = re.search(r"(\d+)", resto)
        if not match:
            return padrao
        return max(1, min(365, int(match.group(1))))

    def _extrair_motivo_revisao(self, texto: str) -> str:
        _, separador, resto = (texto or "").partition("|")
        if not separador:
            return "prazo padrao"
        motivo = re.sub(r"\b\d+\s*dias?\b", "", resto, flags=re.IGNORECASE).strip(" -;")
        return motivo or resto.strip() or "sem motivo informado"

    def _metadata_safe(self, valor: str) -> str:
        if self._parece_sensivel(valor):
            return "[conteudo sensivel ocultado]"
        return re.sub(r"[;\n\r]+", " ", valor or "").strip()

    def _formatar_memoria_curadoria(self, item, conflitos_pendentes=None) -> list[str]:
        motivos = self._motivos_memoria_fraca(item, conflitos_pendentes=conflitos_pendentes)
        linhas = [
            (
                f"- Memoria #{item['id']} [{self._dominio(item)}/{item['tipo']}] {item['chave']} = "
                f"{self._resumir_seguro(item)}"
            ),
            (
                f"  status={item['status']}; confianca={float(item['confianca']):.2f}; "
                f"origem={item['origem'] or 'indisponivel'}; criada={self._campo(item, 'criado_em')}; "
                f"ultimo_uso={self._campo(item, 'ultimo_uso')}; usos={item['uso_count']}"
            ),
            f"  motivo: {'; '.join(motivos) if motivos else 'indisponivel'}",
            "  acao recomendada: confirmar se correta, editar se incompleta, arquivar se nao serve, ou adiar/ignorar.",
        ]
        return linhas

    def _linha_memoria_resumida(self, item) -> str:
        return (
            f"- #{item['id']} [{self._dominio(item)}/{item['tipo']}] {item['chave']} = "
            f"{self._resumir_seguro(item, 100)} "
            f"(status {item['status']}, confianca {float(item['confianca']):.2f}, usos {item['uso_count']})"
        )

    def _resumir_seguro(self, item, limite: int = 160) -> str:
        return self._resumir_valor_seguro(str(item["valor"] or ""), f"{item['tipo']} {item['chave']} {item['origem']}", limite)

    def _resumir_valor_seguro(self, valor: str, contexto: str = "", limite: int = 160) -> str:
        if self._parece_sensivel(f"{contexto} {valor}"):
            return "[conteudo sensivel ocultado]"
        return self._resumir(valor, limite)

    @staticmethod
    def _parece_sensivel(texto: str) -> bool:
        patterns = [
            r"(?i)(senha|password|token|api[_-]?key|chave de api|credencial|segredo)",
            r"sk-[A-Za-z0-9_-]{10,}",
        ]
        return any(re.search(pattern, texto or "") for pattern in patterns)

    @staticmethod
    def _valor_vago(valor: str) -> bool:
        normalizado = CurationService._normalizar(valor)
        if len(normalizado) < 6:
            return True
        return normalizado in {"isso", "aquilo", "coisa", "nao sei", "talvez", "importante"}

    def _memoria_nova(self, criado_em: str) -> bool:
        data = self._parse_data(criado_em)
        return bool(data and datetime.now() - data < timedelta(days=7))

    def _memoria_antiga(self, atualizado_em: str) -> bool:
        data = self._parse_data(atualizado_em)
        return bool(data and datetime.now() - data > timedelta(days=90))

    @staticmethod
    def _parse_data(valor: str):
        if not valor:
            return None
        try:
            return datetime.fromisoformat(str(valor))
        except ValueError:
            return None

    @staticmethod
    def _em_grupo(item, grupos) -> bool:
        item_id = int(item["id"])
        return any(any(int(outro["id"]) == item_id for outro in grupo) for grupo in grupos)

    @staticmethod
    def _campo(item, chave: str) -> str:
        try:
            return item[chave] or "indisponivel"
        except (KeyError, IndexError):
            return "indisponivel"

    @staticmethod
    def _dominio(row) -> str:
        try:
            return row["dominio"] or "geral"
        except (KeyError, IndexError):
            return "geral"

    @staticmethod
    def _extrair_dominio_metadata(metadata: str) -> str:
        match = re.search(r"(?:^|;)dominio=([^;]+)", metadata or "")
        if not match:
            return "geral"
        return match.group(1).strip() or "geral"

    def _trocar_dominio_metadata(self, metadata: str, dominio: str) -> str:
        dominio = self._normalizar_dominio(dominio)
        metadata = (metadata or "").strip()
        if re.search(r"(?:^|;)dominio=[^;]+", metadata):
            return re.sub(r"(^|;)dominio=[^;]+", rf"\1dominio={dominio}", metadata)
        return f"{metadata};dominio={dominio}".strip(";")

    @staticmethod
    def _normalizar_dominio(dominio: str) -> str:
        normalized = CurationService._normalizar(dominio)
        aliases = {"programacao": "programacao", "codigo": "programacao", "estagio": "trabalho"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"pessoal", "estudo", "trabalho", "programacao", "aya", "geral"}:
            return "geral"
        return normalized

    @staticmethod
    def _extrair_id(texto: str) -> int | None:
        match = re.search(r"\d+", texto or "")
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _extrair_limite(texto: str, padrao: int) -> int:
        texto = (texto or "").strip()
        if texto.isdigit():
            return max(1, min(50, int(texto)))
        return padrao

    @staticmethod
    def _resumir(valor: str, limite: int = 160) -> str:
        resumo = (valor or "").replace("\n", " ").strip()
        if len(resumo) > limite:
            return resumo[: limite - 3] + "..."
        return resumo
