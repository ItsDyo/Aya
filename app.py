from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

import gradio as gr

from aya.config import SERVER_CONFIG, ServerConfig
from aya.core.assistant import Assistant
from aya.core.permissions import AccessChannel
from aya.core.voice import VoiceIO
from aya.paths import LOG_PATH, ensure_runtime_dirs
from aya.ui.controller import UIController


ensure_runtime_dirs()
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


APP_THEME = gr.themes.Soft(
    primary_hue="orange",
    neutral_hue="slate",
    radius_size="sm",
    text_size="md",
)


APP_CSS = """
:root {
    --aya-bg: #080c14;
    --aya-panel: #0f1726;
    --aya-panel-soft: #111b2c;
    --aya-border: rgba(148, 163, 184, 0.18);
    --aya-text-soft: #9ca3af;
}
body,
.gradio-container {
    background: var(--aya-bg) !important;
}
.gradio-container {
    max-width: 1440px !important;
    margin: 0 auto !important;
    padding: 14px 28px 28px !important;
}
.aya-header {
    padding: 10px 0 2px;
    text-align: center;
}
.aya-header h1 {
    margin: 0;
    font-size: 34px;
    font-weight: 720;
    letter-spacing: 0;
}
.aya-header p {
    margin: 6px 0 0;
    color: #a8acb8;
    font-size: 15px;
}
.aya-shell {
    gap: 16px;
    align-items: stretch;
}
.aya-workspace {
    max-width: 1180px;
    margin: 0 auto;
}
.aya-chat-shell {
    max-width: 1020px;
    margin: 0 auto;
}
.aya-side {
    min-width: 320px;
}
.aya-muted textarea,
.aya-muted input {
    font-size: 13px !important;
}
.aya-chatbox {
    min-height: 64vh;
}
.aya-chatbox,
.aya-input,
.aya-tools,
.aya-side,
.gradio-accordion,
.form {
    border-color: var(--aya-border) !important;
}
.aya-chatbox,
.aya-input textarea,
textarea,
input {
    background: var(--aya-panel) !important;
}
.aya-input textarea {
    min-height: 76px !important;
    border-radius: 8px !important;
}
.aya-side textarea {
    font-size: 13px !important;
}
.aya-compact button {
    min-height: 38px !important;
}
button {
    border-radius: 8px !important;
    box-shadow: none !important;
}
button.primary {
    font-weight: 700 !important;
}
.block-title,
.label-wrap,
.label-wrap span,
span[data-testid="block-info"] {
    background: transparent !important;
    border: 0 !important;
    color: #cbd5e1 !important;
    padding: 0 0 6px 0 !important;
    font-size: 13px !important;
    font-weight: 650 !important;
}
.block {
    border-radius: 8px !important;
}
.gradio-accordion {
    background: var(--aya-panel-soft) !important;
    border-radius: 8px !important;
}
.aya-tools {
    max-width: 1020px;
    margin: 12px auto 0;
}
div[role="tablist"] {
    justify-content: center;
    border-bottom: 1px solid var(--aya-border) !important;
}
button[role="tab"] {
    font-weight: 600 !important;
    background: transparent !important;
}
label,
.wrap span {
    color: var(--aya-text-soft) !important;
}
footer {
    visibility: hidden;
}
"""


def make_auth_checker(config: ServerConfig = SERVER_CONFIG) -> Callable[[str, str], bool] | None:
    if not config.auth_enabled:
        return None
    expected_user = config.auth_user
    expected_password = config.auth_password
    if not expected_user or not expected_password:
        return None

    def check(username: str, password: str) -> bool:
        user_ok = hmac.compare_digest(username or "", expected_user)
        password_ok = hmac.compare_digest(password or "", expected_password)
        return user_ok and password_ok

    return check


def build_launch_kwargs(config: ServerConfig = SERVER_CONFIG) -> dict[str, object]:
    if config.share:
        raise RuntimeError("AYA_GRADIO_SHARE/share=True nao e permitido para a Aya.")
    if config.is_network_exposed and not config.auth_enabled:
        raise RuntimeError("Modo remoto/rede exige AYA_AUTH_ENABLED=true.")
    if config.is_network_exposed and config.auth is None:
        raise RuntimeError(
            "Modo remoto/rede exige AYA_AUTH_USERNAME e AYA_AUTH_PASSWORD configurados."
        )

    return {
        "server_name": config.host,
        "server_port": config.port,
        "auth": make_auth_checker(config),
        "share": False,
        "theme": APP_THEME,
        "css": APP_CSS,
    }


def create_app(
    assistant: Assistant | None = None,
    config: ServerConfig = SERVER_CONFIG,
) -> gr.Blocks:
    aya = assistant or Assistant()
    channel = AccessChannel.REMOTE_GRADIO if config.is_network_exposed else AccessChannel.LOCAL_GRADIO
    admin_visible = channel != AccessChannel.REMOTE_GRADIO
    ui = UIController(aya, VoiceIO(), channel=channel)

    with gr.Blocks(title="Aya", fill_width=True) as demo:
        gr.HTML(
            """
            <div class="aya-header">
                <h1>Aya</h1>
                <p>Assistente local de estudos, memória, código e companhia.</p>
            </div>
            """
        )

        with gr.Tab("Conversar"):
            with gr.Column(elem_classes="aya-chat-shell"):
                chatbot = gr.Chatbot(label=None, height=640, elem_classes="aya-chatbox")
                mensagem = gr.Textbox(
                    show_label=False,
                    placeholder="Converse naturalmente com a Aya...",
                    lines=3,
                    max_lines=8,
                    elem_classes="aya-input",
                )
                with gr.Row(elem_classes="aya-compact"):
                    enviar = gr.Button("Enviar", variant="primary")
                    limpar_chat = gr.Button("Limpar")
                enviar.click(ui.conversar, inputs=[mensagem, chatbot], outputs=[chatbot, mensagem])
                mensagem.submit(ui.conversar, inputs=[mensagem, chatbot], outputs=[chatbot, mensagem])
                limpar_chat.click(lambda: [], outputs=chatbot)

            with gr.Accordion("Painel, status e voz", open=False, elem_classes="aya-tools"):
                with gr.Row(elem_classes="aya-shell"):
                    with gr.Column(scale=5, min_width=320, elem_classes="aya-side"):
                        saida_lateral = gr.Textbox(label="Painel", lines=22, value=ui.painel())
                        with gr.Row(elem_classes="aya-compact"):
                            atualizar_painel = gr.Button("Painel", variant="primary")
                            ver_continuidade = gr.Button("Continuidade")
                        with gr.Row(elem_classes="aya-compact"):
                            ver_status = gr.Button("Status")
                            diagnostico = gr.Button("Diagnóstico")
                        atualizar_painel.click(ui.painel, outputs=saida_lateral)
                        ver_continuidade.click(ui.continuidade, outputs=saida_lateral)
                        ver_status.click(ui.status, outputs=saida_lateral)
                        diagnostico.click(ui.diagnostico, outputs=saida_lateral)

                    with gr.Column(scale=4, min_width=300):
                        audio_entrada = gr.Audio(label="Fale com a Aya", sources=["microphone"], type="filepath")
                        texto_fallback = gr.Textbox(label="Texto opcional", lines=2)
                        modo_voz = gr.Radio(label="Modo", choices=["Normal", "Companhia"], value="Normal")
                        falar = gr.Button("Enviar por voz", variant="primary")
                        texto_transcrito = gr.Textbox(label="Texto entendido", lines=2)
                        resposta_voz = gr.Textbox(label="Resposta", lines=5)
                        audio_saida = gr.Audio(label="Aya falando", type="filepath")
                        falar.click(
                            ui.conversar_voz,
                            inputs=[audio_entrada, texto_fallback, modo_voz],
                            outputs=[texto_transcrito, resposta_voz, audio_saida],
                        )

        with gr.Tab("Companhia"):
            with gr.Column(elem_classes="aya-chat-shell"):
                chat_companhia = gr.Chatbot(label=None, height=600)
                mensagem_companhia = gr.Textbox(
                    show_label=False,
                    placeholder="Conte como foi seu dia, desabafe ou peça um conselho...",
                    lines=3,
                    max_lines=8,
                    elem_classes="aya-input",
                )
                enviar_companhia = gr.Button("Conversar", variant="primary")
                enviar_companhia.click(
                    ui.conversar_companhia,
                    inputs=[mensagem_companhia, chat_companhia],
                    outputs=[chat_companhia, mensagem_companhia],
                )
                mensagem_companhia.submit(
                    ui.conversar_companhia,
                    inputs=[mensagem_companhia, chat_companhia],
                    outputs=[chat_companhia, mensagem_companhia],
                )

            with gr.Accordion("Diário e atalhos", open=False, elem_classes="aya-tools"):
                with gr.Row(elem_classes="aya-shell"):
                    with gr.Column(scale=3, min_width=260):
                        incentivo = gr.Button("Incentivo")
                        conselho = gr.Button("Conselho")
                        ver_diario = gr.Button("Ver diário", variant="primary")
                    with gr.Column(scale=7, min_width=420):
                        saida_companhia = gr.Textbox(label="Diario", lines=16)
                        incentivo.click(ui.incentivo, outputs=saida_companhia)
                        conselho.click(ui.conselho, outputs=saida_companhia)
                        ver_diario.click(ui.diario, outputs=saida_companhia)

        with gr.Tab("Estudo"):
            with gr.Row(elem_classes=["aya-shell", "aya-workspace"]):
                with gr.Column(scale=4, min_width=280):
                    with gr.Accordion("Sessão de estudo", open=True):
                        materia = gr.Textbox(label="Matéria", placeholder="Ex: Matemática")
                        minutos = gr.Number(label="Minutos planejados", value=25, precision=0)
                        iniciar = gr.Button("Iniciar sessão", variant="primary")
                        notas = gr.Textbox(label="Notas ao encerrar", lines=4)
                        encerrar = gr.Button("Encerrar sessão")

                    with gr.Accordion("Metas e dificuldades", open=False):
                        tipo_meta = gr.Dropdown(
                            label="Tipo da meta",
                            choices=["diaria", "semanal", "mensal", "geral"],
                            value="semanal",
                        )
                        descricao_meta = gr.Textbox(label="Descrição da meta")
                        criar_meta = gr.Button("Criar meta")
                        materia_dif = gr.Textbox(label="Matéria com dificuldade")
                        topico_dif = gr.Textbox(label="Tópico difícil")
                        desc_dif = gr.Textbox(label="Descrição", lines=3)
                        dificuldade = gr.Button("Registrar dificuldade")

                with gr.Column(scale=4, min_width=280):
                    with gr.Accordion("Exercícios e revisão", open=True):
                        topico_exercicio = gr.Textbox(label="Tópico do exercício", placeholder="Ex: listas em Python")
                        nivel_exercicio = gr.Dropdown(label="Nível", choices=["facil", "medio", "dificil"], value="medio")
                        gerar_exercicio = gr.Button("Gerar exercício", variant="primary")
                        exercicio_id = gr.Number(label="ID do exercício", precision=0)
                        resposta_exercicio = gr.Textbox(label="Sua resposta", lines=5)
                        corrigir_exercicio = gr.Button("Corrigir resposta")
                        ver_revisoes = gr.Button("Ver revisões")

                with gr.Column(scale=4, min_width=320):
                    saida_estudo = gr.Textbox(label="Resultado", lines=22)
                    iniciar.click(ui.iniciar_sessao, inputs=[materia, minutos], outputs=saida_estudo)
                    encerrar.click(ui.encerrar_sessao, inputs=notas, outputs=saida_estudo)
                    criar_meta.click(ui.criar_meta, inputs=[tipo_meta, descricao_meta], outputs=saida_estudo)
                    dificuldade.click(
                        ui.registrar_dificuldade,
                        inputs=[materia_dif, topico_dif, desc_dif],
                        outputs=saida_estudo,
                    )
                    gerar_exercicio.click(ui.criar_exercicio, inputs=[topico_exercicio, nivel_exercicio], outputs=saida_estudo)
                    corrigir_exercicio.click(ui.responder_exercicio, inputs=[exercicio_id, resposta_exercicio], outputs=saida_estudo)
                    ver_revisoes.click(ui.revisoes, outputs=saida_estudo)

        with gr.Tab("Conhecimento"):
            with gr.Row(elem_classes=["aya-shell", "aya-workspace"]):
                with gr.Column(scale=5, min_width=320):
                    with gr.Accordion("Salvar conhecimento", open=True):
                        topico = gr.Textbox(label="Tópico", placeholder="Ex: Python - listas")
                        conteudo = gr.Textbox(label="Conteúdo", lines=8)
                        tags = gr.Textbox(label="Tags", placeholder="python, estudo, exemplo")
                        salvar = gr.Button("Salvar conhecimento", variant="primary")

                    with gr.Accordion("Memória manual", open=False):
                        tipo_memoria = gr.Textbox(label="Tipo", placeholder="perfil, objetivo, preferencia, estudo")
                        chave_memoria = gr.Textbox(label="Chave", placeholder="nome, quer_aprender, linguagem")
                        valor_memoria = gr.Textbox(label="Valor", lines=3)
                        salvar_memoria = gr.Button("Salvar memória")

                with gr.Column(scale=4, min_width=300):
                    with gr.Accordion("Buscar no conhecimento", open=True):
                        consulta_rag = gr.Textbox(label="Busca", placeholder="Digite um tema para buscar no conhecimento local", lines=3)
                        buscar_rag = gr.Button("Buscar contexto", variant="primary")
                        buscar_fontes = gr.Button("Ver fontes")

                    with gr.Accordion("Ingestão de arquivos", open=False, visible=admin_visible):
                        caminho_ingestao = gr.Textbox(label="Arquivo ou pasta para ingerir", placeholder="Ex: README.md ou .")
                        ingerir_arquivos = gr.Button("Ingerir arquivos")
                        with gr.Row():
                            status_rag = gr.Button("Status do RAG")
                            reindexar_rag = gr.Button("Reindexar")

                with gr.Column(scale=4, min_width=320):
                    saida_conhecimento = gr.Textbox(label="Resultado", lines=22)
                    salvar.click(ui.salvar_conhecimento, inputs=[topico, conteudo, tags], outputs=saida_conhecimento)
                    salvar_memoria.click(ui.lembrar, inputs=[tipo_memoria, chave_memoria, valor_memoria], outputs=saida_conhecimento)
                    buscar_rag.click(ui.consultar_rag, inputs=consulta_rag, outputs=saida_conhecimento)
                    buscar_fontes.click(ui.consultar_fontes, inputs=consulta_rag, outputs=saida_conhecimento)
                    ingerir_arquivos.click(ui.ingerir, inputs=caminho_ingestao, outputs=saida_conhecimento)
                    status_rag.click(ui.status_rag, outputs=saida_conhecimento)
                    reindexar_rag.click(ui.reindexar_rag, outputs=saida_conhecimento)

        with gr.Tab("Sistema"):
            with gr.Row(elem_classes=["aya-shell", "aya-workspace"]):
                with gr.Column(scale=4, min_width=320):
                    saida_sistema = gr.Textbox(label="Curadoria", lines=24)
                    atualizar_curadoria = gr.Button("Atualizar curadoria", variant="primary")
                    atualizar_curadoria.click(ui.listar_curadoria, outputs=saida_sistema)

                with gr.Column(scale=4, min_width=300):
                    with gr.Accordion("Memórias e aprendizados", open=True):
                        memoria_curadoria_id = gr.Number(label="ID da memória", precision=0)
                        with gr.Row():
                            confirmar_curadoria = gr.Button("Confirmar")
                            arquivar_curadoria = gr.Button("Arquivar")
                        aprendizado_curadoria_id = gr.Number(label="ID do aprendizado", precision=0)
                        with gr.Row():
                            aprovar_curadoria = gr.Button("Aprovar")
                            rejeitar_curadoria = gr.Button("Rejeitar")
                        listar_aprendizados = gr.Button("Listar aprendizados")

                    with gr.Accordion("Conflitos e fusões", open=False):
                        conflito_id = gr.Number(label="ID do conflito", precision=0)
                        decisao_conflito = gr.Radio(
                            label="Decisão",
                            choices=["aceitar", "rejeitar"],
                            value="rejeitar",
                        )
                        with gr.Row():
                            listar_conflitos = gr.Button("Listar conflitos")
                            resolver_conflito = gr.Button("Resolver")
                        memoria_principal_id = gr.Number(label="Memória principal", precision=0)
                        memoria_duplicada_id = gr.Number(label="Memória duplicada", precision=0)
                        fundir_memorias = gr.Button("Fundir memórias")
                        historico_memoria_id = gr.Number(label="Memória para histórico", precision=0)
                        ver_historico_memoria = gr.Button("Ver histórico")

                    with gr.Accordion("Autonomia", open=False, visible=admin_visible):
                        refletir = gr.Button("Gerar reflexão")
                        autonomia = gr.Button("Ver autonomia")
                        with gr.Row():
                            autonomia_on = gr.Button("Ligar")
                            autonomia_off = gr.Button("Desligar")

                with gr.Column(scale=4, min_width=320):
                    with gr.Accordion(
                        "Diagnóstico e exportação",
                        open=True,
                        visible=admin_visible,
                    ):
                        saida_diag = gr.Textbox(label="Diagnóstico", lines=14)
                        diagnostico_sistema = gr.Button("Rodar diagnóstico", variant="primary")
                        finetune = gr.Button("Exportar dataset")
                        modelos = gr.Button("Modelos")

                    with gr.Accordion("Backups", open=False, visible=admin_visible):
                        caminho_backup = gr.Textbox(label="Backup para verificar", placeholder="Ex: aya_backup_20260710_120000.zip")
                        criar_backup = gr.Button("Criar backup", variant="primary")
                        listar_backups = gr.Button("Listar backups")
                        verificar_backup = gr.Button("Verificar backup")
                        extrair_backup = gr.Button("Extrair backup")

                    diagnostico_sistema.click(ui.diagnostico, outputs=saida_diag)
                    finetune.click(ui.exportar_fine_tuning, outputs=saida_diag)
                    modelos.click(ui.modelos, outputs=saida_diag)
                    criar_backup.click(ui.criar_backup, outputs=saida_diag)
                    listar_backups.click(ui.listar_backups, outputs=saida_diag)
                    verificar_backup.click(ui.verificar_backup, inputs=caminho_backup, outputs=saida_diag)
                    extrair_backup.click(ui.extrair_backup, inputs=caminho_backup, outputs=saida_diag)

                confirmar_curadoria.click(ui.confirmar_memoria, inputs=memoria_curadoria_id, outputs=saida_sistema)
                arquivar_curadoria.click(ui.esquecer_memoria, inputs=memoria_curadoria_id, outputs=saida_sistema)
                aprovar_curadoria.click(ui.aprovar_aprendizado, inputs=aprendizado_curadoria_id, outputs=saida_sistema)
                rejeitar_curadoria.click(ui.rejeitar_aprendizado, inputs=aprendizado_curadoria_id, outputs=saida_sistema)
                listar_aprendizados.click(ui.listar_aprendizados, outputs=saida_sistema)
                listar_conflitos.click(ui.listar_conflitos, outputs=saida_sistema)
                resolver_conflito.click(
                    ui.resolver_conflito,
                    inputs=[conflito_id, decisao_conflito],
                    outputs=saida_sistema,
                )
                fundir_memorias.click(
                    ui.fundir_memorias,
                    inputs=[memoria_principal_id, memoria_duplicada_id],
                    outputs=saida_sistema,
                )
                ver_historico_memoria.click(
                    ui.historico_memoria,
                    inputs=historico_memoria_id,
                    outputs=saida_sistema,
                )
                refletir.click(ui.refletir, outputs=saida_sistema)
                autonomia.click(ui.autonomia, outputs=saida_sistema)
                autonomia_on.click(lambda: ui.autonomia("on"), outputs=saida_sistema)
                autonomia_off.click(lambda: ui.autonomia("off"), outputs=saida_sistema)

    return demo


if __name__ == "__main__":
    print(f"Aya iniciando em {SERVER_CONFIG.public_url_hint}")
    if SERVER_CONFIG.remote_mode:
        print("Modo remoto ativo. Use Tailscale Serve; nao use Funnel nem porta publica.")
    elif SERVER_CONFIG.is_network_exposed:
        print("Modo de rede ativo. Use somente com VPN privada e senha forte.")
    create_app().launch(**build_launch_kwargs())
