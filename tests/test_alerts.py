from __future__ import annotations

from aya.core.alerts import Alert, AlertService, formatar_alertas


class FakeCuration:
    def __init__(self, fracas: int = 0, adiadas: int = 0, ignoradas: int = 0):
        self._fracas = fracas
        self._adiadas = adiadas
        self._ignoradas = ignoradas

    def resumo_higiene(self) -> dict:
        return {
            "fracas": self._fracas,
            "adiadas": self._adiadas,
            "ignoradas": self._ignoradas,
        }


class FakeDBMinimal:
    pass


class FakeDBNoConnection:
    def buscar_revisoes_pendentes(self) -> list[dict]:
        return [{"id": 1}]


class FakeConnection:
    def __init__(self):
        self.executes: list[str] = []

    def execute(self, query: str, *args):
        self.executes.append(query)

        class FakeCursor:
            def fetchone(self):
                return (0,)

        return FakeCursor()


class FakeDBWithConnection:
    def __init__(self):
        self.connection = FakeConnection()

    def buscar_revisoes_pendentes(self) -> list[dict]:
        return []

    def contar_exercicios_pendentes(self) -> int:
        return 0

    def listar_conflitos_memoria(self) -> list[dict]:
        return []

    def contar_conflitos_memoria(self) -> int:
        return 0

    def buscar_metas_ativas(self) -> list[dict]:
        return []

    def contar_aprendizados_pendentes(self) -> int:
        return 0

    def buscar_memorias_para_revisao(self) -> list[dict]:
        return []


class FakeProposal:
    def __init__(self, state: str):
        self.state = state


class FakeAyaDev:
    def __init__(self, proposals=None):
        self.proposals = proposals or {}


def test_sem_alertas_retorna_vazio():
    assert AlertService(FakeDBWithConnection()).collect() == []


def test_sem_alertas_mensagem_tranquila():
    message = formatar_alertas(AlertService(FakeDBWithConnection()).collect())
    assert "Tudo em ordem" in message


def test_revisao_pendente_aparece():
    db = FakeDBWithConnection()
    db.buscar_revisoes_pendentes = lambda: [{"id": 1}, {"id": 2}]

    alerts = AlertService(db).collect()

    assert len(alerts) == 1
    assert alerts[0].kind == "revisao"
    assert "2" in alerts[0].detail


def test_meta_ativa_aparece():
    db = FakeDBWithConnection()
    db.buscar_metas_ativas = lambda: [{"id": 1}]

    alerts = AlertService(db).collect()

    assert any(item.kind == "meta" for item in alerts)


def test_conflito_pendente_aparece():
    db = FakeDBWithConnection()
    db.listar_conflitos_memoria = lambda: [{"id": 1}]

    alerts = AlertService(db).collect()

    assert any(item.kind == "memoria" for item in alerts)


def test_curadoria_com_curation_respeita_adiadas_ignoradas():
    db = FakeDBWithConnection()
    db.contar_aprendizados_pendentes = lambda: 2
    curation = FakeCuration(fracas=3, adiadas=5, ignoradas=2)

    alerts = AlertService(db, curation=curation).collect()
    curadoria = [item for item in alerts if item.kind == "curadoria"][0]

    assert "5" in curadoria.detail
    assert "adiadas" not in curadoria.detail.lower()
    assert "ignoradas" not in curadoria.detail.lower()


def test_curadoria_sem_curation_usa_aprendizados():
    db = FakeDBWithConnection()
    db.contar_aprendizados_pendentes = lambda: 4

    alerts = AlertService(db, curation=None).collect()

    assert any(item.kind == "curadoria" and "4" in item.detail for item in alerts)


def test_aya_dev_pendente_aparece():
    dev = FakeAyaDev({"p1": FakeProposal("AGUARDANDO_APROVACAO")})

    alerts = AlertService(FakeDBWithConnection(), aya_dev=dev).collect()

    assert any(item.kind == "sugestao" and "Aya Dev" in item.title for item in alerts)


def test_aya_dev_critico_e_alta_prioridade():
    dev = FakeAyaDev(
        {
            "p1": FakeProposal("REVERSAO_PARCIAL"),
            "p2": FakeProposal("AGUARDANDO_APROVACAO"),
        }
    )

    alerts = AlertService(FakeDBWithConnection(), aya_dev=dev).collect()

    assert alerts[0].kind == "critico"
    assert alerts[0].priority == 1


def test_ordem_deterministica():
    db = FakeDBWithConnection()
    db.buscar_revisoes_pendentes = lambda: [{"id": 1}]
    db.listar_conflitos_memoria = lambda: [{"id": 1}]

    service = AlertService(db)
    alerts = service.collect()

    assert alerts == service.collect()
    for left, right in zip(alerts, alerts[1:], strict=False):
        assert (left.priority, left.kind, left.title) <= (right.priority, right.kind, right.title)


def test_somente_leitura_nao_chama_sql_quando_metodos_reais_existem():
    db = FakeDBWithConnection()
    db.buscar_revisoes_pendentes = lambda: [{"id": 1}]

    AlertService(db).collect()

    assert db.connection.executes == []


def test_sem_aya_dev():
    alerts = AlertService(FakeDBWithConnection(), aya_dev=None).collect()

    assert not any("Aya Dev" in item.title for item in alerts)


def test_sem_curation():
    alerts = AlertService(FakeDBWithConnection(), curation=None).collect()

    assert isinstance(alerts, list)


def test_fake_db_sem_connection_e_sem_metodos():
    assert AlertService(FakeDBMinimal()).collect() == []


def test_fake_db_sem_connection_com_metodos():
    alerts = AlertService(FakeDBNoConnection()).collect()

    assert any(item.kind == "revisao" for item in alerts)


def test_formatar_alertas_vazio():
    assert "Tudo em ordem" in formatar_alertas([])


def test_formatar_alertas_com_conteudo():
    message = formatar_alertas([Alert("revisao", "Revisoes", "1 pendente", "/revisoes", 2)])

    assert "Revisoes" in message
    assert "/revisoes" in message
    assert "Sugestao" in message
