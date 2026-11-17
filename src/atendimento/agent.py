"""Agente: planeja, VALIDA, executa a ferramenta (com politica) e monta a resposta."""
from __future__ import annotations
from dataclasses import dataclass

from .planner import Action, Planner
from .tools import TOOL_SCHEMAS, Tools


@dataclass
class Resultado:
    reply: str
    outcome: str       # consultou | estorno_aprovado | estorno_negado | escalou | perguntou | respondeu | recusou | erro_pedido
    trace: list[dict]
    escalated: bool = False


def validar_chamada(name: str, args: dict) -> str | None:
    """Valida contra o esquema. Retorna mensagem de erro ou None se estiver ok."""
    spec = TOOL_SCHEMAS.get(name)
    if spec is None:
        return f"ferramenta desconhecida: {name}"
    extras = set(args) - set(spec)
    if extras:
        return f"argumentos nao permitidos: {sorted(extras)}"
    for arg, (tipo, obrigatorio) in spec.items():
        if arg not in args:
            if obrigatorio:
                return f"falta o argumento {arg}"
            continue
        v = args[arg]
        if tipo is float and isinstance(v, (int, float)) and not isinstance(v, bool):
            continue
        if not isinstance(v, tipo):
            return f"tipo invalido em {arg}"
    return None


class Agent:
    def __init__(self, planner: Planner, tools: Tools | None = None):
        self.planner = planner
        self.tools = tools or Tools()

    def handle(self, message: str, session: dict | None = None) -> Resultado:
        if not message or not message.strip():
            raise ValueError("Mensagem vazia")
        session = session if session is not None else {}
        act: Action = self.planner.plan(message, session)
        trace = [{"proposta": act.kind, "tool": act.tool, "args": act.args}]
        if act.kind == "ask":
            return Resultado(act.text, "perguntou", trace)
        if act.kind == "reply":
            return Resultado(act.text, "respondeu", trace)
        if act.kind != "tool":
            return Resultado(act.text or "Nao consigo ajudar com isso.", "recusou", trace)

        erro = validar_chamada(act.tool or "", act.args)
        if erro:
            trace.append({"validacao": "rejeitada", "motivo": erro})
            return Resultado("Nao consegui processar esse pedido. Vou chamar um atendente.", "recusou", trace)

        if act.args.get("order_id"):
            session["order_id"] = act.args["order_id"]
        res = self.tools.call(act.tool, act.args)
        trace.append({"resultado": res.code, "mensagem": res.message})

        if act.tool == "consultar_pedido":
            return Resultado(res.message, "consultou" if res.code == "ok" else "erro_pedido", trace)
        if act.tool == "escalar_humano":
            return Resultado(res.message, "escalou", trace, escalated=True)
        # abrir_estorno
        if res.code == "approved":
            return Resultado(res.message, "estorno_aprovado", trace)
        if res.code == "not_found":
            return Resultado(res.message, "erro_pedido", trace)
        if res.code == "needs_human":
            esc = self.tools.escalar_humano(motivo="estorno_requer_analise", order_id=act.args.get("order_id"))
            trace.append({"escalada": esc.message})
            return Resultado(res.message + " " + esc.message, "escalou", trace, escalated=True)
        return Resultado(res.message, "estorno_negado", trace)
