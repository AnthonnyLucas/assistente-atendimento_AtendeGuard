"""Planejadores: decidem QUAL acao propor. Trocaveis (regras ou LLM)."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .text import extract_amount, extract_order_id, normalize


@dataclass
class Action:
    kind: str                       # tool | ask | reply | refuse
    tool: str | None = None
    args: dict = field(default_factory=dict)
    text: str = ""


class Planner(Protocol):
    def plan(self, message: str, session: dict) -> Action: ...


def _has(t: str, words: tuple[str, ...]) -> bool:
    return any(w in t for w in words)


class RuleBasedPlanner:
    """Baseline deterministico: palavras-chave + extracao de entidades. Roda offline."""

    HUMANO = ("atendente", "humano", "pessoa de verdade", "falar com alguem")
    ESTORNO = ("estorn", "reembols", "dinheiro de volta", "devolver o dinheiro", "devolvam",
               "cobrado duas vezes", "cobraram duas vezes", "cobrou dobro", "cobranca duplicada")
    STATUS = ("onde esta", "cade", "status", "rastre", "quando chega", "ja saiu", "chegou")
    SAUDACAO = ("oi", "ola", "bom dia", "boa tarde", "boa noite", "obrigado", "valeu")

    def plan(self, message: str, session: dict) -> Action:
        t = normalize(message)
        order_id = extract_order_id(message) or session.get("order_id")

        if _has(t, self.HUMANO):
            return Action("tool", "escalar_humano", {"motivo": "pedido_do_cliente", **({"order_id": order_id} if order_id else {})})

        if _has(t, self.ESTORNO):
            if not order_id:
                return Action("ask", text="Claro. Qual e o numero do pedido?")
            args = {"order_id": order_id, "motivo": self._motivo(t)}
            valor = extract_amount(message)
            if valor is not None:
                args["valor"] = valor
            return Action("tool", "abrir_estorno", args)

        if _has(t, self.STATUS) or "pedido" in t:
            if not order_id:
                return Action("ask", text="Pode me passar o numero do pedido?")
            return Action("tool", "consultar_pedido", {"order_id": order_id})

        limpo = " " + re.sub(r"[^a-z0-9 ]", " ", t) + " "
        if any(f" {w} " in limpo for w in self.SAUDACAO):
            return Action("reply", text="Ola! Posso ajudar com status de pedido, estorno ou falar com um atendente.")
        return Action("refuse", text="Posso ajudar so com pedidos, estornos e atendimento. Sobre isso nao consigo ajudar.")

    @staticmethod
    def _motivo(t: str) -> str:
        if _has(t, ("duas vezes", "dobro", "duplic")):
            return "cobranca_duplicada"
        if _has(t, ("faltando", "faltou", "veio so", "item")):
            return "item_faltando"
        if _has(t, ("nao chegou", "nao recebi", "nao foi entregue", "nunca chegou")):
            return "pedido_nao_entregue"
        if _has(t, ("atras", "demor")):
            return "atraso_grave"
        return "outro"


class LLMPlanner:
    """Planejador via LLM com chamada de funcao (API compativel com OpenAI).

    NAO FOI EXECUTADO no desenvolvimento (sem acesso a API no ambiente). Serve de ponto de
    integracao: mesmo que o LLM erre ou seja enganado, a politica em tools.py barra acoes
    indevidas, porque a decisao final nunca fica com o modelo.
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model

    def plan(self, message: str, session: dict) -> Action:
        tools = [{"type": "function", "function": {
            "name": name, "description": f"Ferramenta {name}",
            "parameters": {"type": "object",
                           "properties": {a: {"type": "number" if tp is float else "string"} for a, (tp, _) in spec.items()},
                           "required": [a for a, (_, req) in spec.items() if req]}}}
            for name, spec in __import__("atendimento.tools", fromlist=["TOOL_SCHEMAS"]).TOOL_SCHEMAS.items()]
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, tools=tools,
            messages=[{"role": "system", "content": "Voce e atendente de delivery. Use ferramentas quando couber; "
                       "se faltar o numero do pedido, pergunte; fora do escopo, recuse."},
                      {"role": "user", "content": message}])
        msg = r.choices[0].message
        if msg.tool_calls:
            c = msg.tool_calls[0].function
            return Action("tool", c.name, json.loads(c.arguments))
        return Action("reply", text=(msg.content or "").strip())
