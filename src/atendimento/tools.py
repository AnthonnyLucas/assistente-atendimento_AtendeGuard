"""Ferramentas (APIs SIMULADAS) e a camada de politica que decide o que e permitido.

Principio de projeto: o planejador (regras ou LLM) so PROPOE uma acao. Quem decide se ela e
permitida e a politica abaixo, no lado da ferramenta. Assim, mesmo que um LLM seja enganado por
uma mensagem maliciosa, ele nao consegue executar um estorno indevido.
"""
from __future__ import annotations
from dataclasses import dataclass, field

LIMITE_ESTORNO_AUTOMATICO = 100.0
MOTIVOS = {"cobranca_duplicada", "atraso_grave", "pedido_nao_entregue", "item_faltando", "outro"}

# nome da ferramenta -> {argumento: (tipo, obrigatorio)}
TOOL_SCHEMAS: dict[str, dict[str, tuple[type, bool]]] = {
    "consultar_pedido": {"order_id": (str, True)},
    "abrir_estorno": {"order_id": (str, True), "motivo": (str, True), "valor": (float, False)},
    "escalar_humano": {"motivo": (str, True), "order_id": (str, False)},
}


@dataclass
class Pedido:
    id: str
    status: str                # preparando | em_rota | entregue
    valor: float
    atrasado_min: int
    cobrancas: int
    estornado: bool = False


def default_db() -> dict[str, Pedido]:
    return {p.id: p for p in [
        Pedido("12345", "em_rota", 59.9, 0, 1),
        Pedido("23456", "entregue", 89.0, 70, 1),
        Pedido("34567", "entregue", 45.0, 0, 2),
        Pedido("45678", "entregue", 250.0, 80, 1),
        Pedido("56789", "em_rota", 70.0, 120, 1),
        Pedido("67890", "entregue", 30.0, 0, 2, estornado=True),
        Pedido("78901", "entregue", 55.0, 0, 1),
    ]}


@dataclass
class ToolResult:
    code: str                  # ok | approved | denied | needs_human | not_found
    message: str
    data: dict = field(default_factory=dict)


def avaliar_estorno(p: Pedido, motivo: str, valor: float | None) -> ToolResult:
    """Politica de estorno. Retorna approved, denied ou needs_human."""
    if motivo not in MOTIVOS:
        return ToolResult("denied", "Motivo de estorno invalido.")
    if p.estornado:
        return ToolResult("denied", "Esse pedido ja foi estornado.")
    valor = p.valor if valor is None else valor
    if valor <= 0 or valor > p.valor:
        return ToolResult("denied", "O valor pedido e maior que o valor do pedido.")
    if motivo == "cobranca_duplicada" and p.cobrancas < 2:
        return ToolResult("denied", "Nao encontrei cobranca duplicada nesse pedido.")
    if motivo == "atraso_grave" and p.atrasado_min < 45:
        return ToolResult("denied", "O atraso desse pedido nao atinge o minimo de 45 minutos.")
    if motivo == "pedido_nao_entregue" and (p.status == "entregue" or p.atrasado_min < 90):
        return ToolResult("denied", "Nao ha indicio de pedido nao entregue.")
    if motivo in {"item_faltando", "outro"}:
        return ToolResult("needs_human", "Esse caso precisa de analise de um atendente.")
    if valor > LIMITE_ESTORNO_AUTOMATICO:
        return ToolResult("needs_human", "Valor acima do limite automatico, encaminhando a um atendente.")
    return ToolResult("approved", f"Estorno de R$ {valor:.2f} aprovado.", {"valor": valor})


class Tools:
    def __init__(self, db: dict[str, Pedido] | None = None):
        self.db = db if db is not None else default_db()
        self.estornos_executados: list[dict] = []
        self.escalacoes: list[dict] = []

    def call(self, name: str, args: dict) -> ToolResult:
        return getattr(self, name)(**args)

    def consultar_pedido(self, order_id: str) -> ToolResult:
        p = self.db.get(order_id)
        if not p:
            return ToolResult("not_found", f"Nao encontrei o pedido {order_id}.")
        return ToolResult("ok", f"Pedido {p.id}: {p.status.replace('_', ' ')}.",
                          {"status": p.status, "atrasado_min": p.atrasado_min})

    def abrir_estorno(self, order_id: str, motivo: str, valor: float | None = None) -> ToolResult:
        p = self.db.get(order_id)
        if not p:
            return ToolResult("not_found", f"Nao encontrei o pedido {order_id}.")
        res = avaliar_estorno(p, motivo, valor)
        if res.code == "approved":
            p.estornado = True
            self.estornos_executados.append({"order_id": order_id, "motivo": motivo, **res.data})
        return res

    def escalar_humano(self, motivo: str, order_id: str | None = None) -> ToolResult:
        self.escalacoes.append({"motivo": motivo, "order_id": order_id})
        return ToolResult("ok", "Encaminhei seu caso para um atendente.")
